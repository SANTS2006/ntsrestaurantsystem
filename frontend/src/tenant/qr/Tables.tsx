import { Download, Plus, Printer } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE } from '../../lib/config'
import { ApiError, api, downloadFile, tokenStore, type Page } from '../../lib/api'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'
import { useConfirm } from '../../ui/dialogs'

export type Table = { id: number; label: string; seats: number | null; is_active: boolean; branch: number; branch_name: string; qr_url: string; qr_regenerated_at: string | null }
type BranchRow = { id: number; name: string; status: string }
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')

/** The QR image endpoint needs the staff token, so it is fetched with it and shown from a blob URL. */
export function QrImage({ id, version, size = 96 }: { id: number; version: string | null; size?: number }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let url = ''
    let live = true
    const t = tokenStore.get()
    fetch(`${API_BASE}/api/v1/qr-menu/tables/${id}/qr/`, { headers: t ? { Authorization: `Bearer ${t.access}` } : {} })
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((b) => { if (live) { url = URL.createObjectURL(b); setSrc(url) } })
      .catch(() => live && setSrc(''))
    return () => { live = false; if (url) URL.revokeObjectURL(url) }
  }, [id, version])
  return src ? <img src={src} alt={`QR code for table ${id}`} width={size} height={size} style={{ imageRendering: 'pixelated' }} /> : <span className="skeleton" style={{ display: 'inline-block', width: size, height: size }} />
}

export default function Tables() {
  const confirm = useConfirm()
  useDocumentTitle('Tables and QR codes')
  const toast = useToast()
  const list = useAsync(() => api<Page<Table>>('/qr-menu/tables/', { params: { page_size: 100 } }), [])
  const branches = useAsync(() => api<Page<BranchRow>>('/restaurants/branches/', { params: { page_size: 100 } }), [])
  const [edit, setEdit] = useState<Table | 'new' | null>(null)

  async function act(t: Table, path: string, ok: string) {
    try { await api(`/qr-menu/tables/${t.id}/${path}/`, { body: {} }); toast(ok); list.reload() } catch (e) { toast(msg(e)) }
  }
  return (
    <>
      <div className="toolbar"><h1 style={{ fontSize: '1.7rem', margin: 0, flex: 1 }}>Tables and QR codes</h1>
        <Link className="btn secondary" to="/manage/tables/print"><Printer size={16} aria-hidden /> Print all</Link>
        <button className="btn" onClick={() => setEdit('new')}><Plus size={18} aria-hidden /> Add table</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading ? <Skeleton h={100} /> : !list.data?.results.length ? <Empty title="No tables yet">Add tables to generate a QR code for each one.</Empty> : (
          <table className="tbl"><thead><tr><th>QR</th><th>Table</th><th>Branch</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((t) => (
              <tr key={t.id}><td><QrImage id={t.id} version={t.qr_regenerated_at} /></td><td><b>{t.label}</b>{t.seats ? <div className="muted">{t.seats} seats</div> : null}</td><td>{t.branch_name}</td>
                <td><span className={`badge ${t.is_active ? 'active' : 'suspended'}`}>{t.is_active ? 'active' : 'disabled'}</span></td>
                <td style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <button className="btn sm secondary" onClick={() => downloadFile(`/qr-menu/tables/${t.id}/qr/`, `${t.label.replace(/\W+/g, '-')}-qr.png`).catch(() => toast('Download failed.'))}><Download size={14} aria-hidden /> PNG</button>
                  <button className="btn sm secondary" onClick={() => setEdit(t)}>Edit</button>
                  <button className="btn sm secondary" onClick={async () => (await confirm({ title: `Create a new QR code for ${t.label}?`, message: 'Printed copies of the old code stop working immediately.', confirmLabel: 'Create new code', danger: true })) && act(t, 'regenerate', 'New QR code created. Reprint it.')}>Regenerate</button>
                  <button className={`btn sm ${t.is_active ? 'danger' : ''}`} onClick={() => act(t, t.is_active ? 'disable' : 'enable', t.is_active ? 'Table disabled.' : 'Table enabled.')}>{t.is_active ? 'Disable' : 'Enable'}</button>
                </td></tr>
            ))}
          </tbody></table>)}
      </div>
      {edit && <TableForm initial={edit === 'new' ? null : edit} branches={(branches.data?.results ?? []).filter((b) => b.status === 'active')} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
    </>
  )
}

function TableForm({ initial, branches, onClose, onSaved }: { initial: Table | null; branches: BranchRow[]; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ label: initial?.label ?? '', seats: initial?.seats ? String(initial.seats) : '', branch: String(initial?.branch ?? (branches.length === 1 ? branches[0].id : '')) })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!v.label.trim()) local.label = 'Enter the table name, e.g. Table 4.'
    if (!v.branch) local.branch = 'Choose a branch.'
    setErrors(local)
    if (Object.keys(local).length) return
    setBusy(true)
    try { await api(initial ? `/qr-menu/tables/${initial.id}/` : '/qr-menu/tables/', { method: initial ? 'PATCH' : 'POST', body: { label: v.label.trim(), seats: v.seats ? Number(v.seats) : null, ...(initial ? {} : { branch: Number(v.branch) }) } }); onSaved() }
    catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Error' }) } finally { setBusy(false) }
  }
  return (
    <Modal title={initial ? 'Edit table' : 'Add table'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && !Object.keys(errors).some((k) => k !== 'form') && <div className="alert error">{errors.form}</div>}
        {!initial && <Field label="Branch" error={errors.branch}>{(p) => <select {...p} className="input" value={v.branch} onChange={(e) => setV({ ...v, branch: e.target.value })}><option value="">Choose a branch</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>}
        <Field label="Table name" error={errors.label}>{(p) => <input {...p} className="input" placeholder="e.g. Table 4" value={v.label} onChange={(e) => setV({ ...v, label: e.target.value })} />}</Field>
        <Field label="Seats (optional)">{(p) => <input {...p} className="input" inputMode="numeric" placeholder="e.g. 4" value={v.seats} onChange={(e) => setV({ ...v, seats: e.target.value })} />}</Field>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save table'}</button>
      </form>
    </Modal>
  )
}

/** Print sheet: one card per active table with a large QR code. Uses the browser's print dialog. */
export function TablesPrint() {
  useDocumentTitle('Print QR codes')
  const { site } = useSite()
  const list = useAsync(() => api<Page<Table>>('/qr-menu/tables/', { params: { page_size: 100 } }), [])
  const tables = (list.data?.results ?? []).filter((t) => t.is_active)
  return (
    <>
      <div className="toolbar no-print"><Link to="/manage/tables">← Back</Link><div style={{ flex: 1 }} /><button className="btn" onClick={() => window.print()}><Printer size={16} aria-hidden /> Print</button></div>
      {list.loading ? <Skeleton h={200} /> : !tables.length ? <Empty title="No active tables" /> : (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))' }}>
          {tables.map((t) => (
            <div key={t.id} className="card" style={{ textAlign: 'center', breakInside: 'avoid' }}>
              <p style={{ margin: 0, fontWeight: 700 }}>{site.restaurant.name}</p>
              <QrImage id={t.id} version={t.qr_regenerated_at} size={190} />
              <h2 style={{ margin: '4px 0' }}>{t.label}</h2>
              <p className="muted" style={{ margin: 0 }}>{t.branch_name} · Scan to order from your table</p>
            </div>))}
        </div>)}
    </>
  )
}

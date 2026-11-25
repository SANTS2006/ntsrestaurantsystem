import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useConfirm } from '../../ui/dialogs'

type Branch = { id: number; name: string; code: string; address: string; location: string; phone: string; email: string; operating_hours: Record<string, string>; status: string; manager: number | null; manager_name: string | null; staff_count: number }
type Member = { user_id: number; full_name: string; email: string }
const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')

export default function Branches() {
  const confirm = useConfirm()
  useDocumentTitle('Branches')
  const toast = useToast()
  const list = useAsync(() => api<Page<Branch>>('/restaurants/branches/', { params: { page_size: 100 } }), [])
  const managers = useAsync(() => api<Page<Member>>('/staff/members/', { params: { role: 'manager', active: 1, page_size: 100 } }), [])
  const [edit, setEdit] = useState<Branch | 'new' | null>(null)
  const [assign, setAssign] = useState<Branch | null>(null)

  async function toggle(b: Branch) {
    const suspend = b.status === 'active'
    if (suspend && !(await confirm({ title: `Suspend ${b.name}?`, message: 'It will stop taking new orders and shifts.', confirmLabel: 'Suspend', danger: true }))) return
    try { await api(`/restaurants/branches/${b.id}/${suspend ? 'suspend' : 'activate'}/`, { body: {} }); toast(`${b.name} ${suspend ? 'suspended' : 'activated'}.`); list.reload() } catch (e) { toast(msg(e)) }
  }
  return (
    <>
      <div className="toolbar"><h1 style={{ fontSize: '1.7rem', margin: 0, flex: 1 }}>Branches</h1><button className="btn" onClick={() => setEdit('new')}><Plus size={18} aria-hidden /> Add branch</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading ? <Skeleton h={100} /> : !list.data?.results.length ? <Empty title="No branches yet" /> : (
          <table className="tbl"><thead><tr><th>Branch</th><th>Code</th><th>Manager</th><th>Staff</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((b) => (
              <tr key={b.id}><td><b>{b.name}</b><div className="muted">{b.address}</div></td><td>{b.code}</td><td>{b.manager_name ?? <span className="muted">none</span>}</td><td>{b.staff_count}</td>
                <td><span className={`badge ${b.status === 'active' ? 'active' : 'suspended'}`}>{b.status}</span></td>
                <td style={{ display: 'flex', gap: 6 }}><button className="btn sm secondary" onClick={() => setEdit(b)}>Edit</button><button className="btn sm secondary" onClick={() => setAssign(b)}>Manager</button>
                  <button className={`btn sm ${b.status === 'active' ? 'danger' : ''}`} onClick={() => toggle(b)}>{b.status === 'active' ? 'Suspend' : 'Activate'}</button></td></tr>
            ))}
          </tbody></table>)}
      </div>
      {edit && <BranchForm initial={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
      {assign && <AssignManager branch={assign} managers={managers.data?.results ?? []} onClose={() => setAssign(null)} onSaved={() => { setAssign(null); list.reload() }} />}
    </>
  )
}

function BranchForm({ initial, onClose, onSaved }: { initial: Branch | null; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ name: initial?.name ?? '', code: initial?.code ?? '', address: initial?.address ?? '', location: initial?.location ?? '', phone: initial?.phone ?? '', email: initial?.email ?? '' })
  const [hours, setHours] = useState<Record<string, string>>(initial?.operating_hours ?? {})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })
  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!v.name.trim()) local.name = 'Enter the branch name.'
    if (!/^[A-Za-z0-9-]{1,20}$/.test(v.code)) local.code = 'Use up to 20 letters, digits or hyphens.'
    setErrors(local)
    if (Object.keys(local).length) return
    setBusy(true)
    try { await api(initial ? `/restaurants/branches/${initial.id}/` : '/restaurants/branches/', { method: initial ? 'PATCH' : 'POST', body: { ...v, operating_hours: Object.fromEntries(Object.entries(hours).filter(([, t]) => t.trim())) } }); onSaved() }
    catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Error' }) } finally { setBusy(false) }
  }
  const f = (k: keyof typeof v, label: string, ph: string) => <Field label={label} error={errors[k]}>{(p) => <input {...p} className="input" placeholder={ph} value={v[k]} onChange={set(k)} />}</Field>
  return (
    <Modal title={initial ? `Edit ${initial.name}` : 'Add branch'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && !Object.keys(errors).some((k) => k !== 'form') && <div className="alert error">{errors.form}</div>}
        {f('name', 'Branch name', 'e.g. Harbour Road')}{f('code', 'Branch code', 'e.g. HR1')}{f('address', 'Address', 'Street address')}{f('location', 'Area / location', 'e.g. Aberdeen')}{f('phone', 'Phone', 'Branch phone number')}{f('email', 'Email', 'Branch email')}
        <fieldset style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14 }}><legend>Operating hours</legend>
          {DAYS.map((d) => <label key={d} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}><span style={{ width: 90, textTransform: 'capitalize' }}>{d}</span><input className="input" placeholder="e.g. 08:00-22:00 or Closed" aria-label={`${d} hours`} value={hours[d] ?? ''} onChange={(e) => setHours({ ...hours, [d]: e.target.value })} /></label>)}
          {errors.operating_hours && <p className="err">{errors.operating_hours}</p>}
        </fieldset>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save branch'}</button>
      </form>
    </Modal>
  )
}

function AssignManager({ branch, managers, onClose, onSaved }: { branch: Branch; managers: Member[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [uid, setUid] = useState(branch.manager ? String(branch.manager) : '')
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try { await api(`/restaurants/branches/${branch.id}/assign-manager/`, { body: { user_id: uid ? Number(uid) : null } }); toast('Manager updated.'); onSaved() } catch (e) { toast(msg(e)) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Manager for ${branch.name}`} onClose={onClose}>
      <p className="muted">Choose from the restaurant&apos;s managers (add managers in Staff). The branch is added to their access and removed from the previous manager.</p>
      <Field label="Manager">{(p) => <select {...p} className="input" value={uid} onChange={(e) => setUid(e.target.value)}><option value="">No manager</option>{managers.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name || m.email}</option>)}</select>}</Field>
      <button className="btn" disabled={busy} onClick={save}>{busy ? <Spinner /> : 'Save'}</button>
    </Modal>
  )
}

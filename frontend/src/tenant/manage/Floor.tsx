import { CalendarPlus, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Empty, ErrorState, Field, Modal, PageHeader, Pager, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'
import { usePrompt } from '../../ui/dialogs'

type Table = { id: number; label: string; seats: number | null; shape: string; x: number; y: number; state: 'free' | 'reserved' | 'occupied'; occupied_by: { reference?: string; party?: number; name?: string; order?: string } | null; next_reservation: { id: number; reference: string; name: string; party: number; at: string; status: string } | null }
type Board = { branch: string; branch_id: number; counts: Record<string, number>; zones: { zone_id: number | null; zone: string; tables: Table[] }[] }
type Res = { id: number; reference: string; status: string; branch: string; branch_id: number; local_date: string; local_time: string; party_size: number; table: string | null; table_id: number | null; notes: string; source: string; customer_name: string; customer_phone: string; customer_email: string; cancel_reason: string }
type Zone = { id: number; name: string; branch_id: number; branch: string; sort_order: number; is_active: boolean }

const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const STATE: Record<string, string> = { free: 'ok', reserved: 'warn', occupied: 'bad' }
const BADGE: Record<string, string> = { requested: 'warn', confirmed: 'info', seated: 'ok', completed: '', cancelled: 'bad', no_show: 'bad' }
const iso = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)

export default function Floor() {
  useDocumentTitle('Floor and reservations')
  const { me } = useAuth()
  const { site } = useSite()
  const manage = ['restaurant_admin', 'manager', 'platform_admin'].includes(me?.role ?? '')
  const myBranches = site.branches.filter((b) => me?.role === 'restaurant_admin' || me?.role === 'platform_admin' || me?.branch_ids.includes(b.id))
  const [tab, setTab] = useState<'board' | 'list' | 'setup'>('board')
  const [branch, setBranch] = useState(String(myBranches[0]?.id ?? ''))
  return (
    <>
      <PageHeader title="Floor and reservations" subtitle="Live table status, bookings and the floor plan">
        {myBranches.length > 1 && <select className="input" style={{ width: 190 }} aria-label="Branch" value={branch} onChange={(e) => setBranch(e.target.value)}>{myBranches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
        <div className="seg" role="tablist" aria-label="Sections">
          {([['board', 'Floor'], ['list', 'Reservations'], ...(manage ? [['setup', 'Zones and layout']] : [])] as const).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k as typeof tab)}>{l}</button>)}
        </div>
      </PageHeader>
      {!branch ? <Empty title="No branch available" /> : tab === 'board' ? <BoardTab branch={branch} /> : tab === 'list' ? <ListTab branch={branch} /> : <SetupTab branch={branch} />}
    </>
  )
}

function BoardTab({ branch }: { branch: string }) {
  const d = useAsync(() => api<Board>('/floor/status/', { params: { branch } }), [branch])
  const { reload } = d
  useEffect(() => { const t = setInterval(() => { if (!document.hidden) reload() }, 15000); return () => clearInterval(t) }, [reload])
  const toast = useToast()
  async function seat(id: number) { try { await api(`/floor/reservations/${id}/seat/`, { body: {} }); toast('Guests seated.'); reload() } catch (e) { toast(msg(e)) } }
  if (d.error) return <ErrorState message={d.error} onRetry={reload} />
  if (!d.data) return <Skeleton h={220} />
  return (
    <>
      <div className="chips" style={{ marginBottom: 14 }}><span className="badge ok">{d.data.counts.free} free</span><span className="badge warn">{d.data.counts.reserved} reserved soon</span><span className="badge bad">{d.data.counts.occupied} occupied</span>
        <button className="btn sm secondary" onClick={reload}><RefreshCw size={14} aria-hidden /> Refresh</button></div>
      {!d.data.zones.length ? <Empty title="No tables yet">Add tables under Tables and QR, then arrange them into zones here.</Empty> : d.data.zones.map((z) => (
        <section key={z.zone} className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>{z.zone}</h3>
          <div className="tiles" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 180px), 1fr))' }}>
            {z.tables.map((t) => (
              <div key={t.id} className="card flat" style={{ padding: 14, borderLeft: `4px solid var(--${t.state === 'free' ? 'ok' : t.state === 'reserved' ? 'warn' : 'danger'})` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}><b style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem' }}>{t.label}</b><span className={`badge ${STATE[t.state]}`}>{t.state}</span></div>
                <div className="muted" style={{ fontSize: '.85rem' }}>{t.seats ?? '?'} seats · {t.shape}</div>
                {t.occupied_by && <p style={{ margin: '8px 0 0' }}>{t.occupied_by.order ? `Order ${t.occupied_by.order}` : `${t.occupied_by.name} · ${t.occupied_by.party} guests`}</p>}
                {t.next_reservation && <p style={{ margin: '8px 0 0', fontSize: '.9rem' }}>Next: <b>{new Date(t.next_reservation.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b> {t.next_reservation.name} ({t.next_reservation.party})
                  {t.next_reservation.status === 'confirmed' && t.state !== 'occupied' && <button className="btn sm" style={{ marginLeft: 6 }} onClick={() => seat(t.next_reservation!.id)}>Seat</button>}</p>}
              </div>))}
          </div>
        </section>))}
    </>
  )
}

function ListTab({ branch }: { branch: string }) {
  const prompt = usePrompt()
  const toast = useToast()
  const [day, setDay] = useState(iso(new Date()))
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [adding, setAdding] = useState(false)
  const list = useAsync(() => api<Page<Res>>('/floor/reservations/', { params: { date: day, status, branch, page } }), [day, status, branch, page])
  async function act(r: Res, a: string, reason = '') {
    try { await api(`/floor/reservations/${r.id}/${a}/`, { body: { reason } }); toast(`${r.reference}: ${a.replace('-', ' ')}`); list.reload() } catch (e) { toast(msg(e)) }
  }
  async function cancel(r: Res) { const reason = (await prompt({ title: `Cancel ${r.reference}?`, message: 'The guest is emailed the reason.', label: 'Reason', required: true, danger: true, confirmLabel: 'Cancel reservation' })) ?? ''; if (reason) void act(r, 'cancel', reason) }
  return (
    <>
      <div className="toolbar">
        <input className="input" style={{ width: 170 }} type="date" aria-label="Date" value={day} onChange={(e) => { setDay(e.target.value); setPage(1) }} />
        <div className="chips" role="group" aria-label="Status">{['', 'requested', 'confirmed', 'seated', 'completed', 'cancelled', 'no_show'].map((s) => <button key={s} className="chip" aria-pressed={status === s} onClick={() => { setStatus(s); setPage(1) }}>{s ? s.replace('_', ' ') : 'All'}</button>)}</div>
        <span style={{ flex: 1 }} /><button className="btn" onClick={() => setAdding(true)}><CalendarPlus size={16} aria-hidden /> New booking</button>
      </div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title="No reservations for this day" /> : (
          <table className="tbl"><thead><tr><th>Time</th><th>Guest</th><th>Party</th><th>Table</th><th>Status</th><th>Ref</th><th /></tr></thead><tbody>
            {list.data.results.map((r) => (
              <tr key={r.id}><td><b>{r.local_time}</b></td><td>{r.customer_name}<div className="muted" style={{ fontSize: '.8rem' }}>{r.customer_phone}{r.notes ? ` · ${r.notes}` : ''}</div></td><td>{r.party_size}</td><td>{r.table ?? '–'}</td>
                <td><span className={`badge ${BADGE[r.status]}`}>{r.status.replace('_', ' ')}</span></td><td className="muted">{r.reference}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {r.status === 'requested' && <button className="btn sm" onClick={() => act(r, 'confirm')}>Confirm</button>}{' '}
                  {r.status === 'confirmed' && <><button className="btn sm" onClick={() => act(r, 'seat')}>Seat</button> <button className="btn sm secondary" onClick={() => act(r, 'no-show')}>No-show</button></>}{' '}
                  {r.status === 'seated' && <button className="btn sm" onClick={() => act(r, 'complete')}>Complete</button>}{' '}
                  {['requested', 'confirmed'].includes(r.status) && <button className="btn sm danger" onClick={() => cancel(r)}>Cancel</button>}</td></tr>))}
          </tbody></table>)}
      </div>
      {list.data && <Pager page={page} hasPrev={!!list.data.previous} hasNext={!!list.data.next} onPage={setPage} total={list.data.count} />}
      {adding && <Booking branch={branch} day={day} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); list.reload() }} />}
    </>
  )
}

function Booking({ branch, day, onClose, onSaved }: { branch: string; day: string; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({ date: day, time: '19:00', party_size: '2', customer_name: '', customer_phone: '', customer_email: '', notes: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!f.customer_name.trim() || !/^[0-9+()\-\s]{6,30}$/.test(f.customer_phone)) return setErr('Enter the guest name and a valid phone number.')
    setBusy(true); setErr('')
    try { await api('/floor/reservations/', { body: { ...f, branch_id: Number(branch), party_size: Number(f.party_size) } }); toast('Booking created.'); onSaved() } catch (x) { setErr(msg(x)) } finally { setBusy(false) }
  }
  return (
    <Modal title="New booking" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="grid g2">
          <Field label="Date">{(p) => <input {...p} className="input" type="date" value={f.date} onChange={set('date')} />}</Field>
          <Field label="Time">{(p) => <input {...p} className="input" type="time" step={1800} value={f.time} onChange={set('time')} />}</Field>
          <Field label="Guests">{(p) => <input {...p} className="input" type="number" min={1} max={100} value={f.party_size} onChange={set('party_size')} />}</Field>
          <Field label="Guest name">{(p) => <input {...p} className="input" value={f.customer_name} onChange={set('customer_name')} />}</Field>
          <Field label="Phone">{(p) => <input {...p} className="input" type="tel" value={f.customer_phone} onChange={set('customer_phone')} />}</Field>
          <Field label="Email (optional, for confirmation)">{(p) => <input {...p} className="input" type="email" value={f.customer_email} onChange={set('customer_email')} />}</Field>
        </div>
        <Field label="Notes">{(p) => <input {...p} className="input" maxLength={300} value={f.notes} onChange={set('notes')} />}</Field>
        <button className="btn" disabled={busy}>{busy ? 'Booking…' : 'Create booking'}</button>
      </form>
    </Modal>
  )
}

function SetupTab({ branch }: { branch: string }) {
  const toast = useToast()
  const zones = useAsync(() => api<Zone[]>('/floor/zones/'), [])
  const board = useAsync(() => api<Board>('/floor/status/', { params: { branch } }), [branch])
  const [name, setName] = useState('')
  const mine = (zones.data ?? []).filter((z) => String(z.branch_id) === branch)
  const tables = (board.data?.zones ?? []).flatMap((z) => z.tables.map((t) => ({ ...t, zone_id: z.zone_id })))
  const reload = useCallback(() => { zones.reload(); board.reload() }, [zones, board])
  async function addZone(e: FormEvent) {
    e.preventDefault()
    try { await api('/floor/zones/', { body: { name, branch_id: Number(branch), sort_order: mine.length } }); setName(''); toast('Zone added.'); reload() } catch (x) { toast(msg(x)) }
  }
  async function layout(id: number, body: Record<string, unknown>) {
    try { await api(`/floor/tables/${id}/layout/`, { method: 'PATCH', body }); reload() } catch (x) { toast(msg(x)) }
  }
  return (
    <div className="grid g2" style={{ alignItems: 'start' }}>
      <section className="card">
        <h3 style={{ marginTop: 0 }}>Zones</h3>
        {mine.map((z) => <div className="list-row" key={z.id}><span>{z.name}{!z.is_active && <span className="badge" style={{ marginLeft: 6 }}>hidden</span>}</span>
          <button className="btn sm secondary" onClick={async () => { try { await api(`/floor/zones/${z.id}/`, { method: 'PATCH', body: { is_active: !z.is_active } }); reload() } catch (x) { toast(msg(x)) } }}>{z.is_active ? 'Hide' : 'Show'}</button></div>)}
        {!mine.length && <p className="muted">No zones yet, for example “Main hall” or “Terrace”.</p>}
        <form onSubmit={addZone} style={{ display: 'flex', gap: 8, marginTop: 12 }}><input className="input" aria-label="New zone name" placeholder="Zone name" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /><button className="btn" disabled={!name.trim()}>Add</button></form>
      </section>
      <section className="card table-wrap">
        <h3 style={{ marginTop: 0 }}>Tables</h3>
        {!tables.length ? <Empty title="No tables">Create tables under Tables and QR first.</Empty> : (
          <table className="tbl"><thead><tr><th>Table</th><th>Zone</th><th>Seats</th><th>Shape</th></tr></thead><tbody>
            {tables.map((t) => <tr key={t.id}><td><b>{t.label}</b></td>
              <td><select className="input" aria-label={`Zone of ${t.label}`} value={t.zone_id ?? ''} onChange={(e) => layout(t.id, { zone_id: e.target.value ? Number(e.target.value) : null })}><option value="">Unassigned</option>{mine.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}</select></td>
              <td><input className="input" style={{ width: 80 }} type="number" min={1} max={50} aria-label={`Seats at ${t.label}`} defaultValue={t.seats ?? ''} onBlur={(e) => e.target.value && Number(e.target.value) !== t.seats && layout(t.id, { seats: Number(e.target.value) })} /></td>
              <td><select className="input" aria-label={`Shape of ${t.label}`} value={t.shape} onChange={(e) => layout(t.id, { shape: e.target.value })}><option value="square">Square</option><option value="round">Round</option><option value="rect">Rectangular</option></select></td></tr>)}
          </tbody></table>)}
      </section>
    </div>
  )
}

import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { Empty, ErrorState, Field, Skeleton, Spinner, useAsync, useDocumentTitle } from '../ui/kit'
import { useSite } from './SiteContext'

type Options = { enabled: boolean; max_party: number; duration_minutes: number; auto_confirm: boolean; branches: { id: number; name: string }[] }
type Booked = { reference: string; status: string; branch: string; local_date: string; local_time: string; party_size: number; table: string | null; manage_token?: string; cancel_reason?: string }

const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong. Please try again.')
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)

export function ReservePage() {
  const { site } = useSite()
  useDocumentTitle(`Reserve a table | ${site.restaurant.name}`, `Book a table at ${site.restaurant.name}.`)
  const opts = useAsync(() => api<Options>('/floor/public/options/', { auth: false }), [])
  const [f, setF] = useState({ branch_id: '', date: today(), party_size: '2', time: '', customer_name: '', customer_phone: '', customer_email: '', notes: '', accept_privacy: false, website: '' })
  const branch = f.branch_id || String(opts.data?.branches[0]?.id ?? '')
  const slots = useAsync(() => (branch && f.date ? api<{ slots: string[] }>('/floor/public/availability/', { params: { branch, date: f.date, party: Number(f.party_size) || 2 }, auth: false }) : Promise.resolve(null)), [branch, f.date, f.party_size])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<Booked | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!f.time) local.time = 'Choose a time.'
    if (!f.customer_name.trim()) local.customer_name = 'Enter your name.'
    if (!/^[0-9+()\-\s]{6,30}$/.test(f.customer_phone)) local.customer_phone = 'Enter a valid phone number.'
    if (f.customer_email && !/^\S+@\S+\.\S+$/.test(f.customer_email)) local.customer_email = 'Enter a valid email address.'
    if (!f.accept_privacy) local.accept_privacy = 'Please accept the privacy policy.'
    setErrors(local)
    if (Object.keys(local).length) return
    setBusy(true)
    try {
      setDone(await api<Booked>('/floor/public/reservations/', { auth: false, body: { ...f, branch_id: Number(branch), party_size: Number(f.party_size) } }))
    } catch (x) { setErrors({ form: msg(x) }); slots.reload() } finally { setBusy(false) }
  }

  if (opts.loading) return <div className="container section"><Skeleton h={240} /></div>
  if (opts.error || !opts.data) return <div className="container section"><ErrorState message={opts.error ?? 'Could not load.'} onRetry={opts.reload} /></div>
  if (!opts.data.enabled) return <div className="container section"><Empty title="Online reservations are not available">Please call the restaurant to book a table.</Empty></div>
  if (done) return (
    <div className="container section" style={{ maxWidth: 560 }}>
      <div className="card">
        <p className="eyebrow">{done.status === 'confirmed' ? 'Confirmed' : 'Request received'}</p>
        <h1 style={{ fontSize: '2rem' }}>{done.status === 'confirmed' ? 'Your table is booked' : 'We have your request'}</h1>
        <p><b>{done.party_size} guest{done.party_size === 1 ? '' : 's'}</b> · {done.local_date} at {done.local_time} · {done.branch}</p>
        <p>Reference <b>{done.reference}</b>{f.customer_email ? '. We emailed you the details.' : '.'}</p>
        {done.manage_token && <p><Link className="btn secondary" to={`/reservation/${done.manage_token}`}>View or cancel my booking</Link></p>}
        <p className="hint">Keep the link above: it is the only way to change or cancel online. Anyone with it can cancel your booking.</p>
      </div>
    </div>
  )
  return (
    <div className="container section" style={{ maxWidth: 720 }}>
      <p className="eyebrow">Reservations</p>
      <h1 style={{ fontSize: 'clamp(2rem, 4vw, 2.8rem)' }}>Reserve a table</h1>
      <p className="muted">Pick a day, party size and time. Bookings hold the table for {opts.data.duration_minutes} minutes. For groups above {opts.data.max_party}, please call us.</p>
      <form className="card" onSubmit={submit} noValidate>
        {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
        <div className="grid g2">
          {opts.data.branches.length > 1 && <Field label="Location">{(p) => <select {...p} className="input" value={branch} onChange={(e) => setF({ ...f, branch_id: e.target.value, time: '' })}>{opts.data!.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>}
          <Field label="Date">{(p) => <input {...p} className="input" type="date" min={today()} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value, time: '' })} />}</Field>
          <Field label="Guests">{(p) => <input {...p} className="input" type="number" min={1} max={opts.data!.max_party} value={f.party_size} onChange={(e) => setF({ ...f, party_size: e.target.value, time: '' })} />}</Field>
        </div>
        <p style={{ fontWeight: 600, marginBottom: 6 }}>Available times</p>
        {slots.loading ? <Spinner /> : !slots.data?.slots.length ? <p className="muted">No tables available on this day for this party size. Try another date.</p> : (
          <div className="chips" role="group" aria-label="Available times" style={{ marginBottom: 12 }}>{slots.data.slots.map((s) => <button type="button" key={s} className="chip" aria-pressed={f.time === s} onClick={() => setF({ ...f, time: s })}>{s}</button>)}</div>)}
        {errors.time && <p className="err">{errors.time}</p>}
        <div className="grid g2">
          <Field label="Your name" error={errors.customer_name}>{(p) => <input {...p} className="input" autoComplete="name" value={f.customer_name} onChange={set('customer_name')} />}</Field>
          <Field label="Phone" error={errors.customer_phone}>{(p) => <input {...p} className="input" type="tel" autoComplete="tel" value={f.customer_phone} onChange={set('customer_phone')} />}</Field>
          <Field label="Email (for your confirmation)" error={errors.customer_email}>{(p) => <input {...p} className="input" type="email" autoComplete="email" value={f.customer_email} onChange={set('customer_email')} />}</Field>
        </div>
        <Field label="Anything we should know? (optional)">{(p) => <input {...p} className="input" maxLength={300} placeholder="Allergies, celebration, high chair…" value={f.notes} onChange={set('notes')} />}</Field>
        <div aria-hidden style={{ position: 'absolute', left: '-9999px' }}><label>Website<input tabIndex={-1} autoComplete="off" value={f.website} onChange={set('website')} /></label></div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 14 }}><input type="checkbox" checked={f.accept_privacy} onChange={(e) => setF({ ...f, accept_privacy: e.target.checked })} /><span>I agree to the <Link to="/policies/privacy-policy">Privacy Policy</Link> so the restaurant can hold my booking. {errors.accept_privacy && <span className="err">{errors.accept_privacy}</span>}</span></label>
        <button className="btn lg" disabled={busy}>{busy ? <Spinner /> : 'Book this table'}</button>
      </form>
    </div>
  )
}

export function ReservationManage() {
  const { token } = useParams()
  useDocumentTitle('Your reservation')
  const d = useAsync(() => api<Booked>(`/floor/public/reservations/${token}/`, { auth: false }), [token])
  const [err, setErr] = useState('')
  async function cancel() {
    if (!confirm('Cancel this reservation?')) return
    try { await api(`/floor/public/reservations/${token}/`, { auth: false, body: {} }); d.reload() } catch (x) { setErr(msg(x)) }
  }
  if (d.loading) return <div className="container section"><Skeleton h={160} /></div>
  if (d.error || !d.data) return <div className="container section"><Empty title="Reservation not found">This link is not valid.</Empty></div>
  const r = d.data
  return (
    <div className="container section" style={{ maxWidth: 560 }}>
      <div className="card">
        <h1 style={{ fontSize: '1.8rem' }}>Your reservation</h1>
        {err && <div className="alert error" role="alert">{err}</div>}
        <p><span className={`badge ${r.status === 'cancelled' || r.status === 'no_show' ? 'bad' : 'ok'}`}>{r.status.replace('_', ' ')}</span> <b>{r.reference}</b></p>
        <p>{r.party_size} guest{r.party_size === 1 ? '' : 's'} · {r.local_date} at {r.local_time} · {r.branch}</p>
        {['requested', 'confirmed'].includes(r.status) && <button className="btn danger" onClick={cancel}>Cancel reservation</button>}
        {r.status === 'cancelled' && <p className="muted">This reservation was cancelled.</p>}
      </div>
    </div>
  )
}

import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../../lib/api'
import { Empty, ErrorState, Field, Skeleton, Spinner, useAsync } from '../../ui/kit'
import { useSeo } from '../seo'
import { useSite } from '../SiteContext'

type Options = { event_types: { value: string; label: string }[]; services: { id: number; name: string }[]; branches: { id: number; name: string }[]; currency: string }
const A = { auth: false } as const
const tomorrow = () => new Date(Date.now() + 86400000).toISOString().slice(0, 10)

/** Public catering request form. Submitting sends a request for a quotation; it is not a booking. */
export function CateringRequestPage() {
  const { site, money } = useSite()
  useSeo({ title: `Catering and events | ${site.restaurant.name}`, description: `Request catering for your wedding, corporate event or party from ${site.restaurant.name}.`, path: '/catering' })
  const opts = useAsync(() => api<Options>('/catering/public/options/', A), [])
  const [v, setV] = useState({ customer_name: '', customer_email: '', customer_phone: '', event_type: 'wedding', event_date: '', event_location: '', guests: '', branch_id: '', food_preferences: '', budget: '', requirements: '', website: '' })
  const [svc, setSvc] = useState<number[]>([])
  const [agree, setAgree] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault()
    const l: Record<string, string> = {}
    if (!v.customer_name.trim()) l.customer_name = 'Enter your full name.'
    if (!/^\S+@\S+\.\S+$/.test(v.customer_email)) l.customer_email = 'Enter a valid email address.'
    if (!/^[0-9+()\-\s]{6,30}$/.test(v.customer_phone)) l.customer_phone = 'Enter a valid phone number.'
    if (!v.event_date || v.event_date < tomorrow()) l.event_date = 'Choose a date from tomorrow onwards.'
    if (!v.event_location.trim()) l.event_location = 'Enter where the event will take place.'
    const g = Number(v.guests)
    if (!Number.isInteger(g) || g < 1 || g > 5000) l.guests = 'Enter the expected number of guests (1 to 5000).'
    if (v.budget && !/^\d+(\.\d{1,2})?$/.test(v.budget)) l.budget = 'Enter a number such as 2500.'
    if (!agree) l.accept_privacy = 'Please agree to the Privacy Policy.'
    setErrors(l)
    if (Object.keys(l).length) return
    setBusy(true)
    try {
      const r = await api<{ reference: string }>('/catering/public/requests/', { auth: false, body: { ...v, guests: g, budget: v.budget || null, branch_id: v.branch_id ? Number(v.branch_id) : null, service_ids: svc, accept_privacy: agree } })
      setDone(r.reference)
    } catch (err) {
      const fe = err instanceof ApiError ? err.fieldErrors() : {}
      setErrors({ ...fe, form: Object.keys(fe).length ? '' : err instanceof ApiError ? err.message : 'Something went wrong. Please try again.' })
    } finally { setBusy(false) }
  }
  if (done) return (
    <section className="section"><div className="container prose">
      <div className="card"><h1 style={{ fontSize: '1.6rem' }}>Request received</h1>
        <p>Your reference is <b>{done}</b>. We have emailed you a confirmation. Our team will review your request and contact you with a quotation or any questions.</p>
        <p className="muted">This is a request, not a booking. A booking is confirmed only after you accept a quotation.</p>
        <Link className="btn" to="/">Back to home</Link></div>
    </div></section>
  )
  return (
    <section className="section"><div className="container" style={{ maxWidth: 760 }}>
      <h1>Catering and events</h1>
      <p className="muted">Tell us about your event and we will send you a quotation. Budget amounts are in {opts.data?.currency ?? site.currency}{v.budget && /^\d+(\.\d{1,2})?$/.test(v.budget) ? ` (${money(v.budget)})` : ''}.</p>
      {opts.error && <ErrorState message={opts.error} onRetry={opts.reload} />}
      {opts.loading ? <Skeleton h={300} /> : (
        <form className="card" onSubmit={submit} noValidate>
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          <div className="grid g2">
            <Field label="Full name" error={errors.customer_name}>{(p) => <input {...p} className="input" autoComplete="name" placeholder="Enter your full name" value={v.customer_name} onChange={set('customer_name')} />}</Field>
            <Field label="Email address" error={errors.customer_email}>{(p) => <input {...p} className="input" type="email" autoComplete="email" placeholder="Enter your email address" value={v.customer_email} onChange={set('customer_email')} />}</Field>
            <Field label="Phone number" error={errors.customer_phone}>{(p) => <input {...p} className="input" type="tel" autoComplete="tel" placeholder="Enter your phone number" value={v.customer_phone} onChange={set('customer_phone')} />}</Field>
            <Field label="Type of event" error={errors.event_type}>{(p) => <select {...p} className="input" value={v.event_type} onChange={set('event_type')}>{opts.data?.event_types.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select>}</Field>
            <Field label="Event date" error={errors.event_date}>{(p) => <input {...p} className="input" type="date" min={tomorrow()} value={v.event_date} onChange={set('event_date')} />}</Field>
            <Field label="Expected guests" error={errors.guests}>{(p) => <input {...p} className="input" inputMode="numeric" placeholder="e.g. 120" value={v.guests} onChange={set('guests')} />}</Field>
          </div>
          <Field label="Event location" error={errors.event_location}>{(p) => <input {...p} className="input" placeholder="Venue or address" value={v.event_location} onChange={set('event_location')} />}</Field>
          {(opts.data?.services.length ?? 0) > 0 && (
            <fieldset style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14 }}><legend>Services you are interested in</legend>
              {opts.data!.services.map((s) => <label key={s.id} style={{ display: 'block' }}><input type="checkbox" checked={svc.includes(s.id)} onChange={() => setSvc(svc.includes(s.id) ? svc.filter((x) => x !== s.id) : [...svc, s.id])} /> {s.name}</label>)}
              {errors.service_ids && <p className="err">{errors.service_ids}</p>}
            </fieldset>)}
          {(opts.data?.branches.length ?? 0) > 1 && <Field label="Preferred branch (optional)">{(p) => <select {...p} className="input" value={v.branch_id} onChange={set('branch_id')}><option value="">No preference</option>{opts.data!.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>}
          <Field label="Food preferences or dietary needs (optional)">{(p) => <textarea {...p} className="input" rows={3} placeholder="e.g. vegetarian options, no pork, allergies" value={v.food_preferences} onChange={set('food_preferences')} />}</Field>
          <Field label="Budget (optional)" error={errors.budget}>{(p) => <input {...p} className="input" inputMode="decimal" placeholder="e.g. 5000" value={v.budget} onChange={set('budget')} />}</Field>
          <Field label="Anything else we should know? (optional)">{(p) => <textarea {...p} className="input" rows={3} placeholder="Setup, timing, equipment, special requests" value={v.requirements} onChange={set('requirements')} />}</Field>
          <div aria-hidden style={{ position: 'absolute', left: '-9999px' }}><label>Website<input tabIndex={-1} autoComplete="off" value={v.website} onChange={set('website')} /></label></div>
          <div className="field"><label style={{ fontWeight: 400 }}><input type="checkbox" checked={agree} aria-invalid={!!errors.accept_privacy} onChange={(e) => setAgree(e.target.checked)} /> I agree to the <Link to="/policies/privacy-policy" target="_blank">Privacy Policy</Link> and that {site.restaurant.name} may contact me about this request.</label>{errors.accept_privacy && <span className="err">{errors.accept_privacy}</span>}</div>
          <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Send request'}</button>
        </form>)}
    </div></section>
  )
}

type Quote = {
  reference: string; restaurant: string; currency: string; version: number; event: { type: string; date: string; guests: number; location: string }
  items: { description: string; quantity: string; unit_price: string; line_total: string }[]; subtotal: string; discount: string; tax_rate_percent: string; tax_total: string; total: string
  valid_until: string; terms: string; expired: boolean
}

/** Private page opened from the emailed link: view the quotation, then accept or decline. */
export function QuotationPage() {
  const { token = '' } = useParams()
  const { money } = useSite()
  const q = useAsync(() => api<Quote>(`/catering/public/quotations/${token}/`, A), [token])
  const [note, setNote] = useState('')
  const [result, setResult] = useState<'accepted' | 'declined' | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useSeo({ title: 'Your quotation', path: `/quotation/${token}` })

  async function respond(accept: boolean) {
    if (accept && !confirm('Accept this quotation? The restaurant will be notified and your booking will be confirmed with them.')) return
    setBusy(true); setError('')
    try { await api(`/catering/public/quotations/${token}/${accept ? 'accept' : 'decline'}/`, { auth: false, body: { note } }); setResult(accept ? 'accepted' : 'declined') }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Something went wrong.') } finally { setBusy(false) }
  }
  if (q.loading) return <div className="container section"><Skeleton h={240} /></div>
  if (q.error || !q.data) return <div className="container section"><Empty title="This link is no longer valid">The quotation may already have been answered or replaced. Please contact the restaurant.</Empty></div>
  const d = q.data
  const m = (x: string) => money(x)
  return (
    <section className="section"><div className="container" style={{ maxWidth: 720 }}>
      <h1>Quotation for {d.reference}</h1>
      <p className="muted">{d.restaurant} · {d.event.type} on {new Date(d.event.date).toLocaleDateString()} · {d.event.guests} guests · {d.event.location}</p>
      {result ? <div className={`alert ${result === 'accepted' ? 'ok' : ''}`} aria-live="polite">{result === 'accepted' ? 'Thank you! You have accepted this quotation. The restaurant has been notified and will confirm the details with you.' : 'You have declined this quotation. The restaurant has been notified.'}</div> : (
        <>
          <div className="card table-wrap"><table className="tbl"><thead><tr><th>Item</th><th>Qty</th><th>Unit price</th><th style={{ textAlign: 'right' }}>Amount</th></tr></thead><tbody>
            {d.items.map((i, k) => <tr key={k}><td style={{ whiteSpace: 'normal' }}>{i.description}</td><td>{i.quantity}</td><td>{m(i.unit_price)}</td><td style={{ textAlign: 'right' }}>{m(i.line_total)}</td></tr>)}
            <tr><td colSpan={3}>Subtotal</td><td style={{ textAlign: 'right' }}>{m(d.subtotal)}</td></tr>
            {Number(d.discount) > 0 && <tr><td colSpan={3}>Discount</td><td style={{ textAlign: 'right' }}>−{m(d.discount)}</td></tr>}
            {Number(d.tax_total) > 0 && <tr><td colSpan={3}>Tax ({Number(d.tax_rate_percent)}%)</td><td style={{ textAlign: 'right' }}>{m(d.tax_total)}</td></tr>}
            <tr><td colSpan={3}><b>Total</b></td><td style={{ textAlign: 'right' }}><b>{m(d.total)}</b></td></tr>
          </tbody></table></div>
          <p>Valid until <b>{new Date(d.valid_until).toLocaleDateString()}</b>.</p>
          {d.terms && <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.1rem' }}>Terms</h2><p style={{ whiteSpace: 'pre-line' }}>{d.terms}</p></div>}
          {d.expired ? <div className="alert error">This quotation has expired. Please contact the restaurant for a new one.</div> : (
            <>
              {error && <div className="alert error" role="alert">{error}</div>}
              <Field label="Message to the restaurant (optional)">{(p) => <input {...p} className="input" maxLength={300} placeholder="Anything you would like to add" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
              <div style={{ display: 'flex', gap: 8 }}><button className="btn" disabled={busy} onClick={() => respond(true)}>{busy ? <Spinner /> : 'Accept quotation'}</button><button className="btn secondary" disabled={busy} onClick={() => respond(false)}>Decline</button></div>
            </>)}
        </>)}
    </div></section>
  )
}

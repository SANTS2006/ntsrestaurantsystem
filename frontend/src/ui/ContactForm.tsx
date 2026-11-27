import { CheckCircle2, Send } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { Field, Spinner } from './kit'

const PLATFORM_TOPICS = [['sales', 'Bringing my restaurant online'], ['support', 'Help with the system'], ['general', 'General question'], ['feedback', 'Feedback or complaint'], ['other', 'Something else']]
const RESTAURANT_TOPICS = [['general', 'General question'], ['order', 'An order or payment'], ['reservation', 'A reservation or event'], ['feedback', 'Feedback or complaint'], ['other', 'Something else']]

const empty = { name: '', email: '', phone: '', business_name: '', city: '', preferred_contact: 'email', topic: '', subject: '', message: '', branch_id: '', company_website: '' }

/** The contact form of the platform website (`platform`) or of a restaurant website (with its branches to choose from). */
export function ContactForm({ title = 'Send us a message', platform = false, branches = [], privacyTo }: {
  title?: string; platform?: boolean; branches?: { id: number; name: string }[]; privacyTo: string
}) {
  const topics = platform ? PLATFORM_TOPICS : RESTAURANT_TOPICS
  const { pathname } = useLocation()
  const [v, setV] = useState({ ...empty, topic: topics[0][0] })
  const [consent, setConsent] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<{ reference?: string } | null>(null)
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) => setV((now) => ({ ...now, [k]: e.target.value }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (v.name.trim().length < 2) local.name = 'Enter your name.'
    if (!/^\S+@\S+\.\S+$/.test(v.email.trim())) local.email = 'Enter a valid email address.'
    if (v.preferred_contact !== 'email' && !v.phone.trim()) local.phone = 'Add your phone number so we can reach you that way.'
    if (v.subject.trim().length < 3) local.subject = 'Enter a subject.'
    if (v.message.trim().length < 10) local.message = 'Tell us a little more (at least 10 characters).'
    if (!consent) local.consent = 'Please agree so that we can answer you.'
    setErrors(local)
    if (Object.keys(local).length) return
    setBusy(true)
    try {
      const r = await api<{ reference?: string }>('/website/public/contact/', { body: { ...v, branch_id: v.branch_id ? Number(v.branch_id) : null, consent, page: pathname } })
      setSent(r)
    } catch (err) {
      if (err instanceof ApiError) setErrors({ ...err.fieldErrors(), form: err.status === 429 ? 'You have sent several messages. Please wait a while before sending another.' : err.message })
      else setErrors({ form: 'Your message could not be sent. Please try again.' })
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <div className="contact-card sent" role="status">
        <CheckCircle2 size={54} aria-hidden />
        <h2>Message sent</h2>
        <p>Thank you. We have received your message and will get back to you.</p>
        {sent.reference && <p className="muted">Your reference: <b>{sent.reference}</b></p>}
        <button className="btn secondary" onClick={() => { setSent(null); setV({ ...empty, topic: topics[0][0], name: v.name, email: v.email, phone: v.phone }); setConsent(false) }}>Send another message</button>
      </div>
    )
  }

  const input = (k: keyof typeof empty, label: string, ph: string, extra: { type?: string; max?: number; auto?: string } = {}) => (
    <Field label={label} error={errors[k]}>{(p) => <input {...p} className="input" type={extra.type ?? 'text'} autoComplete={extra.auto} maxLength={extra.max ?? 150} placeholder={ph} value={v[k]} onChange={set(k)} />}</Field>
  )
  return (
    <form className="contact-card" onSubmit={submit} noValidate>
      <h2>{title}</h2>
      {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
      <div className="form-2">
        {input('name', 'Your name', 'Enter your full name', { auto: 'name' })}
        {input('email', 'Email address', 'Enter your email address', { type: 'email', auto: 'email', max: 254 })}
        {input('phone', 'Phone number', 'Enter your phone number', { type: 'tel', auto: 'tel', max: 30 })}
        <Field label="How should we reply?" error={errors.preferred_contact}>{(p) => <select {...p} className="input" value={v.preferred_contact} onChange={set('preferred_contact')}><option value="email">By email</option><option value="phone">By phone call</option><option value="whatsapp">On WhatsApp</option></select>}</Field>
        {platform && input('business_name', 'Restaurant name (optional)', 'Enter your restaurant’s name')}
        {platform && input('city', 'City (optional)', 'Enter your city', { max: 100 })}
        <Field label="What is it about?" error={errors.topic}>{(p) => <select {...p} className="input" value={v.topic} onChange={set('topic')}>{topics.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>}</Field>
        {!platform && branches.length > 0 && <Field label="Which location? (optional)" error={errors.branch_id}>{(p) => <select {...p} className="input" value={v.branch_id} onChange={set('branch_id')}><option value="">Any / not sure</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>}
      </div>
      {input('subject', 'Subject', 'Enter your subject')}
      <Field label="Message" error={errors.message}>{(p) => <textarea {...p} className="input" rows={5} maxLength={4000} placeholder="Enter your message" value={v.message} onChange={set('message')} />}</Field>
      {/* hidden from people and assistive technology; only automated form-fillers complete it */}
      <div className="hp" aria-hidden="true"><label>Company website<input tabIndex={-1} autoComplete="off" value={v.company_website} onChange={set('company_website')} /></label></div>
      <label className="consent"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> <span>I agree that these details are kept and used to answer my message. <Link to={privacyTo}>Privacy policy</Link></span></label>
      {errors.consent && <p className="err">{errors.consent}</p>}
      <button className="btn lg" disabled={busy}>{busy ? <Spinner /> : <>Send message <Send size={17} aria-hidden /></>}</button>
    </form>
  )
}

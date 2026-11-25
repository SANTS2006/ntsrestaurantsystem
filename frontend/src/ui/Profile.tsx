import { Camera, KeyRound, Mail, Monitor, Moon, Sun, Trash2, User, Volume2, VolumeX } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useNotifications } from '../lib/live'
import { useTheme } from '../lib/theme'
import { useConfirm } from './dialogs'
import { Avatar } from './Shell'
import { Field, Modal, Spinner, useDocumentTitle, useToast } from './kit'

type Profile = { id: number; email: string; full_name: string; phone: string; avatar: string | null; role: string | null }
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const ROLE_LABEL: Record<string, string> = { restaurant_admin: 'Administrator', manager: 'Manager', cashier: 'Cashier', kitchen: 'Kitchen', waiter: 'Waiter', waitress: 'Waitress', delivery: 'Delivery', platform_admin: 'Platform admin', customer: 'Customer' }

/** Own profile for every kind of user: picture, name, phone, e-mail (verified change), password, appearance and sounds. */
export function ProfileSettings() {
  useDocumentTitle('Profile and settings')
  const { me, reload, adoptTokens } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const { choice, setChoice } = useTheme()
  const { muted, setMuted } = useNotifications()
  const file = useRef<HTMLInputElement>(null)
  const [name, setName] = useState(me?.full_name ?? '')
  const [phone, setPhone] = useState(me?.phone ?? '')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string>('')
  const [emailOpen, setEmailOpen] = useState(false)
  if (!me) return null

  async function pick(f: File | undefined) {
    if (!f) return
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(f.type)) return toast('Choose a PNG, JPEG or WebP picture.')
    if (f.size > 2 * 1024 * 1024) return toast('The picture must be 2 MB or smaller.')
    setBusy('avatar')
    try {
      const form = new FormData()
      form.append('image', f)
      await api<Profile>('/auth/profile/avatar/', { body: form })
      await reload()
      toast('Profile picture updated.')
    } catch (e) { toast(msg(e)) } finally { setBusy(''); if (file.current) file.current.value = '' }
  }
  async function removeAvatar() {
    if (!(await confirm({ title: 'Remove your profile picture?', message: 'Your initials will be shown instead.', confirmLabel: 'Remove', danger: true }))) return
    setBusy('avatar')
    try { await api('/auth/profile/avatar/', { method: 'DELETE' }); await reload(); toast('Profile picture removed.') } catch (e) { toast(msg(e)) } finally { setBusy('') }
  }
  async function save(e: FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (!name.trim()) next.full_name = 'Enter your name.'
    if (phone && !/^[0-9+()\-\s]{6,30}$/.test(phone)) next.phone = 'Enter a valid phone number.'
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy('details')
    try { await api('/auth/profile/', { method: 'PATCH', body: { full_name: name, phone } }); await reload(); toast('Profile saved.') } catch (x) { setErrors(x instanceof ApiError ? x.fieldErrors() : {}); toast(msg(x)) } finally { setBusy('') }
  }

  return (
    <div style={{ maxWidth: 1000 }}>
      <div className="page-head"><div><h1>Profile and settings</h1><p>Your picture, contact details, sign-in email and how the app looks and sounds for you.</p></div></div>
      <div className="profile-grid">
        <section className="card">
          <div className="profile-head">
            <Avatar name={me.full_name || me.email} src={me.avatar} className="lg" />
            <div>
              <h3 style={{ margin: 0 }}>{me.full_name || me.email}</h3>
              <p className="muted" style={{ margin: '2px 0 10px' }}>{ROLE_LABEL[me.role ?? ''] ?? me.role}</p>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn sm" disabled={busy === 'avatar'} onClick={() => file.current?.click()}>{busy === 'avatar' ? <Spinner size={16} /> : <Camera size={16} aria-hidden />} {me.avatar ? 'Replace picture' : 'Upload picture'}</button>
                {me.avatar && <button className="btn sm secondary" disabled={busy === 'avatar'} onClick={removeAvatar}><Trash2 size={16} aria-hidden /> Remove</button>}
              </div>
              <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden aria-label="Profile picture file" onChange={(e) => void pick(e.target.files?.[0])} />
              <p className="hint" style={{ marginTop: 8 }}>PNG, JPEG or WebP, up to 2 MB.</p>
            </div>
          </div>
        </section>

        <form className="card" onSubmit={save} noValidate>
          <h3 style={{ display: 'flex', gap: 8, alignItems: 'center' }}><User size={18} aria-hidden /> Your details</h3>
          <Field label="Full name" error={errors.full_name}>{(p) => <input {...p} className="input" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Phone number" error={errors.phone}>{(p) => <input {...p} className="input" type="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />}</Field>
          <button className="btn" disabled={busy === 'details'}>{busy === 'details' ? <Spinner size={18} /> : 'Save changes'}</button>
        </form>

        <section className="card">
          <h3 style={{ display: 'flex', gap: 8, alignItems: 'center' }}><Mail size={18} aria-hidden /> Sign-in email</h3>
          <p>{me.email}</p>
          <p className="hint">To change it you confirm your password and enter a code we send to the new address. Other devices are signed out.</p>
          <button className="btn secondary" onClick={() => setEmailOpen(true)}>Change email</button>
        </section>

        <PasswordCard />

        <section className="card">
          <h3>Appearance</h3>
          <div className="theme-seg" role="group" aria-label="Colour theme">
            <button aria-pressed={choice === 'light'} onClick={() => setChoice('light')}><Sun size={16} aria-hidden /> Light</button>
            <button aria-pressed={choice === 'dark'} onClick={() => setChoice('dark')}><Moon size={16} aria-hidden /> Dark</button>
            <button aria-pressed={choice === 'system'} onClick={() => setChoice('system')}><Monitor size={16} aria-hidden /> Device</button>
          </div>
          <h3 style={{ marginTop: 22 }}>Notification sounds</h3>
          <div className="toggle-row">
            <span className="muted">{muted ? 'Sounds are off on this device.' : 'A sound plays when an order is ready and for other alerts.'}</span>
            <button role="switch" className="switch" aria-checked={!muted} aria-label="Notification sounds" onClick={() => setMuted(!muted)} />
          </div>
          <p className="hint" style={{ marginTop: 8 }}>{muted ? <VolumeX size={14} aria-hidden /> : <Volume2 size={14} aria-hidden />} Saved on this device only.</p>
        </section>
      </div>
      {emailOpen && <EmailModal onClose={() => setEmailOpen(false)} onDone={async (t) => { await adoptTokens(t); await reload(); setEmailOpen(false); toast('Email changed.') }} />}
    </div>
  )
}

function PasswordCard() {
  const { adoptTokens } = useAuth()
  const toast = useToast()
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!cur || next.length < 10) return setError('Enter your current password and a new one of at least 10 characters.')
    setBusy(true); setError('')
    try {
      const t = await api<{ access: string; refresh: string }>('/auth/change-password/', { body: { current_password: cur, new_password: next } })
      await adoptTokens(t)
      setCur(''); setNext('')
      toast('Password changed. Other devices were signed out.')
    } catch (x) { setError(x instanceof ApiError ? (Array.isArray(x.details) ? (x.details as string[]).join(' ') : x.message) : 'Something went wrong.') } finally { setBusy(false) }
  }
  return (
    <form className="card" onSubmit={submit} noValidate>
      <h3 style={{ display: 'flex', gap: 8, alignItems: 'center' }}><KeyRound size={18} aria-hidden /> Password</h3>
      {error && <div className="alert error" role="alert">{error}</div>}
      <Field label="Current password">{(p) => <input {...p} className="input" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />}</Field>
      <Field label="New password" hint="At least 10 characters.">{(p) => <input {...p} className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />}</Field>
      <button className="btn secondary" disabled={busy}>{busy ? <Spinner size={18} /> : 'Change password'}</button>
    </form>
  )
}

function EmailModal({ onClose, onDone }: { onClose: () => void; onDone: (t: { access: string; refresh: string }) => Promise<void> }) {
  const [step, setStep] = useState<'new' | 'code'>('new')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function send(e: FormEvent) {
    e.preventDefault()
    if (!/^\S+@\S+\.\S+$/.test(email)) return setError('Enter a valid email address.')
    setBusy(true); setError('')
    try { await api('/auth/profile/email/', { body: { new_email: email.trim(), password } }); setStep('code') } catch (x) { setError(msg(x)) } finally { setBusy(false) }
  }
  async function confirmCode(e: FormEvent) {
    e.preventDefault()
    if (code.trim().length !== 6) return setError('Enter the 6-character code.')
    setBusy(true); setError('')
    try { await onDone(await api<{ access: string; refresh: string }>('/auth/profile/email/confirm/', { body: { code: code.trim() } })) } catch (x) { setError(msg(x)); setBusy(false) }
  }
  return (
    <Modal title="Change your email" onClose={onClose}>
      {error && <div className="alert error" role="alert">{error}</div>}
      {step === 'new' ? (
        <form onSubmit={send} noValidate>
          <Field label="New email address">{(p) => <input {...p} className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
          <Field label="Your password">{(p) => <input {...p} className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
          <button className="btn" disabled={busy || !password}>{busy ? <Spinner size={18} /> : 'Send code'}</button>
        </form>
      ) : (
        <form onSubmit={confirmCode} noValidate>
          <p>If the address can be used, we sent a 6-character code to <b>{email}</b>. It expires in 10 minutes.</p>
          <Field label="Code">{(p) => <input {...p} className="input" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />}</Field>
          <button className="btn" disabled={busy}>{busy ? <Spinner size={18} /> : 'Confirm and change'}</button>
        </form>
      )}
    </Modal>
  )
}

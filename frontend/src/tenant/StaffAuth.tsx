import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { Field, Spinner, useDocumentTitle } from '../ui/kit'
import { useSite } from './SiteContext'

const emailOk = (v: string) => /^\S+@\S+\.\S+$/.test(v)

function Shell({ title, children }: { title: string; children: ReactNode }) {
  const { site } = useSite()
  useDocumentTitle(`${title} | ${site.restaurant.name}`)
  return (
    <div className="login-wrap">
      <div className="card" style={{ width: 'min(440px, 100%)' }}>
        <p className="muted" style={{ marginBottom: 4 }}><Link to="/">← {site.restaurant.name}</Link></p>
        <h1 style={{ fontSize: '1.6rem' }}>{title}</h1>
        {children}
      </div>
    </div>
  )
}

const strong = (v: string) => v.length >= 10

export function SetupPassword() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (!strong(pw)) next.pw = 'Use at least 10 characters.'
    if (pw !== pw2) next.pw2 = 'Passwords do not match.'
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy(true)
    try {
      await api('/auth/setup-password/', { body: { token, password: pw }, auth: false })
      setDone(true)
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? (Array.isArray(err.details) ? (err.details as string[]).join(' ') : err.message) : 'Something went wrong.' })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Shell title="Set your password">
      {!token ? <div className="alert error">This link is missing its token. Open the link from your invitation email.</div> : done ? (
        <div><div className="alert ok">Your password is set.</div><Link className="btn" to="/login">Go to sign in</Link></div>
      ) : (
        <form onSubmit={submit} noValidate>
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          <Field label="New password" error={errors.pw} hint="At least 10 characters. Avoid common passwords.">{(p) => <input {...p} className="input" type="password" autoComplete="new-password" placeholder="Enter your new password" value={pw} onChange={(e) => setPw(e.target.value)} />}</Field>
          <Field label="Confirm password" error={errors.pw2}>{(p) => <input {...p} className="input" type="password" autoComplete="new-password" placeholder="Re-enter your new password" value={pw2} onChange={(e) => setPw2(e.target.value)} />}</Field>
          <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner /> : 'Save password'}</button>
        </form>
      )}
    </Shell>
  )
}

export function ForgotPassword() {
  const [step, setStep] = useState<'email' | 'code' | 'done'>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [pw, setPw] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  async function sendCode(e: FormEvent) {
    e.preventDefault()
    if (!emailOk(email)) return setErrors({ email: 'Enter a valid email address.' })
    setBusy(true)
    try {
      await api('/auth/password-reset/', { body: { email }, auth: false })
      setErrors({})
      setStep('code')
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : 'Something went wrong.' })
    } finally {
      setBusy(false)
    }
  }
  async function reset(e: FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (code.trim().length !== 6) next.code = 'Enter the 6-character code from your email.'
    if (!strong(pw)) next.pw = 'Use at least 10 characters.'
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy(true)
    try {
      await api('/auth/password-reset/confirm/', { body: { email, code: code.trim(), new_password: pw }, auth: false })
      setStep('done')
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : 'Something went wrong.' })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Shell title="Reset your password">
      {step === 'done' ? <div><div className="alert ok">Password updated. You can sign in now.</div><Link className="btn" to="/login">Sign in</Link></div>
        : step === 'email' ? (
          <form onSubmit={sendCode} noValidate>
            {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
            <Field label="Email address" error={errors.email}>{(p) => <input {...p} className="input" type="email" placeholder="Enter your email address" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner /> : 'Send reset code'}</button>
          </form>
        ) : (
          <form onSubmit={reset} noValidate>
            <div className="alert">If that email belongs to an account here, a code has been sent. It expires in 10 minutes.</div>
            {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
            <Field label="Code" error={errors.code}>{(p) => <input {...p} className="input" autoComplete="one-time-code" maxLength={6} placeholder="Enter the 6-character code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />}</Field>
            <Field label="New password" error={errors.pw}>{(p) => <input {...p} className="input" type="password" autoComplete="new-password" placeholder="Enter your new password" value={pw} onChange={(e) => setPw(e.target.value)} />}</Field>
            <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner /> : 'Reset password'}</button>
          </form>
        )}
    </Shell>
  )
}

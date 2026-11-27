import { useState, type FormEvent } from 'react'
import { KeyRound, Lock, Mail, Phone, User } from 'lucide-react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AuthField, GoogleSignIn, OrDivider, RememberRow, type GoogleResult } from '../ui/Auth'
import { Spinner } from '../ui/kit'
import { MfaChallengeForm } from '../ui/Mfa'
import { Shell } from './AuthShell'

export const STAFF_ROLES = ['restaurant_admin', 'manager', 'cashier', 'kitchen', 'waiter', 'waitress', 'delivery', 'platform_admin']
const emailOk = (v: string) => /^\S+@\S+\.\S+$/.test(v)

const safeNext = (n: string | null) => (n && n.startsWith('/') && !n.startsWith('//') ? n : null) // no open redirects

/** Where to go after signing in: the page that asked for it, otherwise the person's home. Customers are never sent into the workspace. */
export function destination(role: string | null, next: string | null): string {
  const staff = STAFF_ROLES.includes(role ?? '')
  if (next && (staff || !next.startsWith('/manage'))) return next
  return staff ? '/manage' : '/account'
}

export function Login() {
  const { login, me, adoptTokens } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [challenge, setChallenge] = useState<string | null>(null)
  const dest = (role: string | null) => destination(role, next)
  if (me) return <Navigate to={dest(me.role)} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!emailOk(email)) local.email = 'Enter a valid email address.'
    if (!password) local.password = 'Enter your password.'
    setErrors(local)
    if (Object.keys(local).length) return
    setBusy(true)
    try {
      const profile = await login(email.trim(), password, remember)
      if ('mfa_token' in profile) { setChallenge(profile.mfa_token); return }
      navigate(dest(profile.role))
    } catch (err) {
      if (err instanceof ApiError && err.code === 'email_not_verified') return navigate(`/verify-email?email=${encodeURIComponent(email.trim())}`)
      setErrors({ form: err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.' })
    } finally { setBusy(false) }
  }
  async function google(r: GoogleResult) {
    if (r.mfa_token) return setChallenge(r.mfa_token)
    if (r.access && r.refresh) { const profile = await adoptTokens({ access: r.access, refresh: r.refresh }, remember); navigate(dest(profile.role)) }
  }
  return (
    <Shell title={challenge ? 'Two-step verification' : 'Sign in'} subtitle={challenge ? undefined : 'Welcome back. Enter your details to continue.'}
      footer={challenge ? undefined : <>Don&apos;t have an account? <Link to={`/register${next ? `?next=${encodeURIComponent(next)}` : ''}`}>Sign Up</Link></>}>
      {challenge ? <MfaChallengeForm token={challenge} remember={remember} onDone={() => navigate(next ?? '/manage')} onCancel={() => setChallenge(null)} /> : <>
        <form onSubmit={submit} noValidate>
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          <AuthField label="Email address" icon={User} error={errors.email} type="email" autoComplete="username" placeholder="Enter your email address" value={email} onChange={(e) => setEmail(e.target.value)} />
          <AuthField label="Password" icon={Lock} secret error={errors.password} autoComplete="current-password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <RememberRow remember={remember} onChange={setRemember} forgotTo="/forgot-password" />
          <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner size={20} /> : 'Sign in'}</button>
        </form>
        <OrDivider />
        <GoogleSignIn label="Sign in with Google" onResult={(r) => void google(r)} onError={(m) => setErrors({ form: m })} />
        <p className="hint" style={{ marginTop: 10, textAlign: 'center' }}>By continuing with Google you agree to the <Link to="/policies/terms-of-use">Terms</Link> and <Link to="/policies/privacy-policy">Privacy Policy</Link>.</p>
      </>}
    </Shell>
  )
}

export function Register() {
  const { me, adoptTokens } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const [v, setV] = useState({ full_name: '', email: '', phone: '', password: '' })
  const [terms, setTerms] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [challenge, setChallenge] = useState<string | null>(null)
  if (me) return <Navigate to="/account" replace />
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!v.full_name.trim()) local.full_name = 'Enter your full name.'
    if (!emailOk(v.email)) local.email = 'Enter a valid email address.'
    if (v.phone && !/^[0-9+()\-\s]{6,30}$/.test(v.phone)) local.phone = 'Enter a valid phone number.'
    if (v.password.length < 10) local.password = 'Use at least 10 characters.'
    if (!terms) local.accept_terms = 'You must agree to the Terms of Service and Privacy Policy.'
    setErrors(local)
    if (Object.keys(local).length) return
    setBusy(true)
    try {
      await api('/auth/register/', { body: { ...v, email: v.email.trim(), accept_terms: terms }, auth: false })
      navigate(`/verify-email?email=${encodeURIComponent(v.email.trim())}${next ? `&next=${encodeURIComponent(next)}` : ''}`)
    } catch (err) {
      if (err instanceof ApiError) {
        const f = err.fieldErrors()
        setErrors({ ...f, password: f.password ?? '', form: Object.keys(f).length ? '' : err.message })
      } else setErrors({ form: 'Something went wrong. Please try again.' })
    } finally { setBusy(false) }
  }
  async function google(r: GoogleResult) {
    if (r.mfa_token) return setChallenge(r.mfa_token)
    if (r.access && r.refresh) { await adoptTokens({ access: r.access, refresh: r.refresh }); navigate(next ?? '/account') }
  }
  return (
    <Shell title={challenge ? 'Two-step verification' : 'Sign up'} subtitle={challenge ? undefined : 'Create your account in less than a minute.'}
      footer={challenge ? undefined : <>Already registered? <Link to="/login">Sign in</Link></>}>
      {challenge ? <MfaChallengeForm token={challenge} onDone={() => navigate('/account')} onCancel={() => setChallenge(null)} /> : <>
        <form onSubmit={submit} noValidate>
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          <AuthField label="Full name" icon={User} error={errors.full_name} autoComplete="name" placeholder="Enter your full name" value={v.full_name} onChange={set('full_name')} />
          <AuthField label="Email address" icon={Mail} error={errors.email} type="email" autoComplete="email" placeholder="Enter your email address" value={v.email} onChange={set('email')} />
          <AuthField label="Phone number (optional)" icon={Phone} error={errors.phone} type="tel" autoComplete="tel" placeholder="Enter your phone number" value={v.phone} onChange={set('phone')} />
          <AuthField label="Password" icon={Lock} secret error={errors.password} hint="At least 10 characters. Avoid common passwords." autoComplete="new-password" placeholder="Enter your password" value={v.password} onChange={set('password')} />
          <div className="field">
            <label className="auth-check" style={{ fontWeight: 400 }}><input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} aria-invalid={!!errors.accept_terms} /> <span>I agree to the <Link to="/policies/terms-of-use" target="_blank">Terms of Service</Link> and <Link to="/policies/privacy-policy" target="_blank">Privacy Policy</Link></span></label>
            {errors.accept_terms && <span className="err">{errors.accept_terms}</span>}
          </div>
          <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner size={20} /> : 'Create account'}</button>
        </form>
        <OrDivider />
        <GoogleSignIn label="Sign up with Google" onResult={(r) => void google(r)} onError={(m) => setErrors({ form: m })} />
      </>}
    </Shell>
  )
}

export function VerifyEmail() {
  const [params] = useSearchParams()
  const email = params.get('email') ?? ''
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (code.trim().length !== 6) return setError('Enter the 6-character code from your email.')
    setBusy(true); setError('')
    try {
      await api('/auth/verify-email/', { body: { email, code: code.trim() }, auth: false })
      navigate(`/login${next ? `?next=${encodeURIComponent(next)}` : ''}`, { state: { verified: true } })
    } catch (err) { setError(err instanceof ApiError ? err.message : 'Something went wrong.') } finally { setBusy(false) }
  }
  async function resend() {
    setInfo(''); setError('')
    try { await api('/auth/resend-verification/', { body: { email }, auth: false }); setInfo('If your account needs verification, a new code has been sent. You can request one every minute.') } catch (err) { setError(err instanceof ApiError ? err.message : 'Could not resend.') }
  }
  return (
    <Shell title="Verify your email" subtitle="One more step before you can sign in.">
      <p>We sent a 6-character code to <b>{email || 'your email'}</b>. It expires in 10 minutes.</p>
      <form onSubmit={submit} noValidate>
        {error && <div className="alert error" role="alert">{error}</div>}
        {info && <div className="alert ok">{info}</div>}
        <AuthField label="Verification code" icon={KeyRound} autoComplete="one-time-code" maxLength={6} placeholder="Enter the 6-character code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
        <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner size={20} /> : 'Verify and continue'}</button>
      </form>
      <p style={{ marginTop: 14 }}>Did not get it? <button className="btn sm secondary" type="button" onClick={resend}>Send a new code</button></p>
    </Shell>
  )
}

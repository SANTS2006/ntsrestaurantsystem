import { Lock, User } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AuthField, AuthLayout, GoogleSignIn, OrDivider, RememberRow, type GoogleResult } from '../ui/Auth'
import { Spinner, useDocumentTitle } from '../ui/kit'
import { MfaChallengeForm } from '../ui/Mfa'

export default function Login() {
  useDocumentTitle('Sign in')
  const { login, me, logout, adoptTokens } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({})
  const [remember, setRemember] = useState(false)
  const [busy, setBusy] = useState(false)
  const [challenge, setChallenge] = useState<string | null>(null)

  if (me?.role === 'platform_admin') return <Navigate to="/admin" replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    const next: typeof errors = {}
    if (!/^\S+@\S+\.\S+$/.test(email)) next.email = 'Enter a valid email address.'
    if (!password) next.password = 'Enter your password.'
    setErrors(next)
    if (Object.keys(next).length) return
    setBusy(true)
    try {
      const profile = await login(email.trim(), password, remember)
      if ('mfa_token' in profile) { setChallenge(profile.mfa_token); return }
      if (profile.role !== 'platform_admin') {
        logout()
        setErrors({ form: 'This account cannot sign in here.' })
      } else navigate('/admin')
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.' })
    } finally {
      setBusy(false)
    }
  }

  async function google(result: GoogleResult) {
    setErrors({})
    if (result.mfa_token) { setChallenge(result.mfa_token); return }
    if (!result.access || !result.refresh) return
    try {
      const profile = await adoptTokens({ access: result.access, refresh: result.refresh }, remember)
      if (profile.role !== 'platform_admin') {
        logout()
        setErrors({ form: 'This account cannot sign in here.' })
      } else navigate('/admin')
    } catch (err) {
      setErrors({ form: err instanceof ApiError ? err.message : 'Google sign-in failed.' })
    }
  }

  return (
    <AuthLayout
      brand="NTS Restaurant Platform"
      logo="/logo-192.png"
      tagline="Run every restaurant from one secure place: restaurants, branches, staff, sales and reports."
      title={challenge ? 'Two-step verification' : 'Sign in'}
      subtitle={challenge ? undefined : 'Sign in to manage the platform.'}
    >
      {challenge ? <MfaChallengeForm token={challenge} remember={remember} onDone={() => navigate('/admin')} onCancel={() => setChallenge(null)} /> : (
        <form onSubmit={submit} noValidate>
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          <AuthField label="Email address" icon={User} error={errors.email} type="email" autoComplete="username" placeholder="Enter your email address" value={email} onChange={(e) => setEmail(e.target.value)} />
          <AuthField label="Password" icon={Lock} secret error={errors.password} autoComplete="current-password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <RememberRow remember={remember} onChange={setRemember} forgotTo="/forgot-password" />
          <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner /> : 'Sign in'}</button>
          <OrDivider />
          <GoogleSignIn onResult={(r) => void google(r)} onError={(m) => setErrors({ form: m })} />
          <p className="hint center">Google sign-in works only for an existing platform administrator’s email address.</p>
        </form>
      )}
    </AuthLayout>
  )
}

import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Field, Spinner, useDocumentTitle } from '../ui/kit'
import { MfaChallengeForm } from '../ui/Mfa'

export default function Login() {
  useDocumentTitle('Sign in')
  const { login, me, logout } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({})
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
      const profile = await login(email.trim(), password)
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

  return (
    <div className="login-wrap">
      {challenge ? <div className="card" style={{ width: 'min(420px, 100%)' }}><MfaChallengeForm token={challenge} onDone={() => navigate('/admin')} onCancel={() => setChallenge(null)} /></div> : <form className="card" style={{ width: 'min(420px, 100%)' }} onSubmit={submit} noValidate>
        <img className="login-logo" src="/logo-192.png" alt="NTS Restaurant Platform" width={72} height={72} />
        <h1 style={{ fontSize: '1.6rem', textAlign: 'center' }}>Platform sign in</h1>
        {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
        <Field label="Email address" error={errors.email}>
          {(p) => <input {...p} className="input" type="email" autoComplete="username" placeholder="Enter your email address" value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Password" error={errors.password}>
          {(p) => <input {...p} className="input" type="password" autoComplete="current-password" placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner /> : 'Sign in'}</button>
      </form>}
    </div>
  )
}

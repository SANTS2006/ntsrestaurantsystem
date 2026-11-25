import { useState, type FormEvent } from 'react'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { KeyRound, ShieldCheck } from 'lucide-react'
import { AuthField } from './Auth'
import { Field, Modal, Spinner, useToast } from './kit'

/** Second step of sign-in: a six-digit code from the authenticator app, or one recovery code. */
export function MfaChallengeForm({ token, onDone, onCancel, remember = false }: { token: string; onDone: () => void; onCancel: () => void; remember?: boolean }) {
  const { completeMfa } = useAuth()
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!code.trim()) return setError(recovery ? 'Enter a recovery code.' : 'Enter the 6-digit code.')
    setBusy(true); setError('')
    try { await completeMfa(token, code.trim(), recovery, remember); onDone() } catch (x) { setError(x instanceof ApiError ? x.message : 'Verification failed.') } finally { setBusy(false) }
  }
  return (
    <form onSubmit={submit} noValidate>
      <p className="auth-sub">{recovery ? 'Enter one of your recovery codes. Each works once.' : 'Open your authenticator app and enter the 6-digit code.'}</p>
      {error && <div className="alert error" role="alert">{error}</div>}
      <AuthField label={recovery ? 'Recovery code' : 'Authentication code'} icon={KeyRound} inputMode={recovery ? 'text' : 'numeric'} autoComplete="one-time-code" autoFocus placeholder={recovery ? 'xxxx-xxxx-xxxx' : '123456'} value={code} onChange={(e) => setCode(e.target.value)} />
      <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner /> : 'Verify and sign in'}</button>
      <p style={{ marginTop: 12 }}><button type="button" className="btn sm ghost" onClick={() => { setRecovery(!recovery); setCode(''); setError('') }}>{recovery ? 'Use my authenticator app' : 'Use a recovery code instead'}</button> <button type="button" className="btn sm ghost" onClick={onCancel}>Back</button></p>
    </form>
  )
}


type Policy = { enforced: boolean; master_switch: boolean }

/** Platform owner only: switch the two-step requirement for administrators on or off for the whole platform. */
function MfaPolicyCard() {
  const { me, reload } = useAuth()
  const toast = useToast()
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [target, setTarget] = useState<boolean | null>(null)
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (!loaded) { setLoaded(true); void api<Policy>('/platform/settings/mfa/').then(setPolicy).catch(() => undefined) }
  if (!policy) return null

  async function apply() {
    setBusy(true); setError('')
    try {
      const r = await api<Policy>('/platform/settings/mfa/', { body: { enforced: target, password, code } })
      setPolicy(r)
      toast(r.enforced ? 'Two-step verification is now required for administrators.' : 'Two-step verification is no longer required.')
      setTarget(null); setPassword(''); setCode('')
      await reload()
    } catch (e) { setError(e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.') } finally { setBusy(false) }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="toggle-row">
        <div>
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}><ShieldCheck size={20} aria-hidden /> Require two-step verification</h3>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {policy.master_switch
              ? (policy.enforced ? 'Platform and restaurant administrators must use an authenticator app to sign in.' : 'Off: administrators sign in with a password only. Anyone can still turn it on for their own account.')
              : 'Disabled in the server settings (MFA_ENFORCEMENT=false). Change it there to use this switch.'}
          </p>
        </div>
        <button type="button" role="switch" className="switch" aria-checked={policy.enforced} aria-label="Require two-step verification" disabled={!policy.master_switch} onClick={() => { setError(''); setTarget(!policy.enforced) }} />
      </div>
      {target !== null && (
        <Modal title={target ? 'Require two-step verification' : 'Stop requiring two-step verification'} onClose={() => setTarget(null)}>
          <h2 style={{ marginTop: 0 }}>{target ? 'Turn the requirement on?' : 'Turn the requirement off?'}</h2>
          <p className="muted">{target ? 'Administrators without it will be asked to set it up at their next sign-in.' : 'Your administrators will be able to sign in, and to turn their own factor off, without a code. This weakens protection of the platform.'}</p>
          {error && <div className="alert error" role="alert">{error}</div>}
          <Field label="Your password">{(p) => <input {...p} className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
          {me?.mfa?.enabled && <Field label="Current 6-digit code">{(p) => <input {...p} className="input" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />}</Field>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button className="btn secondary" onClick={() => setTarget(null)}>Cancel</button>
            <button className={target ? 'btn' : 'btn danger'} disabled={busy || !password || (!!me?.mfa?.enabled && code.length < 6)} onClick={apply}>{busy ? <Spinner /> : target ? 'Turn on' : 'Turn off'}</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

type Status = { enabled: boolean; required: boolean; recovery_codes_left: number }

/** Enrol, view and manage two-factor authentication. `forced` is shown when the account must enrol before using the system. */
export function MfaSettings({ forced = false }: { forced?: boolean }) {
  const { me, reload, adoptTokens } = useAuth()
  const toast = useToast()
  const [status, setStatus] = useState<Status | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [password, setPassword] = useState('')
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string; qr: string } | null>(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const enabled = status?.enabled ?? me?.mfa?.enabled ?? false

  if (!loaded) { setLoaded(true); void api<Status>('/auth/mfa/status/').then(setStatus) }

  async function run(fn: () => Promise<void>) {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e instanceof ApiError ? e.message : 'Something went wrong.') } finally { setBusy(false) }
  }
  const start = () => run(async () => { setSetup(await api('/auth/mfa/setup/', { body: { password } })); setPassword('') })
  const confirm = () => run(async () => {
    const r = await api<{ recovery_codes: string[]; access: string; refresh: string }>('/auth/mfa/confirm/', { body: { code } })
    setCodes(r.recovery_codes); setSetup(null); setCode('')
    await adoptTokens({ access: r.access, refresh: r.refresh })
    setStatus(await api<Status>('/auth/mfa/status/'))
    toast('Two-step verification is on.')
  })
  const regenerate = () => run(async () => { const r = await api<{ recovery_codes: string[] }>('/auth/mfa/recovery-codes/', { body: { password, code } }); setCodes(r.recovery_codes); setPassword(''); setCode(''); setStatus(await api<Status>('/auth/mfa/status/')) })
  const disable = () => run(async () => { await api('/auth/mfa/disable/', { body: { password, code } }); toast('Two-step verification turned off. Please sign in again.'); await reload() })

  return (
    <div style={{ maxWidth: 640 }}>
      {forced && <div className="alert warn"><b>Set up two-step verification to continue.</b> Your role requires it. It takes a minute and protects your restaurant if your password is ever stolen.</div>}
      <h1 className="page-title">Two-step verification</h1>
      {me?.role === 'platform_admin' && <MfaPolicyCard />}
      {error && <div className="alert error" role="alert">{error}</div>}
      {codes && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3>Save your recovery codes</h3>
          <p className="muted">Each code works once if you lose your phone. They are shown only now: store them somewhere safe, away from your password.</p>
          <pre style={{ columns: 2, margin: 0, fontSize: '1rem' }}>{codes.join('\n')}</pre>
          <p style={{ marginTop: 12 }}><button className="btn sm secondary" onClick={() => void navigator.clipboard?.writeText(codes.join('\n'))}>Copy codes</button> <button className="btn sm" onClick={() => setCodes(null)}>I have saved them</button></p>
        </div>
      )}
      {!enabled && !setup && (
        <div className="card">
          <p>Use an authenticator app (Google Authenticator, Microsoft Authenticator, Authy, 1Password...) to generate a code each time you sign in.</p>
          <Field label="Confirm with your password">{(p) => <input {...p} className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
          <button className="btn" disabled={busy || !password} onClick={start}>Set up</button>
        </div>
      )}
      {setup && (
        <div className="card">
          <h3>1. Scan this code</h3>
          <img src={setup.qr} alt="QR code for your authenticator app" width={200} height={200} style={{ background: '#fff', padding: 8, borderRadius: 8 }} />
          <p className="muted" style={{ overflowWrap: 'anywhere' }}>Cannot scan? Enter this key manually: <code>{setup.secret}</code></p>
          <h3>2. Enter the 6-digit code it shows</h3>
          <Field label="Code">{(p) => <input {...p} className="input" inputMode="numeric" autoComplete="one-time-code" placeholder="123456" value={code} onChange={(e) => setCode(e.target.value)} />}</Field>
          <button className="btn" disabled={busy || code.length < 6} onClick={confirm}>Turn on</button>
        </div>
      )}
      {enabled && !setup && (
        <div className="card">
          <p><span className="badge active">On</span> You will be asked for a code each time you sign in. <span className="muted">{status?.recovery_codes_left ?? 0} recovery code(s) left.</span></p>
          <Field label="Password">{(p) => <input {...p} className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
          <Field label="Current 6-digit code">{(p) => <input {...p} className="input" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />}</Field>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn secondary" disabled={busy || !password || code.length < 6} onClick={regenerate}>New recovery codes</button>
            {!(status?.required ?? me?.mfa?.required) && <button className="btn danger" disabled={busy || !password || code.length < 6} onClick={disable}>Turn off</button>}
          </div>
          {(status?.required ?? me?.mfa?.required) && <p className="hint" style={{ marginTop: 8 }}>Your role requires two-step verification, so it cannot be turned off here. The platform owner can switch the requirement off under Admin, Security. Lost your phone? Ask a platform administrator to reset it.</p>}
        </div>
      )}
    </div>
  )
}

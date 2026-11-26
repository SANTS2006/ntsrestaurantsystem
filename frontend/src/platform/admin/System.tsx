import { useState, type FormEvent } from 'react'
import { ApiError, api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { PasswordInput, Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'

type Check = { name: string; status: 'ok' | 'warning' | 'critical'; detail: string }
type Health = { status: 'ok' | 'warning' | 'critical'; checked_at: string; checks: Check[]; runtime: Record<string, string | boolean>; config: Record<string, number> }
type Backup = { media_files?: number; media_note?: string; id: number; kind: string; status: string; storage: string; size_bytes: number; sha256: string; rows: number; error: string; created_at: string; finished_at: string | null; verified_at: string | null; verify_ok: boolean | null; verify_error: string; pruned: boolean }

const LABEL = { ok: 'Healthy', warning: 'Needs attention', critical: 'Action needed' } as const
const badge = (s: Check['status']) => (s === 'ok' ? 'active' : 'suspended')
const size = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)
const msg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

export default function System() {
  useDocumentTitle('System')
  const toast = useToast()
  const health = useAsync(() => api<Health>('/system/health/'), [])
  const backups = useAsync(() => api<Backup[]>('/system/backups/'), [])
  const [busy, setBusy] = useState<string | null>(null)
  const [restoring, setRestoring] = useState<Backup | null>(null)

  async function run(key: string, fn: () => Promise<Backup | void>, ok: (b: Backup | void) => string) {
    setBusy(key)
    try { const b = await fn(); toast(ok(b)); backups.reload(); health.reload() } catch (e) { toast(msg(e)) } finally { setBusy(null) }
  }
  const h = health.data
  return (
    <>
      <h1 className="page-title">System</h1>
      {health.error && <ErrorState message={health.error} onRetry={health.reload} />}
      {health.loading && !h ? <Skeleton h={160} /> : h && (
        <>
          <p><span className={`badge ${badge(h.status)}`}>{LABEL[h.status]}</span> <span className="muted">checked {new Date(h.checked_at).toLocaleTimeString()} · Python {String(h.runtime.python)} · Django {String(h.runtime.django)} · payments: {String(h.runtime.payment_provider)} · email: {String(h.runtime.email_provider)}</span> <button className="btn sm secondary" onClick={health.reload}>Recheck</button></p>
          <div className="grid g3" style={{ marginBottom: 16 }}>
            {h.checks.map((c) => <div className="card" key={c.name}><b>{c.name}</b> <span className={`badge ${badge(c.status)}`}>{LABEL[c.status]}</span><p className="muted" style={{ margin: '6px 0 0' }}>{c.detail}</p></div>)}
          </div>
        </>
      )}
      <div className="toolbar">
        <h2 style={{ margin: 0, fontSize: '1.2rem' }}>Backups</h2>
        <span style={{ flex: 1 }} />
        <button className="btn sm" disabled={busy !== null} onClick={() => run('new', () => api<Backup>('/system/backups/', { body: {} }), (b) => ((b as Backup).status === 'succeeded' ? 'Backup completed.' : `Backup failed: ${(b as Backup).error}`))}>{busy === 'new' ? 'Backing up…' : 'Back up now'}</button>
      </div>
      <p className="muted">Encrypted archives of the platform database in Cloudflare R2. <b>Back up now</b> creates one, <b>Verify</b> proves it can be read, and <b>Restore</b> replaces the live data with it (guarded by your password, an authenticator code and a typed confirmation). Backups cannot be downloaded.</p>
      {backups.error && <ErrorState message={backups.error} onRetry={backups.reload} />}
      <div className="card table-wrap">
        {backups.loading && !backups.data ? <Skeleton h={100} /> : !backups.data?.length ? <Empty title="No backups yet">Press “Back up now” to take the first one.</Empty> : (
          <table className="tbl"><thead><tr><th>#</th><th>When</th><th>Type</th><th>Status</th><th>Size</th><th>Rows</th><th>Stored in</th><th>Verified</th><th /></tr></thead><tbody>
            {backups.data.map((b) => (
              <tr key={b.id}>
                <td>{b.id}</td><td>{new Date(b.created_at).toLocaleString()}</td><td>{b.kind}</td>
                <td><span className={`badge ${b.status === 'succeeded' ? 'active' : b.status === 'failed' ? 'suspended' : ''}`}>{b.status}</span>{b.error && <div className="err" style={{ fontSize: '.8rem' }}>{b.error}</div>}</td>
                <td>{b.status === 'succeeded' ? size(b.size_bytes) : '–'}</td><td>{b.status === 'succeeded' ? b.rows : '–'}{b.status === 'succeeded' && <div className="muted" style={{ fontSize: '.8rem' }}>{b.media_files ? `${b.media_files} media file(s)` : b.media_note || ''}</div>}</td><td>{b.storage || '–'}{b.pruned && ' (removed)'}</td>
                <td>{b.verify_ok === null ? <span className="muted">not yet</span> : b.verify_ok ? <span className="badge active">OK {b.verified_at && new Date(b.verified_at).toLocaleDateString()}</span> : <span className="err">Failed: {b.verify_error}</span>}</td>
                <td>{b.status === 'succeeded' && !b.pruned && <button className="btn sm secondary" disabled={busy !== null} onClick={() => run(`v${b.id}`, () => api<Backup>(`/system/backups/${b.id}/verify/`, { body: {} }), (r) => ((r as Backup).verify_ok ? 'Backup verified.' : 'Verification failed.'))}>{busy === `v${b.id}` ? 'Checking…' : 'Verify'}</button>}{' '}{b.status === 'succeeded' && !b.pruned && <button className="btn sm danger" disabled={busy !== null} onClick={() => setRestoring(b)}>Restore</button>}</td>
              </tr>))}
          </tbody></table>)}
      </div>
      {restoring && <RestoreModal backup={restoring} onClose={() => setRestoring(null)} />}
    </>
  )
}

/** Replace ALL platform data with a backup. Needs the password, a fresh authenticator code and the typed phrase. */
function RestoreModal({ backup, onClose }: { backup: Backup; onClose: () => void }) {
  const { logout } = useAuth()
  const [f, setF] = useState({ password: '', code: '', confirm: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const phrase = `RESTORE ${backup.id}`
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (f.confirm.trim() !== phrase) return setErr(`Type ${phrase} exactly to confirm.`)
    setBusy(true); setErr('')
    try {
      await api(`/system/backups/${backup.id}/restore/`, { body: f })
      setDone('Restore finished. Everyone, including you, has been signed out.')
      setTimeout(() => { logout(); location.href = '/login' }, 2500)
    } catch (x) { setErr(x instanceof ApiError ? (Object.values(x.fieldErrors())[0] ?? x.message) : 'The restore failed.') } finally { setBusy(false) }
  }
  return (
    <Modal title={`Restore backup #${backup.id}`} onClose={busy ? () => {} : onClose}>
      {done ? <div className="alert ok" role="status">{done}</div> : (
        <form onSubmit={submit} noValidate>
          <div className="alert warn"><b>This replaces everything on the platform</b> (restaurants, staff, orders, payments, settings) with the data as it was on <b>{new Date(backup.created_at).toLocaleString()}</b>. Anything created since then is removed from the live system. Before it starts, a safety snapshot of the current data is taken and verified, so this restore can itself be undone. Every user is signed out afterwards, and the platform is unavailable for a few moments.</div>
          {err && <div className="alert error" role="alert">{err}</div>}
          <Field label="Your password">{(p) => <PasswordInput {...p} autoComplete="current-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />}</Field>
          <Field label="Authenticator code" hint="Required when two-step verification is on for your account.">{(p) => <input {...p} className="input" inputMode="numeric" autoComplete="one-time-code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />}</Field>
          <Field label={`Type ${phrase} to confirm`}>{(p) => <input {...p} className="input" autoComplete="off" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} />}</Field>
          <button className="btn danger" disabled={busy || !f.password || f.confirm.trim() !== phrase}>{busy ? <><Spinner /> Restoring, do not close this page…</> : 'Restore this backup'}</button>
        </form>
      )}
    </Modal>
  )
}

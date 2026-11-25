import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useConfirm, usePrompt } from '../../ui/dialogs'

type Member = { id: number; user_id: number; full_name: string; email: string; phone: string; role: string; role_label: string; is_active: boolean; invite_pending: boolean; branches: { id: number; name: string }[] }
type BranchRow = { id: number; name: string; status: string }
const ALL_ROLES: [string, string][] = [['manager', 'Branch Manager'], ['cashier', 'Cashier'], ['kitchen', 'Kitchen Staff'], ['waiter', 'Waiter'], ['waitress', 'Waitress'], ['delivery', 'Delivery Staff']]
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')

export default function Staff() {
  const prompt = usePrompt()
  useDocumentTitle('Staff')
  const { me } = useAuth()
  const toast = useToast()
  const isAdmin = me?.role === 'restaurant_admin' || me?.role === 'platform_admin'
  const roles = ALL_ROLES.filter(([r]) => isAdmin || r !== 'manager') // a manager can never create managers
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [active, setActive] = useState('')
  const [page, setPage] = useState(1)
  const [modal, setModal] = useState<{ kind: 'invite' } | { kind: 'edit'; m: Member } | { kind: 'activity'; m: Member } | null>(null)
  const branches = useAsync(() => api<Page<BranchRow>>('/restaurants/branches/', { params: { page_size: 100 } }), [])
  const list = useAsync(() => api<Page<Member>>('/staff/members/', { params: { q, role, active, page } }), [q, role, active, page])

  async function act(m: Member, path: string, ok: string, reason?: string) {
    try { await api(`/staff/members/${m.id}/${path}/`, { body: reason ? { reason } : {} }); toast(ok); list.reload() } catch (e) { toast(msg(e)) }
  }
  const editable = (m: Member) => m.user_id !== me?.id && (isAdmin ? m.role !== 'restaurant_admin' : m.role !== 'manager' && m.role !== 'restaurant_admin')
  return (
    <>
      <div className="toolbar"><h1 style={{ fontSize: '1.7rem', margin: 0, flex: 1 }}>Staff</h1><button className="btn" onClick={() => setModal({ kind: 'invite' })}><Plus size={18} aria-hidden /> Add staff</button></div>
      <div className="toolbar">
        <input className="input" style={{ maxWidth: 240 }} type="search" placeholder="Search name or email" aria-label="Search staff" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <select className="input" style={{ maxWidth: 190 }} aria-label="Filter by role" value={role} onChange={(e) => { setRole(e.target.value); setPage(1) }}><option value="">All roles</option>{ALL_ROLES.map(([r, l]) => <option key={r} value={r}>{l}</option>)}</select>
        <select className="input" style={{ maxWidth: 150 }} aria-label="Filter by status" value={active} onChange={(e) => { setActive(e.target.value); setPage(1) }}><option value="">All</option><option value="1">Active</option><option value="0">Inactive</option></select>
      </div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={100} /> : !list.data?.results.length ? <Empty title="No staff found" /> : (
          <table className="tbl"><thead><tr><th>Name</th><th>Role</th><th>Branches</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((m) => (
              <tr key={m.id}><td><b>{m.full_name || '—'}</b><div className="muted">{m.email}</div></td><td>{m.role_label}</td><td>{m.branches.map((b) => b.name).join(', ') || 'All'}</td>
                <td><span className={`badge ${m.is_active ? 'active' : 'suspended'}`}>{m.is_active ? 'active' : 'inactive'}</span>{m.invite_pending && <span className="badge" style={{ marginLeft: 6 }}>invite pending</span>}</td>
                <td style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <button className="btn sm secondary" onClick={() => setModal({ kind: 'activity', m })}>Activity</button>
                  {editable(m) && <>
                    <button className="btn sm secondary" onClick={() => setModal({ kind: 'edit', m })}>Edit</button>
                    {m.invite_pending && <button className="btn sm secondary" onClick={() => act(m, 'resend-invite', 'Invitation sent again.')}>Resend invite</button>}
                    {m.is_active ? <button className="btn sm danger" onClick={async () => { const r = await prompt({ title: `Deactivate ${m.full_name || m.email}?`, message: 'They will be signed out immediately.', label: 'Reason (optional)', danger: true, confirmLabel: 'Deactivate' }); if (r !== null) void act(m, 'deactivate', 'Deactivated.', r) }}>Deactivate</button>
                      : <button className="btn sm" onClick={() => act(m, 'activate', 'Reactivated.')}>Reactivate</button>}
                  </>}
                </td></tr>
            ))}
          </tbody></table>)}
      </div>
      {list.data && (list.data.next || list.data.previous) && <div className="toolbar" style={{ marginTop: 12 }}><button className="btn sm secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button><span className="muted">Page {page}</span><button className="btn sm secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button></div>}
      {modal?.kind === 'invite' && <StaffForm roles={roles} branches={(branches.data?.results ?? []).filter((b) => b.status === 'active')} onClose={() => setModal(null)} onSaved={() => { setModal(null); list.reload() }} />}
      {modal?.kind === 'edit' && <StaffForm roles={roles} branches={(branches.data?.results ?? []).filter((b) => b.status === 'active')} member={modal.m} onClose={() => setModal(null)} onSaved={() => { setModal(null); list.reload() }} />}
      {modal?.kind === 'activity' && <Activity m={modal.m} onClose={() => setModal(null)} />}
    </>
  )
}

function StaffForm({ roles, branches, member, onClose, onSaved }: { roles: [string, string][]; branches: BranchRow[]; member?: Member; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [v, setV] = useState({ full_name: member?.full_name ?? '', email: member?.email ?? '', phone: member?.phone ?? '', role: member?.role ?? roles[0]?.[0] ?? 'cashier' })
  const [sel, setSel] = useState<number[]>(member?.branches.map((b) => b.id) ?? [])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const toggle = (id: number) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id])
  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!v.full_name.trim()) local.full_name = 'Enter the full name.'
    if (!/^\S+@\S+\.\S+$/.test(v.email.trim())) local.email = 'Enter a valid email address.'
    if (v.phone && !/^[0-9+()\-\s]{6,30}$/.test(v.phone)) local.phone = 'Enter a valid phone number.'
    if (!sel.length) local.branch_ids = 'Choose at least one branch.'
    setErrors(local)
    if (Object.keys(local).length) return
    const emailChanged = !!member && v.email.trim().toLowerCase() !== member.email.toLowerCase()
    if (emailChanged && !(await confirm({ title: 'Change this email address?', message: member.invite_pending ? `The invitation will be sent again to ${v.email.trim()}.` : `${member.full_name || member.email} will be signed out everywhere and must confirm ${v.email.trim()} with a code before signing in again.`, confirmLabel: 'Change email' }))) return
    setBusy(true)
    try {
      if (member) await api(`/staff/members/${member.id}/`, { method: 'PATCH', body: { full_name: v.full_name.trim(), phone: v.phone, role: v.role, branch_ids: sel, ...(emailChanged ? { email: v.email.trim() } : {}) } })
      else await api('/staff/invitations/', { body: { full_name: v.full_name.trim(), email: v.email.trim(), phone: v.phone, role: v.role, branch_ids: sel } })
      toast(member ? 'Staff member updated.' : 'Invitation sent. They will receive a secure link to set their password.')
      onSaved()
    } catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: msg(err) }) } finally { setBusy(false) }
  }
  return (
    <Modal title={member ? `Edit ${member.full_name || member.email}` : 'Add staff'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && !Object.keys(errors).some((k) => k !== 'form') && <div className="alert error" role="alert">{errors.form}</div>}
        <Field label="Full name" error={errors.full_name}>{(p) => <input {...p} className="input" placeholder="Enter the full name" value={v.full_name} onChange={(e) => setV({ ...v, full_name: e.target.value })} />}</Field>
        <Field label="Email address" error={errors.email} hint={member ? 'Fix a mistake here. They must confirm the new address before signing in again.' : 'A secure password-setup link is sent here.'}>{(p) => <input {...p} className="input" type="email" placeholder="Enter the email address" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} />}</Field>
        <Field label="Phone (optional)" error={errors.phone}>{(p) => <input {...p} className="input" type="tel" placeholder="Enter the phone number" value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />}</Field>
        <Field label="Role" error={errors.role}>{(p) => <select {...p} className="input" value={v.role} onChange={(e) => setV({ ...v, role: e.target.value })}>{roles.map(([r, l]) => <option key={r} value={r}>{l}</option>)}</select>}</Field>
        <fieldset style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14 }}><legend>Branches</legend>
          {branches.map((b) => <label key={b.id} style={{ display: 'block' }}><input type="checkbox" checked={sel.includes(b.id)} onChange={() => toggle(b.id)} /> {b.name}</label>)}
          {errors.branch_ids && <p className="err">{errors.branch_ids}</p>}
        </fieldset>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : member ? 'Save changes' : 'Send invitation'}</button>
      </form>
    </Modal>
  )
}

function Activity({ m, onClose }: { m: Member; onClose: () => void }) {
  const r = useAsync(() => api<{ action: string; object_type: string; object_id: string; created_at: string }[]>(`/staff/members/${m.id}/activity/`), [m.id])
  return (
    <Modal title={`Recent activity: ${m.full_name || m.email}`} onClose={onClose}>
      {r.error && <ErrorState message={r.error} />}
      {r.loading ? <Skeleton h={100} /> : !r.data?.length ? <Empty title="No recorded activity" /> : (
        <table className="tbl"><tbody>{r.data.map((a, i) => <tr key={i}><td>{new Date(a.created_at).toLocaleString()}</td><td>{a.action}</td><td className="muted">{a.object_type} {a.object_id}</td></tr>)}</tbody></table>)}
    </Modal>
  )
}

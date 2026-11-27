import { Download } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, api, downloadFile } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Empty, ErrorState, Field, Modal, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'
import { usePrompt } from '../../ui/dialogs'
import { useSearchParams } from 'react-router-dom'
import { BulkBar, GenerateModal, Tick } from './PayrollBulk'

export type Comp = { type: string; name: string; mode: 'fixed' | 'percent_of_basic'; amount: string }
type Structure = { id: number; employee_id: number; version: number; status: string; frequency: string; basic_salary: string; components: Comp[]; terms: string; effective_from: string; created_by: string | null }
type Employee = { id: number; name: string; email: string; role: string; branches: string[]; can_manage: boolean; current: Structure | null; pending: Structure | null }
type Period = { id: number; year: number; month: number; label: string; records: number }
type Rec = {
  id: number; period: string; status: string; employee: { id: number; name: string; role: string }; branch: string | null; basic_salary: string; gross: string; total_deductions: string; net: string
  prepared_by: string | null; approved_by: string | null; paid_by: string | null; paid_on: string | null; receipt_number: string | null; decision_note: string; payment_reference?: string
  lines?: { source: string; type: string; name: string; amount: string }[]; adjustments?: Comp[]
}
type Summary = { by_status: Record<string, { count: number; gross: string; deductions: string; net: string }>; by_branch: { branch: string; count: number; gross: string; net: string }[]; paid_net: string; committed_net: string }

const EARN = [['allowance', 'Allowance'], ['bonus', 'Bonus'], ['overtime', 'Overtime'], ['other_earning', 'Other earning']]
const DED = [['deduction', 'Deduction'], ['other_deduction', 'Other deduction']]
const TYPE_LABEL: Record<string, string> = Object.fromEntries([...EARN, ...DED, ['basic', 'Basic']])
const ROLE: Record<string, string> = { restaurant_admin: 'Administrator', manager: 'Manager', cashier: 'Cashier', kitchen: 'Kitchen', waiter: 'Waiter', waitress: 'Waitress', delivery: 'Delivery' }
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const amountRx = /^\d+(\.\d{1,2})?$/
type Rule = { name: string; kind: 'percent' | 'brackets'; base: 'gross' | 'basic' | 'taxable'; bearer: 'employee' | 'employer'; pre_tax?: boolean; enabled?: boolean; rate?: string; brackets?: { up_to: string | null; rate: string }[] }
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function CompEditor({ items, onChange, types }: { items: Comp[]; onChange: (c: Comp[]) => void; types: string[][] }) {
  const set = (i: number, patch: Partial<Comp>) => onChange(items.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  return (
    <div>
      {items.map((c, i) => (
        <div key={i} className="line-row" style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.4fr 1fr 0.8fr auto', gap: 6, marginBottom: 6 }}>
          <select className="input" aria-label="Item type" value={c.type} onChange={(e) => set(i, { type: e.target.value })}>{types.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          <input className="input" aria-label="Item name" placeholder="Name" value={c.name} maxLength={80} onChange={(e) => set(i, { name: e.target.value })} />
          <select className="input" aria-label="Amount mode" value={c.mode} onChange={(e) => set(i, { mode: e.target.value as Comp['mode'] })}><option value="fixed">Fixed amount</option><option value="percent_of_basic">% of basic</option></select>
          <input className="input" aria-label="Amount" inputMode="decimal" placeholder="0.00" value={c.amount} onChange={(e) => set(i, { amount: e.target.value })} />
          <button type="button" className="btn sm secondary" aria-label="Remove item" onClick={() => onChange(items.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <button type="button" className="btn sm secondary" onClick={() => onChange([...items, { type: types[0][0], name: '', mode: 'fixed', amount: '' }])}>+ Add item</button>
    </div>
  )
}

function validComps(items: Comp[]): string | null {
  for (const c of items) {
    if (!c.name.trim()) return 'Give every item a name.'
    if (!amountRx.test(c.amount.trim())) return 'Amounts must be numbers like 50 or 50.25.'
    if (c.mode === 'percent_of_basic' && Number(c.amount) > 100) return 'A percentage cannot exceed 100.'
  }
  return null
}

export default function Payroll() {
  useDocumentTitle('Payroll')
  const { me } = useAuth()
  const isAdmin = me?.role === 'restaurant_admin' || me?.role === 'platform_admin'
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const tab = wanted === 'runs' || wanted === 'reports' ? wanted : 'employees'
  const setTab = (next: string) => setParams({ tab: next }, { replace: true })
  return (
    <>
      <h1 className="page-title">Payroll</h1>
      <div className="toolbar" role="tablist" aria-label="Payroll sections">
        {([['employees', 'Employees and salaries'], ['runs', 'Monthly payroll'], ['reports', 'Reports']] as const).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={`btn sm ${tab === k ? '' : 'secondary'}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === 'employees' && <Employees isAdmin={isAdmin} />}
      {tab === 'runs' && <Runs isAdmin={isAdmin} />}
      {tab === 'reports' && <Reports isAdmin={isAdmin} />}
    </>
  )
}

// ---------------------------------------------------------------- employees
function Employees({ isAdmin }: { isAdmin: boolean }) {
  const prompt = usePrompt()
  const { money } = useSite()
  const toast = useToast()
  const list = useAsync(() => api<Employee[]>('/payroll/employees/'), [])
  const [edit, setEdit] = useState<Employee | null>(null)
  const [hist, setHist] = useState<Employee | null>(null)

  async function decide(s: Structure, act: 'approve' | 'reject') {
    let reason = ''
    if (act === 'reject') { reason = (await prompt({ title: 'Reject this salary change?', label: 'Reason', required: true, danger: true, confirmLabel: 'Reject' })) ?? ''; if (!reason) return }
    try { await api(`/payroll/structures/${s.id}/${act}/`, { body: { reason } }); toast(act === 'approve' ? 'Salary change approved.' : 'Salary change rejected.'); list.reload() } catch (e) { toast(msg(e)) }
  }
  if (list.error) return <ErrorState message={list.error} onRetry={list.reload} />
  return (
    <>
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.length ? <Empty title="No employees in your scope" /> : (
          <table className="tbl"><thead><tr><th>Employee</th><th>Role</th><th>Branches</th><th>Current salary</th><th>Waiting for approval</th><th /></tr></thead><tbody>
            {list.data.map((e) => (
              <tr key={e.id}>
                <td><b>{e.name}</b><div className="muted" style={{ fontSize: '.8rem' }}>{e.email}</div></td><td>{ROLE[e.role] ?? e.role}</td><td>{e.branches.join(', ') || 'All'}</td>
                <td>{e.current ? <>{money(e.current.basic_salary)} <span className="muted">basic, v{e.current.version}</span></> : <span className="badge suspended">not set</span>}</td>
                <td>{e.pending ? <><b>{money(e.pending.basic_salary)}</b> from {e.pending.effective_from}{isAdmin && e.can_manage && <span style={{ display: 'inline-flex', gap: 4, marginLeft: 8 }}><button className="btn sm" onClick={() => decide(e.pending!, 'approve')}>Approve</button><button className="btn sm danger" onClick={() => decide(e.pending!, 'reject')}>Reject</button></span>}</> : '–'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{e.can_manage ? <button className="btn sm" disabled={!!e.pending} title={e.pending ? 'A change is already waiting for approval' : ''} onClick={() => setEdit(e)}>Set salary</button> : <span className="muted">No access</span>} <button className="btn sm secondary" onClick={() => setHist(e)}>History</button></td>
              </tr>))}
          </tbody></table>)}
      </div>
      {edit && <StructureModal emp={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
      {hist && <HistoryModal emp={hist} onClose={() => setHist(null)} />}
    </>
  )
}

function StructureModal({ emp, onClose, onSaved }: { emp: Employee; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const cur = emp.current
  const [f, setF] = useState({ basic_salary: cur?.basic_salary ?? '', effective_from: '', frequency: cur?.frequency ?? 'monthly', terms: cur?.terms ?? '' })
  const [comps, setComps] = useState<Comp[]>(cur?.components ?? [])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!amountRx.test(f.basic_salary.trim())) return setErr('Enter the basic salary as a number like 1500 or 1500.50.')
    if (!f.effective_from) return setErr('Choose the date this salary starts.')
    const bad = validComps(comps)
    if (bad) return setErr(bad)
    setBusy(true); setErr('')
    try { await api('/payroll/structures/', { body: { membership_id: emp.id, ...f, components: comps } }); toast('Salary submitted for approval.'); onSaved() } catch (x) { setErr(msg(x)) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Salary: ${emp.name}`} onClose={onClose}>
      <form noValidate onSubmit={submit}>
        <p className="muted">Changes create a new version that the restaurant administrator must approve. Past payroll is never altered.</p>
        <div className="grid g2">
          <Field label="Basic salary">{(p) => <input {...p} className="input" inputMode="decimal" value={f.basic_salary} onChange={(e) => setF({ ...f, basic_salary: e.target.value })} />}</Field>
          <Field label="Starts on">{(p) => <input {...p} className="input" type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} />}</Field>
          <Field label="Pay frequency">{(p) => <select {...p} className="input" value={f.frequency} onChange={(e) => setF({ ...f, frequency: e.target.value })}><option value="monthly">Monthly</option><option value="biweekly">Every two weeks</option><option value="weekly">Weekly</option></select>}</Field>
        </div>
        <h3>Regular allowances and deductions</h3>
        <CompEditor items={comps} onChange={setComps} types={[...EARN.slice(0, 1), ...DED]} />
        <Field label="Terms (optional)">{(p) => <textarea {...p} className="input" rows={2} maxLength={2000} value={f.terms} onChange={(e) => setF({ ...f, terms: e.target.value })} />}</Field>
        {err && <p className="err" role="alert">{err}</p>}
        <button className="btn" disabled={busy}>{busy ? 'Saving…' : 'Submit for approval'}</button>
      </form>
    </Modal>
  )
}

function HistoryModal({ emp, onClose }: { emp: Employee; onClose: () => void }) {
  const { money } = useSite()
  const d = useAsync(() => api<Structure[]>('/payroll/structures/', { params: { employee: emp.id } }), [emp.id])
  return (
    <Modal title={`Salary history: ${emp.name}`} onClose={onClose}>
      {!d.data ? <Skeleton h={100} /> : !d.data.length ? <Empty title="No salary recorded yet" /> : (
        <table className="tbl"><thead><tr><th>Version</th><th>Basic</th><th>From</th><th>Status</th><th>Proposed by</th></tr></thead><tbody>
          {d.data.map((s) => <tr key={s.id}><td>v{s.version}</td><td>{money(s.basic_salary)}</td><td>{s.effective_from}</td><td><span className={`badge ${s.status === 'active' ? 'active' : ''}`}>{s.status}</span></td><td>{s.created_by ?? '–'}</td></tr>)}
        </tbody></table>)}
    </Modal>
  )
}

// ---------------------------------------------------------------- monthly runs
function Runs({ isAdmin }: { isAdmin: boolean }) {
  const { money } = useSite()
  const toast = useToast()
  const now = new Date()
  const periods = useAsync(() => api<Period[]>('/payroll/periods/'), [])
  const [params] = useSearchParams()
  const linked = Number(params.get('period')) || null
  const [sel, setSel] = useState<number | null>(linked)
  useEffect(() => { if (linked) setSel(linked) }, [linked])
  const [ticked, setTicked] = useState<Set<number>>(new Set())
  const [generating, setGenerating] = useState(false)
  const [np, setNp] = useState({ year: now.getFullYear(), month: now.getMonth() + 1 })
  const [open, setOpen] = useState<number | null>(null)
  const cur = sel ?? periods.data?.[0]?.id ?? null
  const recs = useAsync(() => (cur ? api<{ label: string; records: Rec[] }>(`/payroll/periods/${cur}/`) : Promise.resolve(null)), [cur])
  useEffect(() => { setTicked(new Set()) }, [cur])
  const rows = recs.data?.records ?? []
  const selected = rows.filter((r) => ticked.has(r.id))
  const tickOne = (id: number, on: boolean) => setTicked((now) => { const next = new Set(now); if (on) next.add(id); else next.delete(id); return next })
  const statuses = [...new Set(rows.map((r) => r.status))]
  const changed = () => { recs.reload(); periods.reload() }

  async function create() {
    try { const p = await api<Period>('/payroll/periods/', { body: np }); toast('Payroll month created.'); periods.reload(); setSel(p.id) } catch (e) { toast(msg(e)) }
  }
  return (
    <>
      <div className="toolbar">
        <select className="input" style={{ maxWidth: 200 }} aria-label="Payroll month" value={cur ?? ''} onChange={(e) => setSel(Number(e.target.value))}>
          {(periods.data ?? []).map((p) => <option key={p.id} value={p.id}>{MONTHS[p.month - 1]} {p.year} ({p.records})</option>)}
        </select>
        {cur && <button className="btn sm" onClick={() => setGenerating(true)}>Generate drafts</button>}
        <span style={{ flex: 1 }} />
        <select className="input" style={{ maxWidth: 90 }} aria-label="New month" value={np.month} onChange={(e) => setNp({ ...np, month: Number(e.target.value) })}>{MONTHS.map((n, i) => <option key={n} value={i + 1}>{n}</option>)}</select>
        <input className="input" style={{ maxWidth: 90 }} aria-label="New year" type="number" value={np.year} onChange={(e) => setNp({ ...np, year: Number(e.target.value) })} />
        <button className="btn sm secondary" onClick={create}>New month</button>
      </div>
      {recs.error && <ErrorState message={recs.error} onRetry={recs.reload} />}
      {statuses.length > 0 && (
        <div className="chips" role="group" aria-label="Select records by status" style={{ marginBottom: 10 }}>
          <span className="muted">Select:</span>
          {statuses.map((st) => <button type="button" key={st} className="chip" onClick={() => setTicked(new Set(rows.filter((r) => r.status === st).map((r) => r.id)))}>All {st} ({rows.filter((r) => r.status === st).length})</button>)}
        </div>
      )}
      {cur && <BulkBar periodId={cur} selected={selected} isAdmin={isAdmin} onClear={() => setTicked(new Set())} onDone={changed} />}
      <div className="card table-wrap">
        {!cur ? <Empty title="No payroll month yet">Create a month above, then generate drafts.</Empty> : !recs.data ? <Skeleton h={100} /> : !recs.data.records.length ? <Empty title="No records">Press “Generate drafts” and choose the employees to prepare pay for.</Empty> : (
          <table className="tbl"><thead><tr><th className="tick-col"><Tick label="Select all records" checked={rows.length > 0 && selected.length === rows.length} some={selected.length > 0} onChange={(on) => setTicked(new Set(on ? rows.map((r) => r.id) : []))} /></th><th>Employee</th><th>Branch</th><th>Gross</th><th>Deductions</th><th>Net pay</th><th>Status</th><th /></tr></thead><tbody>
            {recs.data.records.map((r) => <tr key={r.id} className={ticked.has(r.id) ? 'row-new' : ''}><td className="tick-col"><Tick label={`Select ${r.employee.name}`} checked={ticked.has(r.id)} onChange={(on) => tickOne(r.id, on)} /></td><td><b>{r.employee.name}</b></td><td>{r.branch ?? '–'}</td><td>{money(r.gross)}</td><td>{money(r.total_deductions)}</td><td><b>{money(r.net)}</b></td><td><span className={`badge ${r.status === 'paid' ? 'active' : r.status === 'rejected' || r.status === 'cancelled' ? 'suspended' : ''}`}>{r.status}</span></td><td><button className="btn sm" onClick={() => setOpen(r.id)}>Open</button></td></tr>)}
          </tbody></table>)}
      </div>
      {open !== null && <RecordModal id={open} isAdmin={isAdmin} onClose={() => setOpen(null)} onChanged={changed} />}
      {generating && cur && <GenerateModal periodId={cur} label={recs.data?.label ?? ''} roleName={(r) => ROLE[r] ?? r} onClose={() => setGenerating(false)} onDone={() => { setGenerating(false); changed() }} />}
    </>
  )
}

function RecordModal({ id, isAdmin, onClose, onChanged }: { id: number; isAdmin: boolean; onClose: () => void; onChanged: () => void }) {
  const prompt = usePrompt()
  const { money } = useSite()
  const toast = useToast()
  const d = useAsync(() => api<Rec & { period_id: number; employee: Rec['employee'] & { id: number } }>(`/payroll/records/${id}/`), [id])
  const [adj, setAdj] = useState<Comp[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [payOpen, setPayOpen] = useState(false)
  const r = d.data
  if (!r) return <Modal title="Payroll record" onClose={onClose}>{d.error ? <ErrorState message={d.error} /> : <Skeleton h={160} />}</Modal>
  const items = adj ?? r.adjustments ?? []
  const editable = ['draft', 'rejected', 'cancelled'].includes(r.status)

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true)
    try { await fn(); toast(ok); setAdj(null); d.reload(); onChanged() } catch (e) { toast(msg(e)) } finally { setBusy(false) }
  }
  const act = (a: string, body: unknown = {}) => api(`/payroll/records/${id}/${a}/`, { body })
  async function ask(a: 'reject' | 'cancel', text: string, ok: string) {
    const reason = (await prompt({ title: text.replace(/:$/, ''), label: 'Reason', required: true, multiline: true, danger: true })) ?? ''
    if (reason) void run(() => act(a, { reason }), ok)
  }
  function save() {
    const bad = validComps(items)
    if (bad) return toast(bad)
    void run(() => api(`/payroll/periods/${r!.period_id}/records/`, { body: { membership_id: r!.employee.id, adjustments: items } }), 'Draft saved.')
  }
  return (
    <Modal title={`${r.employee.name}: ${r.period}`} onClose={onClose}>
      <p><span className="badge">{r.status}</span> {r.branch ?? 'Restaurant-wide'} · prepared by {r.prepared_by ?? '–'}{r.approved_by && <> · approved by {r.approved_by}</>}{r.paid_by && <> · paid by {r.paid_by} on {r.paid_on}</>}{r.payment_reference && <> · reference <code>{r.payment_reference}</code></>}</p>
      {r.decision_note && <p className="err">Note: {r.decision_note}</p>}
      <table className="tbl"><tbody>
        {(r.lines ?? []).map((l, i) => <tr key={i}><td>{l.name} <span className="muted">({TYPE_LABEL[l.type] ?? l.type}{l.source === 'adjustment' ? ', this month only' : ''})</span></td><td style={{ textAlign: 'right' }}>{['deduction', 'other_deduction'].includes(l.type) ? '−' : ''}{money(l.amount)}</td></tr>)}
        <tr><td><b>Gross</b></td><td style={{ textAlign: 'right' }}><b>{money(r.gross)}</b></td></tr>
        <tr><td><b>Deductions</b></td><td style={{ textAlign: 'right' }}><b>{money(r.total_deductions)}</b></td></tr>
        <tr><td><b>Net pay</b></td><td style={{ textAlign: 'right' }}><b>{money(r.net)}</b></td></tr>
      </tbody></table>
      {editable && (
        <>
          <h3 style={{ marginTop: 14 }}>This month’s extras (overtime, bonus, deductions)</h3>
          <CompEditor items={items} onChange={setAdj} types={[...EARN.slice(1), ...DED]} />
          <button className="btn sm" style={{ marginTop: 8 }} disabled={busy} onClick={save}>Save draft</button>
        </>
      )}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 14 }}>
        {r.status === 'draft' && <button className="btn" disabled={busy || adj !== null} title={adj ? 'Save your changes first' : ''} onClick={() => run(() => act('submit'), 'Submitted for approval.')}>Submit for approval</button>}
        {r.status === 'submitted' && isAdmin && <><button className="btn" disabled={busy} onClick={() => run(() => act('approve'), 'Approved.')}>Approve</button><button className="btn danger" disabled={busy} onClick={() => ask('reject', 'Reason for rejecting:', 'Rejected.')}>Reject</button></>}
        {r.status === 'submitted' && !isAdmin && <span className="muted">Waiting for the administrator to approve.</span>}
        {r.status === 'approved' && <button className="btn" disabled={busy} onClick={() => setPayOpen(true)}>Record payment</button>}
        {['draft', 'submitted', 'approved', 'rejected'].includes(r.status) && <button className="btn secondary" disabled={busy} onClick={() => ask('cancel', 'Reason for cancelling this record:', 'Cancelled.')}>Cancel record</button>}
        {r.status === 'paid' && <button className="btn" onClick={() => downloadFile(`/payroll/records/${id}/pdf/`, `${r.receipt_number}.pdf`).catch(() => toast('Could not download the PDF.'))}><Download size={16} aria-hidden /> Receipt {r.receipt_number}</button>}
      </div>
      {payOpen && <PayModal id={id} net={money(r.net)} onClose={() => setPayOpen(false)} onPaid={() => { setPayOpen(false); d.reload(); onChanged() }} />}
    </Modal>
  )
}

function PayModal({ id, net, onClose, onPaid }: { id: number; net: string; onClose: () => void; onPaid: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({ method: 'bank_transfer', reference: '', paid_on: new Date().toISOString().slice(0, 10) })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [key] = useState(() => crypto.randomUUID()) // one key per dialog so a double-click cannot pay twice
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setErr('')
    try { await api(`/payroll/records/${id}/pay/`, { body: f, headers: { 'Idempotency-Key': key } }); toast('Payment recorded.'); onPaid() } catch (x) { setErr(msg(x)) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Record payment of ${net}`} onClose={onClose}>
      <form noValidate onSubmit={submit}>
        <p className="muted">This records that you paid the employee outside the system. It cannot be undone.</p>
        <Field label="Method">{(p) => <select {...p} className="input" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}><option value="bank_transfer">Bank transfer</option><option value="mobile_money">Mobile money</option><option value="cash">Cash</option><option value="other">Other</option></select>}</Field>
        <Field label="Your own reference (optional)" hint="Leave empty and the system generates one, e.g. PAY-202611-000001.">{(p) => <input {...p} className="input" maxLength={80} placeholder="Generated automatically" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} />}</Field>
        <Field label="Paid on">{(p) => <input {...p} className="input" type="date" max={new Date().toISOString().slice(0, 10)} value={f.paid_on} onChange={(e) => setF({ ...f, paid_on: e.target.value })} />}</Field>
        {err && <p className="err" role="alert">{err}</p>}
        <button className="btn" disabled={busy}>{busy ? 'Recording…' : 'Confirm payment'}</button>
      </form>
    </Modal>
  )
}

// ---------------------------------------------------------------- reports
function Reports({ isAdmin }: { isAdmin: boolean }) {
  const { money } = useSite()
  const toast = useToast()
  const [year, setYear] = useState(new Date().getFullYear())
  const [month, setMonth] = useState('')
  const d = useAsync(() => api<Summary>('/payroll/summary/', { params: { year, month } }), [year, month])
  const settings = useAsync(() => (isAdmin ? api<{ allow_admin_self_approval: boolean; tax_rules: Rule[] }>('/payroll/settings/') : Promise.resolve(null)), [isAdmin])
  async function toggle(v: boolean) {
    try { await api('/payroll/settings/', { method: 'PATCH', body: { allow_admin_self_approval: v } }); toast('Setting saved.'); settings.reload() } catch (e) { toast(msg(e)) }
  }
  return (
    <>
      <div className="toolbar">
        <input className="input" style={{ maxWidth: 100 }} type="number" aria-label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))} />
        <select className="input" style={{ maxWidth: 140 }} aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)}><option value="">Whole year</option>{MONTHS.map((n, i) => <option key={n} value={i + 1}>{n}</option>)}</select>
        <button className="btn sm secondary" onClick={() => downloadFile(`/payroll/export.csv?year=${year}${month ? `&month=${month}` : ''}`, `payroll-${year}${month ? `-${month}` : ''}.csv`).catch(() => toast('Export failed.'))}><Download size={16} aria-hidden /> CSV</button>
      </div>
      {d.error && <ErrorState message={d.error} onRetry={d.reload} />}
      {!d.data ? <Skeleton h={120} /> : (
        <>
          <div className="grid g3" style={{ marginBottom: 12 }}>
            <div className="card"><div className="muted">Paid out</div><b style={{ fontSize: '1.4rem' }}>{money(d.data.paid_net)}</b></div>
            <div className="card"><div className="muted">Approved or paid (committed)</div><b style={{ fontSize: '1.4rem' }}>{money(d.data.committed_net)}</b></div>
            <div className="card"><div className="muted">Awaiting approval</div><b style={{ fontSize: '1.4rem' }}>{d.data.by_status.submitted.count}</b></div>
          </div>
          <div className="card table-wrap">
            <table className="tbl"><thead><tr><th>Status</th><th>Records</th><th>Gross</th><th>Deductions</th><th>Net</th></tr></thead><tbody>
              {Object.entries(d.data.by_status).filter(([, v]) => v.count > 0).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.count}</td><td>{money(v.gross)}</td><td>{money(v.deductions)}</td><td>{money(v.net)}</td></tr>)}
            </tbody></table>
          </div>
          {d.data.by_branch.length > 0 && <div className="card table-wrap" style={{ marginTop: 12 }}><table className="tbl"><thead><tr><th>Branch</th><th>Records</th><th>Gross</th><th>Net</th></tr></thead><tbody>{d.data.by_branch.map((b) => <tr key={b.branch}><td>{b.branch}</td><td>{b.count}</td><td>{money(b.gross)}</td><td>{money(b.net)}</td></tr>)}</tbody></table></div>}
        </>
      )}
      {isAdmin && settings.data && <TaxRules rules={settings.data.tax_rules} onSaved={settings.reload} />}
      {isAdmin && settings.data && (
        <div className="card" style={{ marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Approval policy</h3>
          <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <input type="checkbox" checked={settings.data.allow_admin_self_approval} onChange={(e) => toggle(e.target.checked)} />
            <span>Let the administrator prepare, approve, pay and handle their own pay alone. Leave this off if there is more than one person who can approve. It is recorded in the audit log.</span>
          </label>
        </div>
      )}
    </>
  )
}


const bracketsToText = (b?: Rule['brackets']) => (b ?? []).map((x) => `${x.up_to ?? 'rest'} ${Number(x.rate)}`).join('\n')
function textToBrackets(t: string): Rule['brackets'] {
  return t.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const [u, r] = l.split(/[\s=:]+/); return { up_to: /^(rest|more|above|open)$/i.test(u) ? null : u, rate: r } })
}

/** Statutory deductions (income tax, pension...) applied to every payroll record when it is prepared. The restaurant is responsible for the rates. */
function TaxRules({ rules, onSaved }: { rules: Rule[]; onSaved: () => void }) {
  const toast = useToast()
  const [list, setList] = useState<(Rule & { text: string })[]>(() => rules.map((r) => ({ ...r, text: bracketsToText(r.brackets) })))
  const [busy, setBusy] = useState(false)
  const set = (i: number, patch: Partial<Rule & { text: string }>) => setList(list.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  async function save() {
    const payload = list.map(({ text, ...r }) => (r.kind === 'brackets' ? { ...r, brackets: textToBrackets(text), rate: undefined } : { ...r, brackets: undefined }))
    setBusy(true)
    try { await api('/payroll/settings/', { method: 'PATCH', body: { tax_rules: payload } }); toast('Statutory rules saved. They apply to payroll prepared from now on.'); onSaved() } catch (e) { toast(msg(e)) } finally { setBusy(false) }
  }
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Tax and pension rules</h3>
      <p className="muted">Rules are applied automatically to each payroll record when it is prepared and are frozen in it. <b>You are responsible for entering the rates required by your country’s law</b>; the system does not know them. Employer contributions are a cost to the restaurant on top of gross pay and are not deducted from the employee.</p>
      {!list.length && <p className="muted">No rules: only the deductions you enter by hand apply.</p>}
      {list.map((r, i) => (
        <div key={i} className="card flat" style={{ marginBottom: 10, padding: 14 }}>
          <div className="grid g3">
            <Field label="Name">{(p) => <input {...p} className="input" maxLength={60} value={r.name} onChange={(e) => set(i, { name: e.target.value })} />}</Field>
            <Field label="Type">{(p) => <select {...p} className="input" value={r.kind} onChange={(e) => set(i, { kind: e.target.value as Rule['kind'] })}><option value="percent">Flat percentage</option><option value="brackets">Progressive brackets</option></select>}</Field>
            <Field label="Calculated on">{(p) => <select {...p} className="input" value={r.base} onChange={(e) => set(i, { base: e.target.value as Rule['base'] })}><option value="gross">Gross pay</option><option value="basic">Basic salary</option><option value="taxable">Taxable pay (gross minus pre-tax contributions)</option></select>}</Field>
            <Field label="Paid by">{(p) => <select {...p} className="input" value={r.bearer} onChange={(e) => set(i, { bearer: e.target.value as Rule['bearer'], pre_tax: e.target.value === 'employer' ? false : r.pre_tax })}><option value="employee">Employee (deducted)</option><option value="employer">Employer (extra cost)</option></select>}</Field>
            {r.kind === 'percent' && <Field label="Rate (%)">{(p) => <input {...p} className="input" inputMode="decimal" value={r.rate ?? ''} onChange={(e) => set(i, { rate: e.target.value })} />}</Field>}
          </div>
          {r.kind === 'brackets' && <Field label="Brackets (one per line: upper limit, then rate %; use “rest” for the last)">{(p) => <textarea {...p} className="input" rows={4} placeholder={'500 0\n1500 10\nrest 25'} value={r.text} onChange={(e) => set(i, { text: e.target.value })} />}</Field>}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            {r.bearer === 'employee' && <label><input type="checkbox" checked={!!r.pre_tax} onChange={(e) => set(i, { pre_tax: e.target.checked })} /> Reduces taxable pay (e.g. employee pension)</label>}
            <label><input type="checkbox" checked={r.enabled !== false} onChange={(e) => set(i, { enabled: e.target.checked })} /> Active</label>
            <button type="button" className="btn sm danger" onClick={() => setList(list.filter((_, j) => j !== i))}>Remove</button>
          </div>
        </div>))}
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" className="btn secondary" disabled={list.length >= 10} onClick={() => setList([...list, { name: '', kind: 'percent', base: 'gross', bearer: 'employee', rate: '', text: '', enabled: true }])}>+ Add rule</button>
        <button type="button" className="btn" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save rules'}</button>
      </div>
    </div>
  )
}

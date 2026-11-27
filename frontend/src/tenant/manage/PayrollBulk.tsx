// Working on many employees at once: choose who gets a draft, submit / approve / reject / cancel selected records, and pay them together.
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiError, api } from '../../lib/api'
import { Empty, ErrorState, Field, Modal, SearchInput, Skeleton, Spinner, useAsync, useToast } from '../../ui/kit'
import { useConfirm, usePrompt } from '../../ui/dialogs'
import { useSite } from '../SiteContext'
import { eligibleFor, type BulkAction, type BulkRecord, type BulkResult } from './payrollRules'

const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const people = (n: number) => `${n} employee${n === 1 ? '' : 's'}`

/** A checkbox that can also show "some, not all". */
export function Tick({ checked, some = false, onChange, label, disabled }: { checked: boolean; some?: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = some && !checked }, [some, checked])
  return <input ref={ref} type="checkbox" className="tick" checked={checked} disabled={disabled} aria-label={label} onChange={(e) => onChange(e.target.checked)} />
}

type Candidate = { id: number; name: string; email: string; role: string; branches: string[]; eligible: boolean; reason: string }

/** "Generate drafts": pick the employees (everyone who is due is ticked to begin with). */
export function GenerateModal({ periodId, label, roleName, onClose, onDone }: { periodId: number; label: string; roleName: (r: string) => string; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const list = useAsync(() => api<Candidate[]>(`/payroll/periods/${periodId}/candidates/`), [periodId])
  const [picked, setPicked] = useState<Set<number> | null>(null)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const eligible = useMemo(() => (list.data ?? []).filter((c) => c.eligible), [list.data])
  const chosen = picked ?? new Set(eligible.map((c) => c.id))
  const shown = (list.data ?? []).filter((c) => `${c.name} ${c.email} ${c.branches.join(' ')}`.toLowerCase().includes(q.toLowerCase()))
  const toggle = (id: number, on: boolean) => { const next = new Set(chosen); if (on) next.add(id); else next.delete(id); setPicked(next) }
  const count = eligible.filter((c) => chosen.has(c.id)).length

  async function generate() {
    setBusy(true)
    try {
      const r = await api<{ created: number; skipped: number }>(`/payroll/periods/${periodId}/generate/`, { body: { membership_ids: eligible.filter((c) => chosen.has(c.id)).map((c) => c.id) } })
      toast(`${r.created} draft${r.created === 1 ? '' : 's'} created${r.skipped ? `, ${r.skipped} skipped` : ''}.`)
      onDone()
    } catch (e) { toast(msg(e)) } finally { setBusy(false) }
  }

  return (
    <Modal title={`Generate drafts: ${label}`} onClose={onClose}>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {!list.data ? !list.error && <Skeleton h={160} /> : !list.data.length ? <Empty title="No employees in your scope" /> : (
        <>
          <p className="muted">Choose who gets a draft for this month. People without an approved salary, or who already have a record, cannot be chosen.</p>
          <SearchInput value={q} onChange={setQ} placeholder="Name, email or branch" label="Search employees" />
          <label className="pick-row all">
            <Tick label="Select all who can be chosen" checked={eligible.length > 0 && count === eligible.length} some={count > 0} disabled={!eligible.length} onChange={(on) => setPicked(new Set(on ? eligible.map((c) => c.id) : []))} />
            <b>Select all ({eligible.length})</b>
          </label>
          <div className="pick-list">
            {shown.map((c) => (
              <label className={`pick-row ${c.eligible ? '' : 'off'}`} key={c.id}>
                <Tick label={`Select ${c.name}`} checked={c.eligible && chosen.has(c.id)} disabled={!c.eligible} onChange={(on) => toggle(c.id, on)} />
                <span><b>{c.name}</b><small className="muted">{[roleName(c.role), c.branches.join(', ')].filter(Boolean).join(' · ')}</small>{!c.eligible && <small className="why">{c.reason}</small>}</span>
              </label>
            ))}
          </div>
          <button className="btn" style={{ width: '100%', marginTop: 12 }} disabled={busy || !count} onClick={() => void generate()}>{busy ? <Spinner /> : `Generate ${count} draft${count === 1 ? '' : 's'}`}</button>
        </>
      )}
    </Modal>
  )
}

const LABEL: Record<BulkAction, string> = { submit: 'Submit for approval', approve: 'Approve', reject: 'Reject', pay: 'Pay and record', cancel: 'Cancel records' }
const DONE: Record<BulkAction, string> = { submit: 'submitted for approval', approve: 'approved', reject: 'rejected', pay: 'paid and recorded', cancel: 'cancelled' }

/** The bar that appears when records are ticked. Each button shows how many of the ticked records it applies to. */
export function BulkBar({ periodId, selected, isAdmin, onClear, onDone }: { periodId: number; selected: BulkRecord[]; isAdmin: boolean; onClear: () => void; onDone: () => void }) {
  const toast = useToast()
  const confirm = useConfirm()
  const prompt = usePrompt()
  const { money } = useSite()
  const [busy, setBusy] = useState<BulkAction | null>(null)
  const [paying, setPaying] = useState<BulkRecord[] | null>(null)
  const [result, setResult] = useState<{ action: BulkAction; data: BulkResult } | null>(null)
  const total = (rows: BulkRecord[]) => money(rows.reduce((sum, r) => sum + Number(r.net), 0))

  async function send(action: BulkAction, rows: BulkRecord[], extra: Record<string, string> = {}, key: string = crypto.randomUUID()) {
    setBusy(action)
    try {
      const data = await api<BulkResult>(`/payroll/periods/${periodId}/bulk/`, { body: { action, record_ids: rows.map((r) => r.id), ...extra }, headers: { 'Idempotency-Key': key } })
      if (data.failed.length || action === 'pay') setResult({ action, data })
      else toast(`${data.done.length} record${data.done.length === 1 ? '' : 's'} ${DONE[action]}.`)
      onClear(); onDone()
      return true
    } catch (e) { toast(msg(e)); return false } finally { setBusy(null) }
  }
  async function run(action: BulkAction) {
    const rows = eligibleFor(action, selected, isAdmin)
    if (!rows.length) return
    if (action === 'pay') return setPaying(rows)
    if (action === 'reject' || action === 'cancel') {
      const reason = (await prompt({ title: `${LABEL[action]} for ${people(rows.length)}?`, label: 'Reason', required: true, multiline: true, danger: true })) ?? ''
      if (reason) await send(action, rows, { reason })
      return
    }
    if (await confirm({ title: `${LABEL[action]}: ${people(rows.length)}?`, message: `Total net pay ${total(rows)}.`, confirmLabel: LABEL[action] })) await send(action, rows)
  }

  return (
    <>
      {selected.length > 0 && (
        <div className="bulk-bar" role="region" aria-label="Actions for the selected records">
          <b>{selected.length} selected</b><span className="muted">{total(selected)}</span>
          <span className="bulk-actions">
            {(['submit', 'approve', 'pay', 'reject', 'cancel'] as BulkAction[]).map((a) => {
              const n = eligibleFor(a, selected, isAdmin).length
              if (!n) return null
              return <button key={a} className={`btn sm ${a === 'reject' ? 'danger' : a === 'cancel' ? 'secondary' : ''}`} disabled={!!busy} onClick={() => void run(a)}>{busy === a ? <Spinner /> : `${LABEL[a]} (${n})`}</button>
            })}
          </span>
          <button className="btn sm ghost" onClick={onClear}>Clear</button>
        </div>
      )}
      {paying && <BulkPayModal rows={paying} onClose={() => setPaying(null)} onPay={async (extra, key) => { if (await send('pay', paying, extra, key)) setPaying(null) }} />}
      {result && <ResultModal action={result.action} data={result.data} onClose={() => setResult(null)} />}
    </>
  )
}

function BulkPayModal({ rows, onClose, onPay }: { rows: BulkRecord[]; onClose: () => void; onPay: (extra: Record<string, string>, key: string) => Promise<void> }) {
  const { money } = useSite()
  const [method, setMethod] = useState('bank_transfer')
  const [paidOn, setPaidOn] = useState(today())
  const [busy, setBusy] = useState(false)
  // one key per choice of method and date: pressing twice, or retrying after a lost connection, can never pay twice
  const key = useMemo(() => crypto.randomUUID(), [method, paidOn]) // eslint-disable-line react-hooks/exhaustive-deps
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    await onPay({ method, paid_on: paidOn }, key)
    setBusy(false)
  }
  return (
    <Modal title={`Record payment for ${people(rows.length)}`} onClose={onClose}>
      <form noValidate onSubmit={submit}>
        <p className="muted">This records that you paid these employees outside the system. It cannot be undone. A payment reference is generated automatically for each one.</p>
        <div className="pick-list">{rows.map((r) => <div className="list-row" key={r.id}><span>{r.employee.name}</span><b>{money(r.net)}</b></div>)}</div>
        <p style={{ fontSize: '1.1rem' }}><b>Total: {money(rows.reduce((s, r) => s + Number(r.net), 0))}</b></p>
        <Field label="Method">{(p) => <select {...p} className="input" value={method} onChange={(e) => setMethod(e.target.value)}><option value="bank_transfer">Bank transfer</option><option value="mobile_money">Mobile money</option><option value="cash">Cash</option><option value="other">Other</option></select>}</Field>
        <Field label="Paid on">{(p) => <input {...p} className="input" type="date" max={today()} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />}</Field>
        <button className="btn" style={{ width: '100%' }} disabled={busy || !paidOn}>{busy ? <Spinner /> : `Confirm ${rows.length} payment${rows.length === 1 ? '' : 's'}`}</button>
      </form>
    </Modal>
  )
}

function ResultModal({ action, data, onClose }: { action: BulkAction; data: BulkResult; onClose: () => void }) {
  const { money } = useSite()
  return (
    <Modal title={`${data.done.length} ${DONE[action]}${data.failed.length ? `, ${data.failed.length} not` : ''}`} onClose={onClose}>
      {action === 'pay' && data.done.length > 0 && (
        <div className="table-wrap"><table className="tbl"><thead><tr><th>Employee</th><th>Net pay</th><th>Reference</th><th>Receipt</th></tr></thead><tbody>
          {data.done.map((d) => <tr key={d.id}><td>{d.name}</td><td>{money(d.net)}</td><td><code>{d.reference}</code></td><td>{d.receipt_number}</td></tr>)}
        </tbody></table></div>
      )}
      {data.failed.length > 0 && <><h3>Not done</h3><ul className="feed">{data.failed.map((f) => <li key={f.id}><span className="dot" /><span><b>{f.name}</b><br /><small className="muted">{f.reason}</small></span></li>)}</ul></>}
      <button className="btn" onClick={onClose}>Close</button>
    </Modal>
  )
}

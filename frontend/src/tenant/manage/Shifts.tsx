import { useState } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { Empty, ErrorState, Modal, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'
import type { ShiftData } from './Cashier'
import { usePrompt } from '../../ui/dialogs'

type Adj = { id: number; shift_id: number; kind: string; amount: string; reason: string; status: string; requested_by: string }
type Report = ShiftData & {
  payments: { reference: string; order_number: string; method: string; amount: string; received: string | null; change: string; paid_at: string }[]
  refunds: { reference: string; amount: string; reason: string }[]
  adjustments: (Adj & { decided_by: string | null; decision_note: string })[]
}

/** Manager/admin view: branch shifts, approvals of cash adjustments, and shift reports. */
export default function Shifts() {
  const prompt = usePrompt()
  useDocumentTitle('Shifts')
  const { money } = useSite()
  const toast = useToast()
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const list = useAsync(() => api<Page<ShiftData>>('/cashier/shifts/', { params: { status } }), [status])
  const pending = useAsync(() => api<Adj[]>('/cashier/adjustments/pending/'), [])

  async function decide(a: Adj, approve: boolean) {
    const answer = approve ? '' : await prompt({ title: 'Reject this adjustment?', label: 'Reason (optional)', danger: true, confirmLabel: 'Reject' })
    if (answer === null) return
    const note = answer
    try { await api(`/cashier/adjustments/${a.id}/decide/`, { body: { approve, note } }); toast(approve ? 'Approved.' : 'Rejected.'); pending.reload(); list.reload() } catch (e) { toast(e instanceof ApiError ? e.message : 'Failed.') }
  }
  return (
    <>
      <h1 className="page-title">Shifts</h1>
      <h2 style={{ fontSize: '1.2rem' }}>Cash adjustments waiting for approval</h2>
      {pending.error && <ErrorState message={pending.error} onRetry={pending.reload} />}
      <div className="card table-wrap" style={{ marginBottom: 24 }}>
        {pending.loading ? <Skeleton h={50} /> : !pending.data?.length ? <Empty title="Nothing waiting" /> : (
          <table className="tbl"><thead><tr><th>Cashier</th><th>Type</th><th>Amount</th><th>Reason</th><th /></tr></thead><tbody>
            {pending.data.map((a) => <tr key={a.id}><td>{a.requested_by}</td><td>{a.kind === 'cash_in' ? 'Cash in' : 'Cash out'}</td><td>{money(a.amount)}</td><td>{a.reason}</td>
              <td style={{ display: 'flex', gap: 6 }}><button className="btn sm" onClick={() => decide(a, true)}>Approve</button><button className="btn sm danger" onClick={() => decide(a, false)}>Reject</button></td></tr>)}
          </tbody></table>)}
      </div>
      <div className="toolbar"><h2 style={{ fontSize: '1.2rem', margin: 0, flex: 1 }}>Shift history</h2>
        <select className="input" style={{ maxWidth: 170 }} aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option><option value="open">Open</option><option value="closed">Closed</option></select></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={90} /> : !list.data?.results.length ? <Empty title="No shifts yet" /> : (
          <table className="tbl"><thead><tr><th>Cashier</th><th>Branch</th><th>Opened</th><th>Status</th><th>Expected</th><th>Counted</th><th>Variance</th><th /></tr></thead><tbody>
            {list.data.results.map((s) => <tr key={s.id}><td>{s.cashier}</td><td>{s.branch_name}</td><td>{new Date(s.opened_at).toLocaleString()}</td><td><span className={`badge ${s.status === 'open' ? 'active' : ''}`}>{s.status}</span></td>
              <td>{s.expected_cash ? money(s.expected_cash) : '–'}</td><td>{s.actual_cash ? money(s.actual_cash) : '–'}</td>
              <td style={{ color: s.variance && Number(s.variance) !== 0 ? 'var(--danger)' : undefined }}>{s.variance ? money(s.variance) : '–'}</td><td><button className="btn sm secondary" onClick={() => setOpen(s.id)}>Report</button></td></tr>)}
          </tbody></table>)}
      </div>
      {open !== null && <ReportModal id={open} onClose={() => setOpen(null)} />}
    </>
  )
}

function ReportModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { money } = useSite()
  const r = useAsync(() => api<Report>(`/cashier/shifts/${id}/`), [id])
  return (
    <Modal title="Shift report" onClose={onClose}>
      {r.error && <ErrorState message={r.error} />}
      {!r.data ? <Skeleton h={120} /> : (
        <>
          <p><b>{r.data.cashier}</b> · {r.data.branch_name} · {new Date(r.data.opened_at).toLocaleString()}{r.data.closed_at && ` → ${new Date(r.data.closed_at).toLocaleString()}`}</p>
          <table className="tbl"><tbody>
            <tr><td>Opening cash</td><td>{money(r.data.opening_cash)}</td></tr>
            <tr><td>Cash sales</td><td>{money(r.data.totals!.cash_sales)}</td></tr>
            <tr><td>Cash refunds</td><td>−{money(r.data.totals!.cash_refunds)}</td></tr>
            <tr><td>Cash in / out (approved)</td><td>+{money(r.data.totals!.cash_in)} / −{money(r.data.totals!.cash_out)}</td></tr>
            <tr><td><b>Expected</b></td><td><b>{money(r.data.expected_cash ?? r.data.totals!.cash_sales)}</b></td></tr>
            {r.data.status === 'closed' && <><tr><td>Counted</td><td>{money(r.data.actual_cash ?? '0')}</td></tr><tr><td><b>Variance</b></td><td><b>{money(r.data.variance ?? '0')}</b></td></tr></>}
            <tr><td className="muted">Mobile money sales</td><td className="muted">{money(r.data.totals!.mobile_money_sales)}</td></tr>
          </tbody></table>
          {r.data.close_notes && <p>Cashier&apos;s note: <i>{r.data.close_notes}</i></p>}
          <h3>Cash transactions ({r.data.payments.length})</h3>
          {r.data.payments.map((p) => <p key={p.reference} className="muted" style={{ margin: '2px 0' }}>{new Date(p.paid_at).toLocaleTimeString()} · {p.order_number} · {money(p.amount)}{p.received ? ` (received ${money(p.received)}, change ${money(p.change)})` : ''}</p>)}
          {r.data.refunds.length > 0 && <><h3>Refunds</h3>{r.data.refunds.map((x) => <p key={x.reference} className="muted">−{money(x.amount)} · {x.reason}</p>)}</>}
        </>
      )}
    </Modal>
  )
}

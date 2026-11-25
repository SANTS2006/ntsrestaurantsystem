import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../lib/auth'
import { ApiError, api, type Page } from '../../lib/api'
import { Drawer, Empty, ErrorState, PageHeader, Pager, SearchInput, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { StatusBadge, type OrderRow } from '../account/pages'
import { useSite } from '../SiteContext'
import { usePrompt } from '../../ui/dialogs'

type StaffDetail = OrderRow & {
  contact_phone: string; contact_email: string; customer_notes: string; delivery_address: Record<string, string>
  subtotal: string; tax_total: string; delivery_fee: string; cancellation_reason: string
  items: { product_name: string; variation_name: string; quantity: number; line_total: string; addons: { name: string; quantity: number }[]; instructions: string }[]
  history: { status_label: string; note: string; created_at: string; actor_role: string }[]
  allowed_transitions: { status: string; label: string }[]
  total: string; amount_paid: string; payment_method: string; payment_status: string
  payments: { id: number; method: string; status: string; amount: string; receipt_id: number | null }[]
}

const REFRESH_MS = 15000

export default function Orders() {
  useDocumentTitle('Orders')
  const { money } = useSite()
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [active, setActive] = useState(true)
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number | null>(null)
  const list = useAsync(() => api<Page<OrderRow>>('/orders/manage/', { params: { status, q, page, active: active && !status ? 1 : undefined } }), [status, q, page, active])
  const { reload } = list

  // Keep the board fresh while the tab is visible (push updates arrive with the realtime phase).
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden) reload() }, REFRESH_MS)
    return () => clearInterval(t)
  }, [reload])

  const statuses = useAsync(() => api<{ status: string; label: string }[]>('/orders/manage/statuses/'), [])
  return (
    <>
      <PageHeader title="Orders" subtitle="Every order across your branches, updated automatically">
        <button className="btn sm secondary" onClick={reload}>Refresh</button>
      </PageHeader>
      <div className="toolbar">
        <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Order number, name or phone" label="Search orders" />
        <div className="chips" role="group" aria-label="Filter by status">
          <button className="chip" aria-pressed={!status && active} onClick={() => { setStatus(''); setActive(true); setPage(1) }}>Open</button>
          <button className="chip" aria-pressed={!status && !active} onClick={() => { setStatus(''); setActive(false); setPage(1) }}>All</button>
          {(statuses.data ?? []).filter((s) => ['awaiting_payment', 'received', 'preparing', 'ready_for_pickup', 'out_for_delivery', 'completed', 'cancelled'].includes(s.status)).map((s) => <button key={s.status} className="chip" aria-pressed={status === s.status} onClick={() => { setStatus(status === s.status ? '' : s.status); setPage(1) }}>{s.label}</button>)}
        </div>
      </div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title="No orders to show" /> : (
          <table className="tbl"><thead><tr><th>Order</th><th>Customer</th><th>Branch</th><th>Type</th><th>Status</th><th>Total</th><th>Placed</th><th /></tr></thead><tbody>
            {list.data.results.map((o) => (
              <tr key={o.id}><td>{o.number}{o.cancellation_requested && <span className="badge suspended" style={{ marginLeft: 6 }}>cancel requested</span>}</td><td>{o.contact_name}</td><td>{o.branch_name}</td><td>{o.fulfilment}</td>
                <td><StatusBadge s={o.status} label={o.status_label} /></td><td>{money(o.total)}</td><td>{new Date(o.created_at).toLocaleString()}</td><td><button className="btn sm" onClick={() => setOpen(o.id)}>Open</button></td></tr>
            ))}
          </tbody></table>
        )}
      </div>
      {list.data && <Pager page={page} hasPrev={!!list.data.previous} hasNext={!!list.data.next} onPage={setPage} total={list.data.count} />}
      {open !== null && <OrderModal id={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </>
  )
}

function OrderModal({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const prompt = usePrompt()
  const { money } = useSite()
  const toast = useToast()
  const [o, setO] = useState<StaffDetail | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { me } = useAuth()
  const canRefund = ['restaurant_admin', 'manager', 'platform_admin'].includes(me?.role ?? '')
  const load = useCallback(() => api<StaffDetail>(`/orders/manage/${id}/`).then(setO, (e) => setError(e instanceof ApiError ? e.message : 'Could not load the order.')), [id])
  useEffect(() => { void load() }, [load])

  async function recordCash() {
    if (!o) return
    const due = (Number(o.total) - Number(o.amount_paid)).toFixed(2)
    const got = await prompt({ title: 'Record cash payment', message: `Amount due ${due}.`, label: 'Cash received', defaultValue: due, required: true, inputMode: 'decimal', confirmLabel: 'Record payment' })
    if (got === null) return
    setBusy(true)
    try { const r = await api<{ change_given: string }>('/payments/cash/', { body: { order_id: id, amount_received: got.trim() }, headers: { 'Idempotency-Key': crypto.randomUUID() } }); toast(`Payment recorded. Change to give: ${r.change_given}`); await load(); onChanged() }
    catch (e) { toast(e instanceof ApiError ? (e.fieldErrors().amount_received ?? e.fieldErrors().order_id ?? e.message) : 'Failed.') } finally { setBusy(false) }
  }
  async function refund(paymentId: number, max: string) {
    const amount = await prompt({ title: 'Refund payment', message: `Up to ${max}.`, label: 'Refund amount', defaultValue: max, required: true, inputMode: 'decimal', confirmLabel: 'Continue' })
    if (amount === null) return
    const reasonAsked = await prompt({ title: 'Reason for the refund', label: 'Reason', required: true, multiline: true, confirmLabel: 'Continue' })
    if (reasonAsked === null) return
    const reason = reasonAsked
    if (reason.length < 3) return toast('A reason is required.')
    let manual_reference = ''
    if (o?.payments.find((p) => p.id === paymentId)?.method === 'mobile_money') {
      // Monime has no refund API: the money is returned from the Monime dashboard and its reference is recorded here
      manual_reference = (await prompt({ title: 'Record the Monime refund', message: 'Mobile money refunds are made in the Monime dashboard. Refund the customer there first, then enter the refund reference to record it.', label: 'Refund reference', required: true })) ?? ''
      if (manual_reference.length < 3) return toast('Enter the reference of the refund you made in the Monime dashboard.')
    }
    setBusy(true)
    try { await api(`/payments/${paymentId}/refund/`, { body: { amount: amount.trim(), reason, manual_reference }, headers: { 'Idempotency-Key': crypto.randomUUID() } }); toast('Refund recorded.'); await load(); onChanged() }
    catch (e) { toast(e instanceof ApiError ? (e.fieldErrors().amount ?? e.fieldErrors().manual_reference ?? e.message) : 'Failed.') } finally { setBusy(false) }
  }

  async function move(to: string, label: string) {
    let note = ''
    if (to === 'cancelled') {
      note = (await prompt({ title: 'Cancel this order?', message: 'The customer will see the reason.', label: 'Reason', required: true, multiline: true, danger: true, confirmLabel: 'Cancel order' })) ?? ''
      if (!note) return
    }
    setBusy(true)
    try { setO(await api<StaffDetail>(`/orders/manage/${id}/transition/`, { body: { status: to, note } })); toast(`Order moved to ${label}.`); onChanged() } catch (e) { toast(e instanceof ApiError ? e.message : 'Failed.'); void load() } finally { setBusy(false) }
  }
  return (
    <Drawer title={o ? `Order ${o.number}` : 'Order'} onClose={onClose}>
      {error && <div className="alert error">{error}</div>}
      {!o ? !error && <Skeleton h={160} /> : (
        <>
          <p><StatusBadge s={o.status} label={o.status_label} /> <span className="muted">{o.fulfilment} · {o.branch_name} · {o.payment_method === 'cash' ? 'cash' : o.payment_method} ({o.payment_status})</span></p>
          {o.cancellation_requested && <div className="alert warn">The customer asked to cancel: {o.cancellation_reason}</div>}
          <p><b>{o.contact_name}</b> · <a href={`tel:${o.contact_phone}`}>{o.contact_phone}</a>{o.contact_email && <> · {o.contact_email}</>}</p>
          {o.fulfilment === 'delivery' && <p>Deliver to: {o.delivery_address.line1}{o.delivery_address.line2 ? `, ${o.delivery_address.line2}` : ''}, {o.delivery_address.city}{o.delivery_address.delivery_notes ? ` (${o.delivery_address.delivery_notes})` : ''}</p>}
          {o.customer_notes && <p>Customer note: <i>{o.customer_notes}</i></p>}
          <table className="tbl"><tbody>
            {o.items.map((i, k) => <tr key={k}><td>{i.quantity} × {i.product_name}{i.variation_name ? ` (${i.variation_name})` : ''}{i.addons.length > 0 && <div className="muted">{i.addons.map((a) => `${a.quantity}× ${a.name}`).join(', ')}</div>}{i.instructions && <div className="muted">Note: {i.instructions}</div>}</td><td style={{ textAlign: 'right' }}>{money(i.line_total)}</td></tr>)}
            <tr><td><b>Total</b></td><td style={{ textAlign: 'right' }}><b>{money(o.total)}</b></td></tr>
          </tbody></table>
          <h3 style={{ marginTop: 16 }}>Payment</h3>
          <p>{money(o.amount_paid)} paid of {money(o.total)} · <b>{o.payment_status}</b></p>
          {o.payments.map((p) => <p key={p.id} className="muted">{p.method} · {p.status} · {money(p.amount)} {p.receipt_id && <Link to={`/receipts/${p.receipt_id}`}>receipt</Link>} {canRefund && p.status === 'succeeded' && <button className="btn sm secondary" disabled={busy} onClick={() => refund(p.id, p.amount)}>Refund</button>}</p>)}
          {o.payment_status !== 'paid' && !['cancelled', 'refunded', 'refund_pending'].includes(o.status) && o.payment_method === 'cash' && <button className="btn sm" disabled={busy} onClick={recordCash}>Record cash payment</button>}
          <h3 style={{ marginTop: 16 }}>History</h3>
          <ul style={{ paddingLeft: 18 }}>{o.history.map((h, i) => <li key={i}><b>{h.status_label}</b> <span className="muted">{new Date(h.created_at).toLocaleString()} · {h.actor_role}{h.note ? ` · ${h.note}` : ''}</span></li>)}</ul>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
            {o.allowed_transitions.length === 0 ? <span className="muted">No actions available for your role at this stage.</span> : o.allowed_transitions.map((t) => <button key={t.status} className={`btn ${t.status === 'cancelled' ? 'danger' : ''}`} disabled={busy} onClick={() => move(t.status, t.label)}>{t.status === 'cancelled' ? 'Cancel order' : `Mark ${t.label}`}</button>)}
          </div>
        </>
      )}
    </Drawer>
  )
}

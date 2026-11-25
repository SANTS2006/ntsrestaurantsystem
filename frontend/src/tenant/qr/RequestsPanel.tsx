import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api, type Page } from '../../lib/api'
import { useStaffSocket } from '../../lib/realtime'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'
import { usePrompt } from '../../ui/dialogs'

type Req = {
  id: number; status: string; branch_name: string; table: string; customer_name: string; customer_phone: string; notes: string; created_at: string
  summary: { currency: string; total: string; lines: { name: string; variation: string; quantity: number; addons: string[]; instructions: string; line_total: string }[] }
}
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')

/** Live list of table requests for the cashier. WebSocket pushes new requests instantly; polling is the fallback. */
export default function RequestsPanel({ onCount }: { onCount?: (n: number) => void }) {
  const prompt = usePrompt()
  const { money } = useSite()
  const toast = useToast()
  const list = useAsync(() => api<Page<Req>>('/qr-menu/requests/', { params: { status: 'new' } }), [])
  const { reload } = list
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  const [convert, setConvert] = useState<Req | null>(null)
  const seen = useRef(new Set<number>())

  const live = useStaffSocket(useCallback((e) => {
    if (e.type === 'qr.request.created') { setFresh((s) => new Set(s).add(e.id as number)); toast(`New request from ${e.table as string}`) }
    if (String(e.type).startsWith('qr.request')) reload()
  }, [reload, toast]))

  useEffect(() => { // fallback: poll while the socket is not live
    if (live === 'live') return
    const t = setInterval(() => { if (!document.hidden) reload() }, 8000)
    return () => clearInterval(t)
  }, [live, reload])

  const rows = list.data?.results ?? []
  useEffect(() => {
    onCount?.(rows.length)
    for (const r of rows) if (!seen.current.has(r.id)) { seen.current.add(r.id) } // first load is not "new"
  }, [rows.length]) // eslint-disable-line react-hooks/exhaustive-deps

  async function reject(r: Req) {
    const reason = await prompt({ title: `Reject the request from ${r.table}?`, message: 'The reason is shown to the diner.', label: 'Reason', danger: true, confirmLabel: 'Reject' })
    if (reason === null) return
    try { await api(`/qr-menu/requests/${r.id}/reject/`, { body: { reason } }); toast('Request rejected.'); reload() } catch (e) { toast(msg(e)) }
  }
  return (
    <>
      <p className="muted" aria-live="polite">{live === 'live' ? '● Live: new requests appear instantly.' : live === 'connecting' ? 'Connecting…' : '○ Live updates unavailable: refreshing every few seconds.'}</p>
      {list.error && <ErrorState message={list.error} onRetry={reload} />}
      {list.loading && !list.data ? <Skeleton h={120} /> : !rows.length ? <Empty title="No requests waiting">Requests sent from table QR codes appear here.</Empty> : (
        <div className="grid g2" style={{ alignItems: 'start' }}>
          {rows.map((r) => (
            <div key={r.id} className="card" style={fresh.has(r.id) ? { borderColor: 'var(--brand)', borderWidth: 2 } : undefined}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><b style={{ fontSize: '1.15rem' }}>{r.table}</b><span className="muted">{new Date(r.created_at).toLocaleTimeString()}</span></div>
              <p className="muted" style={{ margin: '2px 0 8px' }}>{r.branch_name}{r.customer_name && ` · ${r.customer_name}`}{r.customer_phone && ` · ${r.customer_phone}`}</p>
              {r.summary.lines.map((l, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span>{l.quantity} × {l.name}{l.variation ? ` (${l.variation})` : ''}{l.addons.length > 0 && <span className="muted"> + {l.addons.join(', ')}</span>}{l.instructions && <div className="muted" style={{ fontSize: '.85rem' }}>Note: {l.instructions}</div>}</span><span>{money(l.line_total)}</span></div>))}
              {r.notes && <p style={{ marginTop: 6 }}><i>{r.notes}</i></p>}
              <p style={{ fontWeight: 700, marginTop: 8 }}>Total {money(r.summary.total)} <span className="muted" style={{ fontWeight: 400 }}>(re-priced when confirmed)</span></p>
              <div style={{ display: 'flex', gap: 8 }}><button className="btn" onClick={() => setConvert(r)}>Confirm order</button><button className="btn secondary" onClick={() => reject(r)}>Reject</button></div>
            </div>))}
        </div>)}
      {convert && <ConvertModal req={convert} onClose={() => setConvert(null)} onDone={() => { setConvert(null); reload() }} />}
    </>
  )
}

function ConvertModal({ req, onClose, onDone }: { req: Req; onClose: () => void; onDone: () => void }) {
  const { site, money } = useSite()
  const [payment, setPayment] = useState('cash')
  const [received, setReceived] = useState('')
  const [phone, setPhone] = useState(req.customer_phone)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<{ number: string; change: string | null; receipt: number | null } | null>(null)
  const key = useRef(crypto.randomUUID()) // retrying the same confirmation can never create two orders
  const change = /^\d+(\.\d{1,2})?$/.test(received) ? Number(received) - Number(req.summary.total) : null

  async function submit(e: FormEvent) {
    e.preventDefault(); setError('')
    if (payment === 'cash' && !/^\d+(\.\d{1,2})?$/.test(received)) return setError('Enter the cash received, e.g. 50.00.')
    if (payment === 'mobile_money' && !phone.trim()) return setError("Enter the customer's mobile money number.")
    setBusy(true)
    try {
      const r = await api<{ order: { number: string }; payment?: { receipt_id: number | null }; change_given?: string | null }>(`/qr-menu/requests/${req.id}/convert/`, {
        body: { payment, ...(payment === 'cash' ? { amount_received: received } : {}), ...(payment === 'mobile_money' ? { payer_phone: phone } : {}) }, headers: { 'Idempotency-Key': key.current } })
      setDone({ number: r.order.number, change: r.change_given ?? null, receipt: r.payment?.receipt_id ?? null })
    } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }
  if (done) return (
    <Modal title={`Order ${done.number} created`} onClose={onDone}>
      {done.change !== null && <p style={{ fontSize: '1.4rem' }}>Change to give: <b>{money(done.change)}</b></p>}
      <div style={{ display: 'flex', gap: 8 }}>{done.receipt && <Link className="btn" to={`/receipts/${done.receipt}`} target="_blank">Print receipt</Link>}<button className="btn secondary" onClick={onDone}>Done</button></div>
    </Modal>
  )
  return (
    <Modal title={`Confirm ${req.table}`} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {error && <div className="alert error" role="alert">{error}</div>}
        <p>Estimated total <b>{money(req.summary.total)}</b>. The final amount is calculated again by the system.</p>
        <Field label="Payment">{(p) => <select {...p} className="input" value={payment} onChange={(e) => setPayment(e.target.value)}><option value="cash">Cash</option>{site.online_payments && <option value="mobile_money">Mobile money</option>}<option value="pay_later">Pay later</option></select>}</Field>
        {payment === 'cash' && <Field label="Cash received">{(p) => <input {...p} className="input" inputMode="decimal" placeholder="e.g. 50.00" value={received} onChange={(e) => setReceived(e.target.value)} />}</Field>}
        {payment === 'cash' && change !== null && change >= 0 && <p>Change: <b>{money(change.toFixed(2))}</b></p>}
        {payment === 'mobile_money' && <Field label="Mobile money number">{(p) => <input {...p} className="input" type="tel" placeholder="Customer's number" value={phone} onChange={(e) => setPhone(e.target.value)} />}</Field>}
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Create order'}</button>
      </form>
    </Modal>
  )
}

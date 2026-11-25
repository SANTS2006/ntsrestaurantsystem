import { Download, Printer } from 'lucide-react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { api, downloadFile } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Empty, ErrorState, Skeleton, useAsync, useDocumentTitle, useToast } from '../ui/kit'
import { formatMoney } from './SiteContext'

type ReceiptData = {
  id: number; number: string; issued_at: string; currency: string; order_number: string; fulfilment: string
  restaurant: { name: string; phone: string; email: string; address: string }
  branch: { name: string; address: string; phone: string }
  customer: { name: string; phone: string; email: string }
  cashier: string
  items: { name: string; variation: string; quantity: number; unit_price: string; line_total: string; addons: { name: string; quantity: number }[] }[]
  totals: { subtotal: string; discount: string; tax: string; delivery_fee: string; total: string }
  payment: { method: string; reference: string; amount: string; received: string; change: string; paid_at: string; status: string }
}

/** Receipt view shared by customers (own receipts) and staff (their branch). Print uses the browser's print dialog. */
export default function Receipt() {
  const { id = '' } = useParams()
  const { me, loading } = useAuth()
  const toast = useToast()
  const r = useAsync(() => (me ? api<ReceiptData>(`/payments/receipts/${id}/`) : Promise.resolve(null)), [id, me?.id])
  useDocumentTitle(r.data ? `Receipt ${r.data.number}` : 'Receipt')
  if (loading) return <Skeleton h={200} />
  if (!me) return <Navigate to={`/login?next=/receipts/${id}`} replace />
  if (r.loading) return <div className="container section"><Skeleton h={300} /></div>
  if (r.error || !r.data) return <div className="container section"><ErrorState message={r.error ?? 'Receipt not found.'} /> <Link to="/">Home</Link></div>
  const d = r.data
  const m = (v: string) => formatMoney(v, d.currency)
  const back = me.role === 'customer' ? '/account/orders' : '/manage/orders'
  return (
    <section className="section">
      <div className="container" style={{ maxWidth: 520 }}>
        <div className="toolbar no-print">
          <Link to={back}>← Back</Link><div style={{ flex: 1 }} />
          <button className="btn sm secondary" onClick={() => window.print()}><Printer size={16} aria-hidden /> Print</button>
          <button className="btn sm" onClick={() => downloadFile(`/payments/receipts/${id}/pdf/`, `${d.number}.pdf`).catch(() => toast('Could not download the PDF.'))}><Download size={16} aria-hidden /> PDF</button>
        </div>
        <div className="card" id="receipt">
          <h1 style={{ fontSize: '1.4rem', marginBottom: 2 }}>{d.restaurant.name}</h1>
          <p className="muted" style={{ marginBottom: 12 }}>{d.branch.name}{d.branch.address ? `, ${d.branch.address}` : ''}{d.branch.phone ? ` · ${d.branch.phone}` : ''}</p>
          <p><b>Receipt {d.number}</b><br />Order {d.order_number} · {new Date(d.payment.paid_at).toLocaleString()}</p>
          {d.customer.name && <p>Customer: {d.customer.name}</p>}
          {d.cashier && <p>Cashier: {d.cashier}</p>}
          <table className="tbl"><tbody>
            {d.items.map((i, k) => <tr key={k}><td>{i.quantity} × {i.name}{i.variation ? ` (${i.variation})` : ''}{i.addons.map((a) => <div key={a.name} className="muted">+ {a.quantity} × {a.name}</div>)}</td><td style={{ textAlign: 'right' }}>{m(i.line_total)}</td></tr>)}
            <tr><td>Subtotal</td><td style={{ textAlign: 'right' }}>{m(d.totals.subtotal)}</td></tr>
            {Number(d.totals.discount) > 0 && <tr><td>Discount</td><td style={{ textAlign: 'right' }}>−{m(d.totals.discount)}</td></tr>}
            {Number(d.totals.tax) > 0 && <tr><td>Tax</td><td style={{ textAlign: 'right' }}>{m(d.totals.tax)}</td></tr>}
            {Number(d.totals.delivery_fee) > 0 && <tr><td>Delivery</td><td style={{ textAlign: 'right' }}>{m(d.totals.delivery_fee)}</td></tr>}
            <tr><td><b>Total</b></td><td style={{ textAlign: 'right' }}><b>{m(d.totals.total)}</b></td></tr>
          </tbody></table>
          <p style={{ marginTop: 12 }}>Paid by {d.payment.method === 'cash' ? 'cash' : 'mobile money'}: <b>{m(d.payment.amount)}</b><br />
            {d.payment.received && <>Received {m(d.payment.received)} · Change {m(d.payment.change)}<br /></>}
            <span className="muted">Reference {d.payment.reference}</span></p>
          {d.restaurant.phone && <p className="muted">{d.restaurant.phone}</p>}
        </div>
        {me.role !== 'customer' && <Empty title="" />}
      </div>
    </section>
  )
}

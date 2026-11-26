import { Download, Printer } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { api, downloadFile } from '../lib/api'
import { useAuth } from '../lib/auth'
import { API_URL } from '../lib/config'
import { BackButton } from '../ui/BackButton'
import { ErrorState, Skeleton, useAsync, useDocumentTitle, useToast } from '../ui/kit'
import { formatMoney } from './SiteContext'
import '../receipt.css'

export type ReceiptData = {
  id: number; number: string; issued_at: string; currency: string; order_number: string; fulfilment: string; table?: string
  website?: string; footer?: string; qr?: string
  restaurant: { name: string; logo?: string; phone: string; email: string; address: string; city?: string }
  branch: { name: string; address: string; phone: string }
  customer: { name: string; phone: string; email: string }
  cashier: string
  items: { name: string; variation: string; quantity: number; unit_price: string; line_total: string; addons: { name: string; quantity: number }[] }[]
  totals: { subtotal: string; discount: string; tax: string; delivery_fee: string; total: string }
  payment: { method: string; reference: string; amount: string; received: string; change: string; paid_at: string; status: string }
}

const FULFILMENT: Record<string, string> = { dine_in: 'Dine in', pickup: 'Takeaway / pickup', delivery: 'Delivery' }
const METHOD: Record<string, string> = { cash: 'Cash', mobile_money: 'Mobile money' }

/** The receipt as it comes out of the 80 mm printer (72 mm printable, black on white whatever the app's theme). */
export function ReceiptPaper({ d }: { d: ReceiptData }) {
  const m = (v: string) => formatMoney(v, d.currency)
  const logo = d.restaurant.logo ? (d.restaurant.logo.startsWith('http') ? d.restaurant.logo : `${API_URL}${d.restaurant.logo}`) : ''
  const address = [d.restaurant.address, d.restaurant.city].filter(Boolean).join(', ')
  const contacts = [d.branch.phone || d.restaurant.phone, d.restaurant.email].filter(Boolean)
  const Row = ({ label, value, strong }: { label: string; value: string; strong?: boolean }) => (
    <div className={`rc-row ${strong ? 'strong' : ''}`}><span>{label}</span><span>{value}</span></div>
  )
  return (
    <article className="receipt-paper" id="receipt" aria-label={`Receipt ${d.number}`}>
      <header>
        {logo && <img className="rc-logo" src={logo} alt="" />}
        <h1>{d.restaurant.name}</h1>
        {address && <p>{address}</p>}
        <p>Branch: {d.branch.name}{d.branch.address ? `, ${d.branch.address}` : ''}</p>
        {contacts.map((c) => <p key={c}>{c}</p>)}
      </header>
      <h2>Sales receipt</h2>
      <section>
        <Row label="Receipt no." value={d.number} strong />
        <Row label="Order no." value={d.order_number} />
        <Row label="Date" value={new Date(d.payment.paid_at || d.issued_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })} />
        <Row label="Order type" value={FULFILMENT[d.fulfilment] ?? d.fulfilment} />
        {d.table && <Row label="Table" value={d.table} />}
        {d.cashier && <Row label="Served by" value={d.cashier} />}
        {d.customer.name && <Row label="Customer" value={d.customer.name} />}
      </section>
      <section>
        <div className="rc-row head"><span>Item</span><span>Amount</span></div>
        {d.items.map((i, k) => (
          <div className="rc-item" key={k}>
            <Row label={`${i.name}${i.variation ? ` (${i.variation})` : ''}`} value={m(i.line_total)} strong />
            <small>{i.quantity} × {m(i.unit_price)}</small>
            {i.addons.map((a) => <small key={a.name}>+ {a.quantity} × {a.name}</small>)}
          </div>
        ))}
      </section>
      <section>
        <Row label="Subtotal" value={m(d.totals.subtotal)} />
        {Number(d.totals.discount) > 0 && <Row label="Discount" value={`-${m(d.totals.discount)}`} />}
        {Number(d.totals.tax) > 0 && <Row label="Tax" value={m(d.totals.tax)} />}
        {Number(d.totals.delivery_fee) > 0 && <Row label="Delivery fee" value={m(d.totals.delivery_fee)} />}
        <div className="rc-total"><span>Total</span><span>{m(d.totals.total)}</span></div>
        <Row label={`Paid (${METHOD[d.payment.method] ?? d.payment.method})`} value={m(d.payment.amount)} strong />
        {d.payment.received && <><Row label="Cash received" value={m(d.payment.received)} /><Row label="Change" value={m(d.payment.change)} /></>}
        {Number(d.totals.total) > Number(d.payment.amount) && <p className="rc-note">This is a part payment.</p>}
        <p className="rc-ref">Ref: {d.payment.reference}</p>
      </section>
      <footer>
        <p className="rc-thanks">{d.footer || 'Thank you for your order. Please come again!'}</p>
        {d.qr && <><img className="rc-qr" src={d.qr} alt="QR code of the restaurant website" /><p>Scan to order online</p></>}
        {d.website && <p className="rc-site">{d.website.replace(/^https?:\/\//, '')}</p>}
        <p>Please keep this receipt.</p>
      </footer>
    </article>
  )
}

/** Receipt view shared by customers (own receipts) and staff (their branch). Print uses the browser's print dialog. */
export default function Receipt() {
  const { id = '' } = useParams()
  const { me, loading } = useAuth()
  const toast = useToast()
  const wrap = useRef<HTMLDivElement>(null)
  const r = useAsync(() => (me ? api<ReceiptData>(`/payments/receipts/${id}/`) : Promise.resolve(null)), [id, me?.id])
  useDocumentTitle(r.data ? `Receipt ${r.data.number}` : 'Receipt')

  // The printer's paper is 80 mm wide and as long as the receipt: the page size is set from the receipt's real height just before printing.
  useEffect(() => {
    if (!r.data) return
    const style = document.createElement('style')
    document.head.appendChild(style)
    const fit = () => {
      const paper = wrap.current?.querySelector<HTMLElement>('.receipt-paper')
      const height = Math.ceil(((paper?.scrollHeight ?? 600) * 25.4) / 96) + 8
      style.textContent = `@page { size: 80mm ${Math.max(height, 80)}mm; margin: 0; }`
    }
    fit()
    document.documentElement.classList.add('printing-receipt')
    window.addEventListener('beforeprint', fit)
    return () => { window.removeEventListener('beforeprint', fit); style.remove(); document.documentElement.classList.remove('printing-receipt') }
  }, [r.data])

  if (loading) return <Skeleton h={200} />
  if (!me) return <Navigate to={`/login?next=/receipts/${id}`} replace />
  if (r.loading && !r.data) return <div className="container section"><Skeleton h={300} /></div>
  if (r.error || !r.data) return <div className="container section"><ErrorState message={r.error ?? 'Receipt not found.'} /> <Link to="/">Home</Link></div>
  const d = r.data
  const back = me.role === 'customer' ? '/account/orders' : '/manage/orders'
  return (
    <div className="receipt-page" ref={wrap}>
      <div className="receipt-actions no-print">
        <BackButton to={back} />
        <button className="btn secondary" onClick={() => window.print()}><Printer size={16} aria-hidden /> Print (80 mm)</button>
        <button className="btn" onClick={() => downloadFile(`/payments/receipts/${id}/pdf/`, `${d.number}.pdf`).catch(() => toast('Could not download the PDF.'))}><Download size={16} aria-hidden /> PDF</button>
      </div>
      <ReceiptPaper d={d} />
      <p className="hint no-print receipt-help">For the thermal printer, choose it in the print window with paper size 80 mm, margins “None” and scale 100%.</p>
    </div>
  )
}

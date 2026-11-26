import { CheckCircle2, ExternalLink, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { BackButton } from '../ui/BackButton'
import { PageLoader, Spinner, useDocumentTitle, useToast } from '../ui/kit'
import { formatMoney } from './SiteContext'
import { UssdCode } from './UssdCode'

type Payment = { id: number; order_id: number; status: string; amount: string; currency: string; checkout_url: string; redirect_url: string; ussd_code: string }
type OrderLite = { id: number; number: string; total: string; currency: string; payment_status: string; status: string; payments: { id: number; method: string; status: string; receipt_id: number | null }[] }

const POLL_MS = 4000

/** Calls `tick` now and then every few seconds while it returns true. */
function usePoll(tick: () => Promise<boolean>, key: string) {
  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const run = async () => {
      let again = true
      try { again = await tick() } catch { /* offline: try again */ }
      if (!stop && again) timer = setTimeout(run, POLL_MS)
    }
    void run()
    return () => { stop = true; clearTimeout(timer) }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
}

/** "Complete your payment": the dial code (or the Monime page link). Moves to the success page by itself once Monime confirms. */
export function PayPage() {
  useDocumentTitle('Complete your payment')
  const { paymentId = '' } = useParams()
  const [params] = useSearchParams()
  const orderId = params.get('order') ?? ''
  const { me, loading } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const [p, setP] = useState<Payment | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  usePoll(async () => {
    if (!me) return true
    try {
      const next = await api<Payment>(`/payments/my/${paymentId}/`)
      setP(next); setError('')
      if (next.status === 'succeeded') { navigate(`/payment-complete?order=${next.order_id}`, { replace: true }); return false }
      return next.status === 'pending'
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not check the payment.')
      return !(e instanceof ApiError && e.status === 404)
    }
  }, `${paymentId}-${me?.id ?? ''}`)

  async function retry() {
    setBusy(true)
    try {
      const id = Number(orderId || p?.order_id)
      const { contact_phone } = await api<{ contact_phone: string }>(`/orders/my/${id}/`) // the number already on the order
      const next = await api<Payment>('/payments/initiate/', { body: { order_id: id, phone: contact_phone }, headers: { 'Idempotency-Key': crypto.randomUUID() } })
      if (next.redirect_url) { window.location.assign(next.redirect_url); return }
      navigate(`/pay/${next.id}?order=${next.order_id}`, { replace: true })
    } catch (e) { toast(e instanceof ApiError ? (e.fieldErrors().detail ?? e.fieldErrors().order_id ?? e.message) : 'Could not start the payment.') } finally { setBusy(false) }
  }

  if (loading) return <PageLoader />
  if (!me) return <Navigate to={`/login?next=/pay/${paymentId}`} replace />
  return (
    <div className="container section pay-screen">
      <div className="card pay-card">
        {!p ? (error ? <p className="alert error" role="alert">{error}</p> : <PageLoader label="Preparing your payment" />) : p.status === 'pending' ? (
          <>
            <p className="eyebrow">Mobile money</p>
            <h1>{formatMoney(p.amount, p.currency)}</h1>
            {p.ussd_code && <UssdCode code={p.ussd_code} />}
            {p.checkout_url && <p><a className="btn lg" href={p.checkout_url}><ExternalLink size={18} aria-hidden /> Continue to the Monime payment page</a></p>}
            <p className="pay-waiting" role="status" aria-live="polite"><Spinner size={22} /> Waiting for your payment…</p>
            {error && <p className="err">{error}</p>}
          </>
        ) : (
          <div className="pay-result bad" role="alert">
            <XCircle size={64} aria-hidden />
            <h1>Payment not completed</h1>
            <p className="muted">The payment was cancelled or the code expired. No money was taken by this attempt.</p>
            <button className="btn lg" disabled={busy} onClick={() => void retry()}>{busy ? <Spinner /> : 'Try again'}</button>
          </div>
        )}
        <p><BackButton to={orderId ? `/account/orders/${orderId}` : '/account/orders'}>View my order</BackButton></p>
      </div>
    </div>
  )
}

/**
 * Where the customer lands after paying. It never trusts the address: success is shown only when the server says the order is paid
 * (the server asks Monime). Guests who paid at the counter have no account and get a plain thank-you.
 */
export function PaymentComplete() {
  useDocumentTitle('Payment')
  const [params] = useSearchParams()
  const orderId = /^\d+$/.test(params.get('order') ?? '') ? params.get('order')! : ''
  const { me, loading } = useAuth()
  const [order, setOrder] = useState<OrderLite | null>(null)
  const [gaveUp, setGaveUp] = useState(false)

  usePoll(async () => {
    if (!me || !orderId) return !!orderId
    let o = await api<OrderLite>(`/orders/my/${orderId}/`)
    const pending = o.payments.find((x) => x.status === 'pending')
    if (o.payment_status !== 'paid' && pending) {
      await api(`/payments/my/${pending.id}/`) // asks Monime now
      o = await api<OrderLite>(`/orders/my/${orderId}/`)
    }
    setOrder(o)
    return o.payment_status !== 'paid' && o.payments.some((x) => x.status === 'pending')
  }, `${orderId}-${me?.id ?? ''}`)
  useEffect(() => { const t = setTimeout(() => setGaveUp(true), 90000); return () => clearTimeout(t) }, [])

  if (loading) return <PageLoader />
  const paid = order?.payment_status === 'paid'
  const pending = order?.payments.some((x) => x.status === 'pending')
  const receipt = order?.payments.find((x) => x.status === 'succeeded' && x.receipt_id)?.receipt_id

  return (
    <div className="container section pay-screen">
      <div className="card pay-card">
        {!orderId || !me ? (
          <div className="pay-result">
            <CheckCircle2 size={64} aria-hidden />
            <h1>Thank you</h1>
            <p className="muted">The restaurant confirms your payment automatically. You can return to the counter, or sign in to follow your order.</p>
            <Link className="btn lg" to={me ? '/account/orders' : '/'}>{me ? 'My orders' : 'Back to the website'}</Link>
          </div>
        ) : paid && order ? (
          <div className="pay-result ok" role="status">
            <span className="tick"><CheckCircle2 size={72} aria-hidden /></span>
            <h1>Payment successful</h1>
            <p>We received <b>{formatMoney(order.total, order.currency)}</b> for order <b>{order.number}</b>.</p>
            <p className="muted">The restaurant has your order. We will let you know when it is ready.</p>
            <div className="ussd-actions">
              <Link className="btn lg" to={`/account/orders/${order.id}`}>Follow my order</Link>
              {receipt && <Link className="btn lg secondary" to={`/receipts/${receipt}`}>View receipt</Link>}
            </div>
          </div>
        ) : order && !pending ? (
          <div className="pay-result bad" role="alert">
            <XCircle size={64} aria-hidden />
            <h1>Payment not completed</h1>
            <p className="muted">We have not received a payment for order {order.number}. You can try again from the order.</p>
            <Link className="btn lg" to={`/account/orders/${order.id}`}>Go to my order</Link>
          </div>
        ) : (
          <div className="pay-result" role="status" aria-live="polite">
            <Spinner size={64} />
            <h1>Confirming your payment</h1>
            <p className="muted">{gaveUp ? 'This is taking longer than usual. You can leave this page: your order updates as soon as the payment is confirmed.' : 'This usually takes a few seconds. Please keep this page open.'}</p>
            <Link className="btn secondary" to={`/account/orders/${orderId}`}>View my order</Link>
          </div>
        )}
      </div>
    </div>
  )
}

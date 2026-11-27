import { CheckCircle2, ExternalLink, Smartphone, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Spinner } from '../ui/kit'
import { UssdCode } from './UssdCode'

type Status = { id: number; status: string; amount: string; currency: string; checkout_url: string; ussd_code?: string; qr: string; receipt_id: number | null; order_number: string; failure_reason: string }

const POLL_MS = 5000

/**
 * Till view of a mobile-money (Monime) payment: the customer scans the code (or the till opens the payment page), pays on their phone,
 * and this follows the result. Only the server, after asking Monime, decides that it is paid.
 */
export function MomoPayment({ paymentId, onPaid }: { paymentId: number; onPaid?: () => void }) {
  const [s, setS] = useState<Status | null>(null)
  const [error, setError] = useState('')
  const paid = useRef(onPaid)
  paid.current = onPaid

  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const r = await api<Status>(`/payments/${paymentId}/status/`)
        if (stop) return
        setS(r); setError('')
        if (r.status === 'succeeded') { paid.current?.(); return }
        if (r.status !== 'pending') return
      } catch (e) { if (!stop) setError((e as Error).message) }
      timer = setTimeout(tick, POLL_MS)
    }
    void tick()
    return () => { stop = true; clearTimeout(timer) }
  }, [paymentId])

  if (!s) return <div className="momo"><Spinner size={32} /><p className="muted">{error || 'Preparing the mobile money payment…'}</p></div>
  if (s.status === 'succeeded') {
    return (
      <div className="momo ok" role="status">
        <CheckCircle2 size={46} aria-hidden />
        <h3>Payment received</h3>
        <p>{s.currency} {s.amount} for order {s.order_number}</p>
        {s.receipt_id && <Link className="btn" to={`/receipts/${s.receipt_id}?print=1`}>Print receipt</Link>}
      </div>
    )
  }
  if (s.status !== 'pending') {
    return (
      <div className="momo bad" role="alert">
        <XCircle size={46} aria-hidden />
        <h3>Payment did not go through</h3>
        <p className="muted">{s.status === 'mismatch' ? 'The amount reported by the provider does not match. Do not hand over the order; ask a manager to check.' : 'Start a new mobile money payment or take cash from the order screen.'}</p>
      </div>
    )
  }
  return (
    <div className="momo" role="status" aria-live="polite">
      <h3><Smartphone size={20} aria-hidden /> Mobile money: {s.currency} {s.amount}</h3>
      <p className="muted">{s.ussd_code ? 'The customer can dial the code below, or scan the square code to open their dialler.' : 'Ask the customer to scan this code with their phone and pay on the Monime page.'}</p>
      {s.ussd_code && <UssdCode code={s.ussd_code} forStaff />}
      {s.qr && <img src={s.qr} alt="QR code of the mobile money payment page" width={220} height={220} />}
      {s.checkout_url && <a className="btn secondary sm" href={s.checkout_url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} aria-hidden /> Open payment page</a>}
      <p className="waiting"><Spinner size={18} /> Waiting for the payment to be confirmed…</p>
      {error && <p className="err">{error}</p>}
    </div>
  )
}

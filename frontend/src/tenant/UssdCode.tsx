import { Check, Copy, PhoneCall } from 'lucide-react'
import { useState } from 'react'

/** A mobile-money dial code (Orange Money / Afrimoney): large, tap to dial, copy, and what happens next. */
export function UssdCode({ code, forStaff = false }: { code: string; forStaff?: boolean }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch { /* the code stays on screen to be typed */ }
  }
  return (
    <div className="ussd">
      <p className="ussd-label">{forStaff ? 'Ask the customer to dial this code on their phone' : 'Dial this code on your Orange Money or Afrimoney phone'}</p>
      <p className="ussd-code" aria-label={`Payment code ${code}`}>{code}</p>
      <div className="ussd-actions">
        <a className="btn" href={`tel:${code.replace(/#/g, '%23')}`}><PhoneCall size={17} aria-hidden /> Tap to dial</a>
        <button type="button" className="btn secondary" onClick={() => void copy()}>{copied ? <Check size={17} aria-hidden /> : <Copy size={17} aria-hidden />} {copied ? 'Copied' : 'Copy code'}</button>
      </div>
      <ol className="ussd-steps">
        <li>Dial the code and press call.</li>
        <li>Check the amount and approve with your mobile money PIN.</li>
        <li>Stay on this screen: it moves on by itself when the payment is confirmed.</li>
      </ol>
      <p className="hint">The code is for this payment only and expires after 30 minutes. Never share your PIN.</p>
    </div>
  )
}

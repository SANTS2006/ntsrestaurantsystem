import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/**
 * The one back control of the whole system: a pill with a round arrow "puck". On hover the puck stretches across the pill and the
 * arrow slides back, showing which way it goes. Give `to` for a link or `onClick` for a button.
 */
export function BackButton({ to, onClick, children = 'Back', className = '' }: { to?: string; onClick?: () => void; children?: ReactNode; className?: string }) {
  const inner = (
    <>
      <span className="back-puck" aria-hidden><ArrowLeft size={17} strokeWidth={2.6} /></span>
      <span className="back-label">{children}</span>
    </>
  )
  return to
    ? <Link to={to} className={`back-btn no-print ${className}`} onClick={onClick}>{inner}</Link>
    : <button type="button" className={`back-btn no-print ${className}`} onClick={onClick}>{inner}</button>
}

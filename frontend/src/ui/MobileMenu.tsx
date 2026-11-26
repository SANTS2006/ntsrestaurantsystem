import { ChevronRight, X } from 'lucide-react'
import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

/**
 * The website menu on phones and tablets: a panel that slides in from the right (and out again) over a dimmed page, showing the
 * logo and name, the pages one after another, and the account actions. Escape, the dimmed area or choosing a page closes it.
 * It sits outside the header, because the header's blur would otherwise trap a fixed panel inside it.
 */
export function MobileMenu({ open, onClose, brand, logo, links, children }: {
  open: boolean; onClose: () => void; brand: string; logo?: string | null; links: readonly (readonly [string, string])[]; children?: ReactNode
}) {
  const closeButton = useRef<HTMLButtonElement>(null)
  const { pathname } = useLocation()
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => close.current(), [pathname])
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => e.key === 'Escape' && close.current()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden' // the page behind does not scroll while the menu is open
    document.addEventListener('keydown', key)
    closeButton.current?.focus({ preventScroll: true })
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', key) }
  }, [open])

  return (
    <div className={`mobile-menu ${open ? 'open' : ''}`}>
      <div className="mm-scrim" onClick={onClose} aria-hidden="true" />
      <aside className="mm-panel" role="dialog" aria-modal="true" aria-label="Website menu" aria-hidden={!open}>
        <div className="mm-head">
          {logo && <img src={logo} alt="" width={40} height={40} />}
          <b>{brand}</b>
          <button ref={closeButton} type="button" className="mm-close" aria-label="Close menu" onClick={onClose}><X size={20} aria-hidden /></button>
        </div>
        <nav aria-label="Mobile">
          {links.map(([to, label], i) => (
            <NavLink key={to} to={to} end={to === '/'} onClick={onClose} style={{ '--i': i } as CSSProperties}><span>{label}</span><ChevronRight size={18} aria-hidden /></NavLink>
          ))}
        </nav>
        {children && <div className="mm-foot" onClick={onClose}>{children}</div>}
      </aside>
    </div>
  )
}

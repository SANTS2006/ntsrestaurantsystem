import { useSyncExternalStore, type CSSProperties } from 'react'

/**
 * Branded loading animations. The logo shown is the restaurant's inside a restaurant (set by the site / workspace),
 * and the platform logo everywhere else.
 */
type Brand = { logo: string; name: string }
const PLATFORM: Brand = { logo: '/logo-64.png', name: 'NTS Restaurant Platform' }
let brand: Brand = PLATFORM
const subs = new Set<() => void>()

export function setBrand(b: { logo?: string | null; name?: string } | null) {
  const next = { logo: b?.logo || PLATFORM.logo, name: b?.name || PLATFORM.name }
  if (next.logo === brand.logo && next.name === brand.name) return
  brand = next
  subs.forEach((f) => f())
}
export const useBrand = (): Brand => useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f) } }, () => brand)

/** The logo inside a turning ring. `size` is the diameter in px. Inherits the text colour for the ring so it suits buttons too. */
export function Spinner({ size = 22 }: { size?: number }) {
  const b = useBrand()
  return (
    <span className="bspin" role="status" aria-label="Loading" style={{ '--s': `${size}px` } as CSSProperties}>
      <span className="ring" />
      <img src={b.logo} alt="" />
    </span>
  )
}

/** Centered block for a table, card or panel that is loading. */
export function LoadingBlock({ label = 'Loading' }: { label?: string }) {
  return <div className="loading-block"><Spinner size={46} /><span>{label}…</span></div>
}

/** Whole-screen loader (page or workspace starting). */
export function PageLoader({ label = 'Loading' }: { label?: string }) {
  const b = useBrand()
  return (
    <div className="page-loader" role="status" aria-live="polite" aria-label={label}>
      <div className="orb"><span className="pulse" /><span className="pulse two" /><img src={b.logo} alt="" /></div>
      <p>{label}…</p>
    </div>
  )
}

/** Shown while signing out: the logout completes when the animation does. */
export function LogoutOverlay() {
  const b = useBrand()
  return (
    <div className="logout-overlay" role="alertdialog" aria-live="assertive" aria-label="Signing out">
      <div className="orb"><span className="pulse" /><span className="pulse two" /><img src={b.logo} alt="" /></div>
      <h2>Signing you out</h2>
      <p>Securing your session&hellip;</p>
      <div className="bar"><span /></div>
    </div>
  )
}

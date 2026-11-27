import { Home, UtensilsCrossed } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BackButton } from './BackButton'

/** `to` is a page of the current website; `href` loads another website (used to leave an address that is not a real restaurant). */
export type NotFoundLink = { label: string; to?: string; href?: string }

/**
 * The one "404, page not found" screen of the whole system. Inside a website or workspace it sits between the header and footer;
 * with `full` it fills the screen by itself (an address that belongs to no website).
 */
export function NotFound({ title = 'This page is not on the menu', text = 'The page you asked for does not exist, or it has moved. Check the address, or choose where to go next.',
  links = [{ to: '/', label: 'Back to home' }], full = false, brand, logo }: {
  title?: string; text?: string; links?: NotFoundLink[]; full?: boolean; brand?: string; logo?: string | null
}) {
  const navigate = useNavigate()
  useEffect(() => {
    const before = document.title
    document.title = 'Page not found (404)'
    // keep missing pages out of search engines
    const robots = document.createElement('meta')
    robots.name = 'robots'
    robots.content = 'noindex'
    document.head.appendChild(robots)
    return () => { robots.remove(); document.title = before }
  }, [])

  const [first, ...others] = links
  const link = (l: NotFoundLink, className: string, icon = false) => {
    const inner = <>{icon && <Home size={17} aria-hidden />} {l.label}</>
    return l.href ? <a key={l.label} className={className} href={l.href}>{inner}</a> : <Link key={l.label} className={className} to={l.to ?? '/'}>{inner}</Link>
  }

  return (
    <section className={`nf ${full ? 'nf-full' : ''}`} aria-labelledby="nf-title">
      <span className="nf-blob a" aria-hidden /><span className="nf-blob b" aria-hidden />
      <div className="nf-card">
        {brand && <p className="nf-brand">{logo && <img src={logo} alt="" width={34} height={34} />} {brand}</p>}
        <p className="nf-code" aria-label="Error 404">
          <span aria-hidden>4</span>
          <span className="nf-plate" aria-hidden><UtensilsCrossed /></span>
          <span aria-hidden>4</span>
        </p>
        <h1 id="nf-title">{title}</h1>
        <p className="nf-text">{text}</p>
        <div className="nf-actions">
          {first && link(first, 'btn lg', true)}
          {others.map((l) => link(l, 'btn lg secondary'))}
        </div>
        {/* only offered when there is somewhere to go back to */}
        {window.history.length > 1 && <div className="nf-back"><BackButton onClick={() => navigate(-1)}>Go back</BackButton></div>}
      </div>
    </section>
  )
}

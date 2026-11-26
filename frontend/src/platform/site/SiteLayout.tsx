import { Menu, MessageCircle } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { useSecretClicks } from '../../lib/useSecretClicks'
import { useAsync } from '../../ui/kit'
import { ThemeToggle } from '../../ui/TopTools'
import { ScrollFx } from '../../ui/fx'
import { MobileMenu } from '../../ui/MobileMenu'

export type PublicSettings = { platform_name: string; whatsapp_number: string; support_email: string }

const links = [
  ['/features', 'Features'],
  ['/pricing', 'Pricing'],
  ['/about', 'About'],
  ['/faq', 'FAQ'],
  ['/contact', 'Contact'],
] as const

export const legal = [
  ['privacy-policy', 'Privacy Policy'],
  ['terms-of-service', 'Terms of Service'],
  ['payment-terms', 'Payment Terms'],
  ['refund-and-cancellation-policy', 'Refund and Cancellation Policy'],
  ['cookie-policy', 'Cookie Policy'],
  ['security-policy', 'Security Policy'],
  ['acceptable-use-policy', 'Acceptable Use Policy'],
] as const

export function usePublicSettings() {
  return useAsync(() => api<PublicSettings>('/platform/public/settings/', { auth: false }), [])
}

export default function SiteLayout() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const goLogin = useCallback(() => navigate('/login'), [navigate])
  const onSecret = useSecretClicks(goLogin)
  const { data: s } = usePublicSettings()
  const name = s?.platform_name ?? 'NTS Restaurant Platform'

  return (
    <>
      <ScrollFx />
      <header className="nav">
        <div className="container row">
          <Link to="/" className="logo" aria-label={name}><img src="/logo-64.png" alt="" width={36} height={36} /> <span className="logo-name">{name}</span></Link>
          <nav className="links" aria-label="Main">
            {links.map(([to, label]) => <NavLink key={to} to={to}>{label}</NavLink>)}
          </nav>
          <div className="nav-end">
          {/* Intentionally empty, unlabelled area: five quick clicks open the sign-in page. */}
          <div className="secret" onClick={onSecret} aria-hidden="true" data-testid="secret-area" />
          <div className="actions">
            <ThemeToggle />
            <Link to="/contact" className="btn sm hide-sm">Contact us</Link>
            <button className="menu-btn" onClick={() => setOpen(true)} aria-label="Toggle menu" aria-expanded={open}><Menu /></button>
          </div>
          </div>
        </div>
      </header>
      <MobileMenu open={open} onClose={() => setOpen(false)} brand={name} logo="/logo-64.png" links={[['/', 'Home'], ...links]}>
        <Link to="/contact" className="btn">Contact us</Link>
      </MobileMenu>
      <main><Outlet /></main>
      <footer className="footer">
        <div className="container">
          <div className="foot-grid">
            <div className="foot-brand">
              <Link to="/" className="logo"><img src="/logo-64.png" alt="" width={36} height={36} /> {name}</Link>
              <p>Run every restaurant, branch and till from one secure platform: orders, payments, kitchen, stock, staff and reports.</p>
            </div>
            <div className="foot-explore"><h4>Product</h4><ul className="foot-links">{links.map(([to, l]) => <li key={to}><Link to={to}>{l}</Link></li>)}</ul></div>
            <div><h4>Legal</h4><ul>{legal.slice(0, 4).map(([slug, l]) => <li key={slug}><Link to={`/legal/${slug}`}>{l}</Link></li>)}</ul></div>
            <div><h4>Contact</h4><div className="foot-contact">{s?.support_email ? <a href={`mailto:${s.support_email}`}>{s.support_email}</a> : <Link to="/contact">Contact us</Link>}{s?.whatsapp_number && <a href={`https://wa.me/${s.whatsapp_number}`} target="_blank" rel="noopener noreferrer">WhatsApp us</a>}</div></div>
          </div>
          <div className="foot-bottom">
            <span>&copy; {new Date().getFullYear()} {name}. All rights reserved.</span>
            <nav aria-label="Legal">{legal.slice(4).map(([slug, l]) => <Link key={slug} to={`/legal/${slug}`}>{l}</Link>)}</nav>
          </div>
        </div>
      </footer>
      {s?.whatsapp_number && (
        <a className="wa" href={`https://wa.me/${s.whatsapp_number}`} target="_blank" rel="noopener noreferrer" aria-label="Chat with us on WhatsApp">
          <MessageCircle />
        </a>
      )}
    </>
  )
}

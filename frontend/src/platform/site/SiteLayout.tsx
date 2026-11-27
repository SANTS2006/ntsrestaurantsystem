import { ArrowRight, ArrowUp, Clock, Mail, MapPin, Menu, MessageCircle, Phone } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { useSecretClicks } from '../../lib/useSecretClicks'
import { ErrorState, PageLoader, useAsync } from '../../ui/kit'
import { ThemeToggle } from '../../ui/TopTools'
import { ScrollFx } from '../../ui/fx'
import { MobileMenu } from '../../ui/MobileMenu'
import { RichText } from '../../ui/RichText'
import { PageBlocks, PageDesigns } from '../../ui/builder/PageDesign'
import { pageIdOf } from '../../ui/builder/types'
import { SiteTextsContext, type PlatformSite } from './content'

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

const toTop = () => window.scrollTo?.({ top: 0, behavior: 'smooth' })

export default function SiteLayout() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const goLogin = useCallback(() => navigate('/login'), [navigate])
  const onSecret = useSecretClicks(goLogin)
  const { data: s } = usePublicSettings()
  const site = useAsync(() => api<PlatformSite>('/website/public/content/', { auth: false }), [])
  const texts = site.data?.content ? site.data : null
  const name = s?.platform_name ?? 'NTS Restaurant Platform'
  const footer = texts?.content.footer
  const contact = texts?.content.contact
  const office = contact?.locations[0]

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
      <main>
        {texts ? <SiteTextsContext.Provider value={texts}><PageDesigns><Outlet /><PageBlocks page={pageIdOf(pathname)} placement="bottom" /></PageDesigns></SiteTextsContext.Provider>
          : site.loading ? <PageLoader />
          : <div className="container section"><ErrorState message={site.error ?? 'The page could not be loaded.'} onRetry={site.reload} /></div>}
      </main>
      <footer className="site-footer">
        <div className="container">
          {footer?.cta_title && pathname !== '/contact' && pathname !== '/' && (
            <div className="foot-cta">
              <div><h2><RichText text={footer.cta_title} /></h2><p><RichText text={footer.cta_text} /></p></div>
              {footer.cta_button && <Link className="btn lg" to="/contact">{footer.cta_button} <ArrowRight size={18} aria-hidden /></Link>}
            </div>
          )}
          <div className="foot-cols">
            <div className="foot-about">
              <Link to="/" className="logo"><img src="/logo-64.png" alt="" width={40} height={40} /> {name}</Link>
              {footer?.about && <p><RichText text={footer.about} /></p>}
              <div className="foot-social">
                {s?.whatsapp_number && <a href={`https://wa.me/${s.whatsapp_number}`} target="_blank" rel="noopener noreferrer" aria-label="WhatsApp"><MessageCircle size={18} aria-hidden /></a>}
                {s?.support_email && <a href={`mailto:${s.support_email}`} aria-label="Email"><Mail size={18} aria-hidden /></a>}
                {contact?.phone && <a href={`tel:${contact.phone.replace(/[^+\d]/g, '')}`} aria-label="Phone"><Phone size={18} aria-hidden /></a>}
              </div>
            </div>
            <nav className="foot-col" aria-label="Product"><h4>Product</h4><ul><li><Link to="/">Home</Link></li>{links.slice(0, 2).map(([to, l]) => <li key={to}><Link to={to}>{l}</Link></li>)}</ul></nav>
            <nav className="foot-col" aria-label="Company"><h4>Company</h4><ul>{links.slice(2).map(([to, l]) => <li key={to}><Link to={to}>{l}</Link></li>)}</ul></nav>
            <nav className="foot-col" aria-label="Legal"><h4>Legal</h4><ul>{legal.slice(0, 4).map(([slug, l]) => <li key={slug}><Link to={`/legal/${slug}`}>{l}</Link></li>)}</ul></nav>
            <div className="foot-col foot-reach"><h4>Get in touch</h4><ul>
              {s?.support_email && <li><Mail size={15} aria-hidden /> <a href={`mailto:${s.support_email}`}>{s.support_email}</a></li>}
              {contact?.phone && <li><Phone size={15} aria-hidden /> <a href={`tel:${contact.phone.replace(/[^+\d]/g, '')}`}>{contact.phone}</a></li>}
              {office?.address && <li><MapPin size={15} aria-hidden /> <Link to="/contact">{office.address}</Link></li>}
              {contact?.hours && <li><Clock size={15} aria-hidden /> <span className="pre"><RichText text={contact.hours} /></span></li>}
              <li><Mail size={15} aria-hidden /> <Link to="/contact">Send us a message</Link></li>
            </ul></div>
          </div>
          <div className="foot-base">
            <span>&copy; {new Date().getFullYear()} {name}. All rights reserved.</span>
            <nav aria-label="More policies">{legal.slice(4).map(([slug, l]) => <Link key={slug} to={`/legal/${slug}`}>{l}</Link>)}</nav>
            <button type="button" className="to-top" onClick={toTop}><ArrowUp size={15} aria-hidden /> Back to top</button>
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

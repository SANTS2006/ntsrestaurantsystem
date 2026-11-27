import { ArrowRight, ArrowUp, Mail, MapPin, Menu as MenuIcon, Phone, ShoppingCart, User } from 'lucide-react'
import { useState, Suspense, lazy } from 'react'
import { Link, NavLink, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { API_URL } from '../lib/config'
import { useAuth } from '../lib/auth'
import { can } from '../lib/permissions'
import { NotificationBell, ThemeToggle } from '../ui/TopTools'
import { Avatar } from '../ui/Shell'
import { ScrollFx } from '../ui/fx'
import { MobileMenu } from '../ui/MobileMenu'
import { CartProvider, useCart } from './cart'
import { Login, Register, VerifyEmail } from './CustomerAuth'
import { CartPage, CheckoutPage } from './shop'
import { PayPage, PaymentComplete } from './PaymentPages'
import { PageLoader } from '../ui/kit'
import { NotFound } from '../ui/NotFound'
import { About, Contact, Faq, Gallery, Home, Menu, Policy, ProductPage, Services } from './pages'
import { SiteProvider, useSite } from './SiteContext'
import { ForgotPassword, SetupPassword } from './StaffAuth'
import { RichText } from '../ui/RichText'
import { PageBlocks, PageDesigns } from '../ui/builder/PageDesign'
import { pageIdOf } from '../ui/builder/types'
import { directionsUrl, mapQuery } from '../ui/geo'
import { spotsOf } from './Locations'

const AccountLayout = lazy(() => import('./account/pages').then((m) => ({ default: m.AccountLayout })))
const Addresses = lazy(() => import('./account/pages').then((m) => ({ default: m.Addresses })))
const MyOrders = lazy(() => import('./account/pages').then((m) => ({ default: m.Orders })))
const OrderDetail = lazy(() => import('./account/pages').then((m) => ({ default: m.OrderDetail })))
const Overview = lazy(() => import('./account/pages').then((m) => ({ default: m.Overview })))
const CustomerProfile = lazy(() => import('./account/pages').then((m) => ({ default: m.CustomerProfile })))
const CustomerSecurity = lazy(() => import('./account/pages').then((m) => ({ default: m.CustomerSecurity })))
const Support = lazy(() => import('./account/pages').then((m) => ({ default: m.Support })))
const CateringAdmin = lazy(() => import('./catering/Admin'))
const MyPay = lazy(() => import('./manage/MyPay'))
const Payroll = lazy(() => import('./manage/Payroll'))
const Reports = lazy(() => import('./manage/Reports'))
const CateringRequestPage = lazy(() => import('./catering/Public').then((m) => ({ default: m.CateringRequestPage })))
const QuotationPage = lazy(() => import('./catering/Public').then((m) => ({ default: m.QuotationPage })))
const QRMenu = lazy(() => import('./qr/QRMenu'))
const Tables = lazy(() => import('./qr/Tables'))
const TablesPrint = lazy(() => import('./qr/Tables').then((m) => ({ default: m.TablesPrint })))
const Branches = lazy(() => import('./manage/Branches'))
const SecurityMfa = lazy(() => import('../ui/Mfa').then((m) => ({ default: m.MfaSettings })))
const ProfileSettings = lazy(() => import('../ui/Profile').then((m) => ({ default: m.ProfileSettings })))
const Notifications = lazy(() => import('../ui/Notifications').then((m) => ({ default: m.NotificationsPage })))
const NotificationDetail = lazy(() => import('../ui/Notifications').then((m) => ({ default: m.NotificationDetailPage })))
const Customers = lazy(() => import('./manage/Customers'))
const Floor = lazy(() => import('./manage/Floor'))
const Stock = lazy(() => import('./manage/Stock'))
const Finance = lazy(() => import('./manage/Finance'))
const ReservePage = lazy(() => import('./Reserve').then((m) => ({ default: m.ReservePage })))
const ReservationManage = lazy(() => import('./Reserve').then((m) => ({ default: m.ReservationManage })))
const Kitchen = lazy(() => import('./manage/Kitchen'))
const Cashier = lazy(() => import('./manage/Cashier'))
const Dashboard = lazy(() => import('./manage/Dashboard'))
const Staff = lazy(() => import('./manage/Staff'))
const ManageOrders = lazy(() => import('./manage/Orders'))
const Shifts = lazy(() => import('./manage/Shifts'))
const ManageLayout = lazy(() => import('./manage/ManageLayout'))
const Categories = lazy(() => import('./manage/pages').then((m) => ({ default: m.Categories })))
const GalleryAdmin = lazy(() => import('./manage/pages').then((m) => ({ default: m.Gallery })))
const Inventory = lazy(() => import('./manage/pages').then((m) => ({ default: m.Inventory })))
const Products = lazy(() => import('./manage/pages').then((m) => ({ default: m.Products })))
const ServicesAdmin = lazy(() => import('./manage/pages').then((m) => ({ default: m.ServicesAdmin })))
const PageBuilder = lazy(() => import('../ui/builder/Builder'))
const SiteContent = lazy(() => import('./manage/pages').then((m) => ({ default: m.SiteContent })))
const Receipt = lazy(() => import('./Receipt'))
const WebsiteMessages = lazy(() => import('../ui/WebsiteMessages'))

const links = [['/', 'Home'], ['/menu', 'Menu'], ['/services', 'Services'], ['/catering', 'Catering'], ['/reserve', 'Reserve'], ['/gallery', 'Gallery'], ['/about', 'About'], ['/contact', 'Contact']] as const

function PublicLayout() {
  const { site } = useSite()
  const [open, setOpen] = useState(false)
  const r = site.restaurant
  const cart = useCart()
  const { me } = useAuth()
  const { pathname } = useLocation()
  const logo = r.logo ? (r.logo.startsWith('http') ? r.logo : `${API_URL}${r.logo}`) : null
  return (
    <>
      <ScrollFx />
      <header className="nav many">
        <div className="container row">
          <Link to="/" className="logo" aria-label={r.name}>{logo && <img src={logo} alt="" height={36} />}<span className="logo-name">{r.name}</span></Link>
          <nav className="links" aria-label="Main">
            {links.map(([to, l]) => <NavLink key={to} to={to} end={to === '/'}>{l}</NavLink>)}
          </nav>
          <div className="nav-end">
          <div className="secret" aria-hidden="true" />
          <div className="actions">
            <ThemeToggle />
            {me && <NotificationBell />}
            <Link to="/cart" className="btn sm secondary" aria-label={`Cart, ${cart.count} items`}><ShoppingCart size={18} aria-hidden /> {cart.count}</Link>
            {me ? <Link to={me.role === 'customer' ? '/account' : '/manage'} className="btn sm secondary">{me.avatar ? <Avatar name={me.full_name || me.email} src={me.avatar} /> : <User size={18} aria-hidden />} <span className="hide-sm">Account</span></Link>
              : <><Link to="/login" className="btn sm secondary" aria-label="Log in"><User size={18} aria-hidden /> <span className="hide-sm">Log in</span></Link><Link to="/register" className="btn sm hide-sm">Sign up</Link></>}
            <button className="menu-btn" onClick={() => setOpen(true)} aria-label="Toggle menu" aria-expanded={open}><MenuIcon /></button>
          </div>
          </div>
        </div>
      </header>
      <MobileMenu open={open} onClose={() => setOpen(false)} brand={r.name} logo={logo} links={[...links, ['/faq', 'FAQ']]}>
        {me ? <Link to={me.role === 'customer' ? '/account' : '/manage'} className="btn">{me.role === 'customer' ? 'My account' : 'Open workspace'}</Link>
          : <><Link to="/login" className="btn secondary">Log in</Link><Link to="/register" className="btn">Sign up</Link></>}
        <Link to="/cart" className="btn secondary"><ShoppingCart size={18} aria-hidden /> Cart ({cart.count})</Link>
      </MobileMenu>
      <main><PageDesigns><Outlet /><PageBlocks page={pageIdOf(pathname)} placement="bottom" /></PageDesigns></main>
      <footer className="site-footer">
        <div className="container">
          {pathname !== '/' && pathname !== '/checkout' && pathname !== '/cart' && !pathname.startsWith('/pay') && (
            <div className="foot-cta">
              <div><h2>Hungry? Order from {r.name}</h2><p>Order your favourites online, or book a table.</p></div>
              <div className="foot-cta-actions"><Link className="btn lg" to="/menu">Order now <ArrowRight size={18} aria-hidden /></Link><Link className="btn lg outline" to="/reserve">Reserve a table</Link></div>
            </div>
          )}
          <div className="foot-cols">
            <div className="foot-about">
              <Link to="/" className="logo">{logo && <img src={logo} alt="" width={40} height={40} />}{r.name}</Link>
              {r.description && <p><RichText text={r.description} /></p>}
              <div className="foot-social">
                {r.contact_phone && <a href={`tel:${r.contact_phone}`} aria-label="Phone"><Phone size={18} aria-hidden /></a>}
                {r.contact_email && <a href={`mailto:${r.contact_email}`} aria-label="Email"><Mail size={18} aria-hidden /></a>}
              </div>
            </div>
            <nav className="foot-col" aria-label="Explore"><h4>Explore</h4><ul>{links.slice(0, 5).map(([to, l]) => <li key={to}><Link to={to}>{l}</Link></li>)}</ul></nav>
            <nav className="foot-col" aria-label="More"><h4>More</h4><ul>{links.slice(5).map(([to, l]) => <li key={to}><Link to={to}>{l}</Link></li>)}<li><Link to="/faq">FAQ</Link></li></ul></nav>
            <nav className="foot-col" aria-label="Policies"><h4>Policies</h4><ul>{site.policies.map((p) => <li key={p.slug}><Link to={`/policies/${p.slug}`}>{p.title}</Link></li>)}</ul></nav>
            <div className="foot-col foot-reach"><h4>Get in touch</h4><ul>
              {r.contact_phone && <li><Phone size={15} aria-hidden /> <a href={`tel:${r.contact_phone}`}>{r.contact_phone}</a></li>}
              {r.contact_email && <li><Mail size={15} aria-hidden /> <a href={`mailto:${r.contact_email}`}>{r.contact_email}</a></li>}
              {spotsOf(site).slice(0, 2).map((s) => <li key={s.key}><MapPin size={15} aria-hidden /> {mapQuery(s) ? <a href={directionsUrl(mapQuery(s))} target="_blank" rel="noopener noreferrer">{s.address || s.name}</a> : <span>{s.name}</span>}</li>)}
              <li><Mail size={15} aria-hidden /> <Link to="/contact">Send us a message</Link></li>
            </ul></div>
          </div>
          <div className="foot-base">
            <span>&copy; {new Date().getFullYear()} {r.name}. All rights reserved.</span>
            <nav aria-label="Staff"><Link to="/login">Staff sign in</Link></nav>
            <button type="button" className="to-top" onClick={() => window.scrollTo?.({ top: 0, behavior: 'smooth' })}><ArrowUp size={15} aria-hidden /> Back to top</button>
          </div>
        </div>
      </footer>
    </>
  )
}

const SITE_LINKS = [{ to: '/', label: 'Back to home' }, { to: '/menu', label: 'View the menu' }, { to: '/contact', label: 'Contact us' }]

function ManageHome() {
  const { me } = useAuth()
  if (me?.role === 'cashier') return <Navigate to="/manage/cashier" replace />
  return can(me?.role, 'manage.use') ? <Navigate to="/manage/dashboard" replace /> : <Navigate to="/manage/orders" replace />
}

export default function RestaurantApp() {
  return (
    <SiteProvider>
      <CartProvider>
      <Suspense fallback={<PageLoader />}>
<Routes>
        <Route element={<PublicLayout />}>
          <Route index element={<Home />} />
          <Route path="menu" element={<Menu />} />
          <Route path="menu/:slug" element={<ProductPage />} />
          <Route path="services" element={<Services />} />
          <Route path="gallery" element={<Gallery />} />
          <Route path="catering" element={<CateringRequestPage />} />
          <Route path="reserve" element={<ReservePage />} />
          <Route path="reservation/:token" element={<ReservationManage />} />
          <Route path="quotation/:token" element={<QuotationPage />} />
          <Route path="about" element={<About />} />
          <Route path="contact" element={<Contact />} />
          <Route path="faq" element={<Faq />} />
          <Route path="policies/:slug" element={<Policy />} />
          <Route path="cart" element={<CartPage />} />
          <Route path="payment-complete" element={<PaymentComplete />} />
          <Route path="pay/:paymentId" element={<PayPage />} />
          <Route path="checkout" element={<CheckoutPage />} />
          <Route path="*" element={<NotFound links={SITE_LINKS} />} />
        </Route>
        <Route path="account" element={<AccountLayout />}>
          <Route index element={<Overview />} />
          <Route path="orders" element={<MyOrders />} />
          <Route path="orders/:id" element={<OrderDetail />} />
          <Route path="profile" element={<CustomerProfile />} />
          <Route path="addresses" element={<Addresses />} />
          <Route path="security" element={<CustomerSecurity />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="notifications/:nid" element={<NotificationDetail />} />
          <Route path="support" element={<Support />} />
          <Route path="*" element={<NotFound title="That page is not part of your account" links={[{ to: '/account', label: 'Go to my account' }, { to: '/menu', label: 'Order food' }]} />} />
        </Route>
        <Route path="receipts/:id" element={<Receipt />} />
        <Route path="t/:token" element={<QRMenu />} />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="verify-email" element={<VerifyEmail />} />
        <Route path="setup-password" element={<SetupPassword />} />
        <Route path="forgot-password" element={<ForgotPassword />} />
        <Route path="manage" element={<ManageLayout />}>
          <Route index element={<ManageHome />} />
          <Route path="products" element={<Products />} />
          <Route path="orders" element={<ManageOrders />} />
          <Route path="cashier" element={<Cashier />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="branches" element={<Branches />} />
          <Route path="tables" element={<Tables />} />
          <Route path="catering" element={<CateringAdmin />} />
          <Route path="kitchen" element={<Kitchen />} />
          <Route path="customers" element={<Customers />} />
          <Route path="floor" element={<Floor />} />
          <Route path="stock" element={<Stock />} />
          <Route path="finance" element={<Finance />} />
          <Route path="security" element={<SecurityMfa />} />
          <Route path="profile" element={<ProfileSettings />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="notifications/:nid" element={<NotificationDetail />} />
          <Route path="payroll" element={<Payroll />} />
          <Route path="reports" element={<Reports />} />
          <Route path="my-pay" element={<MyPay />} />
          <Route path="tables/print" element={<TablesPrint />} />
          <Route path="staff" element={<Staff />} />
          <Route path="shifts" element={<Shifts />} />
          <Route path="categories" element={<Categories />} />
          <Route path="inventory" element={<Inventory />} />
          <Route path="services" element={<ServicesAdmin />} />
          <Route path="gallery" element={<GalleryAdmin />} />
          <Route path="site" element={<SiteContent />} />
          <Route path="builder" element={<PageBuilder />} />
          <Route path="*" element={<NotFound title="That page is not part of the workspace" links={[{ to: '/manage', label: 'Go to the workspace' }, { to: '/', label: 'View website' }]} />} />
          <Route path="website-contact" element={<WebsiteMessages subtitle="Messages sent through your restaurant website’s contact form." />} />
        </Route>
      </Routes>
</Suspense>
      </CartProvider>
    </SiteProvider>
  )
}

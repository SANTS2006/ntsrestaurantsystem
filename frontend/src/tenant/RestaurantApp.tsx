import { Menu as MenuIcon, ShoppingCart, User, X } from 'lucide-react'
import { useState, Suspense, lazy } from 'react'
import { Link, NavLink, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { API_URL } from '../lib/config'
import { useAuth } from '../lib/auth'
import { can } from '../lib/permissions'
import { NotificationBell, ThemeToggle } from '../ui/TopTools'
import { Avatar } from '../ui/Shell'
import { ScrollFx } from '../ui/fx'
import { CartProvider, useCart } from './cart'
import { Login, Register, VerifyEmail } from './CustomerAuth'
import { CartPage, CheckoutPage } from './shop'
import { Empty, PageLoader } from '../ui/kit'
import { About, Contact, Faq, Gallery, Home, Menu, Policy, ProductPage, Services } from './pages'
import { SiteProvider, useSite } from './SiteContext'
import { ForgotPassword, SetupPassword } from './StaffAuth'
import { BackButton } from '../ui/BackButton'

const AccountLayout = lazy(() => import('./account/pages').then((m) => ({ default: m.AccountLayout })))
const Addresses = lazy(() => import('./account/pages').then((m) => ({ default: m.Addresses })))
const MyOrders = lazy(() => import('./account/pages').then((m) => ({ default: m.Orders })))
const OrderDetail = lazy(() => import('./account/pages').then((m) => ({ default: m.OrderDetail })))
const Overview = lazy(() => import('./account/pages').then((m) => ({ default: m.Overview })))
const Profile = lazy(() => import('./account/pages').then((m) => ({ default: m.Profile })))
const Security = lazy(() => import('./account/pages').then((m) => ({ default: m.Security })))
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
const SiteContent = lazy(() => import('./manage/pages').then((m) => ({ default: m.SiteContent })))
const Receipt = lazy(() => import('./Receipt'))

const links = [['/', 'Home'], ['/menu', 'Menu'], ['/services', 'Services'], ['/catering', 'Catering'], ['/reserve', 'Reserve'], ['/gallery', 'Gallery'], ['/about', 'About'], ['/contact', 'Contact']] as const

function PublicLayout() {
  const { site } = useSite()
  const [open, setOpen] = useState(false)
  const r = site.restaurant
  const cart = useCart()
  const { me } = useAuth()
  const logo = r.logo ? (r.logo.startsWith('http') ? r.logo : `${API_URL}${r.logo}`) : null
  return (
    <>
      <ScrollFx />
      <header className="nav">
        <div className="container row">
          <Link to="/" className="logo" aria-label={r.name}>{logo && <img src={logo} alt="" height={36} />}<span className="logo-name">{r.name}</span></Link>
          <nav className={`links ${open ? 'open' : ''}`} aria-label="Main">
            {links.map(([to, l]) => <NavLink key={to} to={to} end={to === '/'} onClick={() => setOpen(false)}>{l}</NavLink>)}
          </nav>
          <div className="nav-end">
          <div className="secret" aria-hidden="true" />
          <div className="actions">
            <ThemeToggle />
            {me && <NotificationBell />}
            <Link to="/cart" className="btn sm secondary" aria-label={`Cart, ${cart.count} items`}><ShoppingCart size={18} aria-hidden /> {cart.count}</Link>
            {me ? <Link to={me.role === 'customer' ? '/account' : '/manage'} className="btn sm secondary">{me.avatar ? <Avatar name={me.full_name || me.email} src={me.avatar} /> : <User size={18} aria-hidden />} <span className="hide-sm">Account</span></Link>
              : <><Link to="/login" className="btn sm secondary" aria-label="Log in"><User size={18} aria-hidden /> <span className="hide-sm">Log in</span></Link><Link to="/register" className="btn sm hide-sm">Sign up</Link></>}
            <button className="menu-btn" onClick={() => setOpen(!open)} aria-label="Toggle menu" aria-expanded={open}>{open ? <X /> : <MenuIcon />}</button>
          </div>
          </div>
        </div>
      </header>
      <main><Outlet /></main>
      <footer className="footer">
        <div className="container">
          <div className="foot-grid">
            <div className="foot-brand">
              <Link to="/" className="logo">{logo && <img src={logo} alt="" width={36} height={36} />}{r.name}</Link>
              <p>{r.description}</p>
            </div>
            <div className="foot-explore"><h4>Explore</h4><ul className="foot-links">{links.map(([to, l]) => <li key={to}><Link to={to}>{l}</Link></li>)}<li><Link to="/faq">FAQ</Link></li></ul></div>
            <div><h4>Policies</h4><ul>{site.policies.map((p) => <li key={p.slug}><Link to={`/policies/${p.slug}`}>{p.title}</Link></li>)}</ul></div>
            <div><h4>Contact</h4><div className="foot-contact">
              {r.contact_phone && <a href={`tel:${r.contact_phone}`}>{r.contact_phone}</a>}
              {r.contact_email && <a href={`mailto:${r.contact_email}`}>{r.contact_email}</a>}
              {(r.address || r.city) && <span>{[r.address, r.city].filter(Boolean).join(', ')}</span>}
              {!r.contact_phone && !r.contact_email && !r.address && !r.city && <Link to="/contact">Contact us</Link>}
            </div></div>
          </div>
          <div className="foot-bottom">
            <span>&copy; {new Date().getFullYear()} {r.name}. All rights reserved.</span>
            <nav aria-label="Staff"><Link to="/login">Staff sign in</Link></nav>
          </div>
        </div>
      </footer>
    </>
  )
}

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
          <Route path="payment-complete" element={<div className="container section"><Empty title="Thank you">Your payment page is complete. You can return to the counter: the restaurant confirms the payment automatically.</Empty></div>} />
          <Route path="checkout" element={<CheckoutPage />} />
          <Route path="account" element={<AccountLayout />}>
            <Route index element={<Overview />} />
            <Route path="orders" element={<MyOrders />} />
            <Route path="orders/:id" element={<OrderDetail />} />
            <Route path="profile" element={<Profile />} />
            <Route path="addresses" element={<Addresses />} />
            <Route path="security" element={<Security />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="notifications/:nid" element={<NotificationDetail />} />
            <Route path="support" element={<Support />} />
          </Route>
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
        </Route>
        <Route path="*" element={<div className="container section"><Empty title="Page not found"><BackButton to="/">Back to home</BackButton></Empty></div>} />
      </Routes>
</Suspense>
      </CartProvider>
    </SiteProvider>
  )
}

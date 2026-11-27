import { Banknote, BarChart3, Bell, Boxes, Building2, CalendarDays, ChefHat, Contact, Grid3x3, HandCoins, Inbox, LayoutTemplate, Truck, Clock, FileBarChart, Image, Package, QrCode, Receipt, Settings, Store, Tags, Users, Wallet, ShieldCheck } from 'lucide-react'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { API_URL } from '../../lib/config'
import { useAuth } from '../../lib/auth'
import { useNotifications } from '../../lib/live'
import { STAFF_ALL, can, canOpen } from '../../lib/permissions'
import { Empty, PageLoader } from '../../ui/kit'
import { MfaSettings } from '../../ui/Mfa'
import Shell, { type NavGroup } from '../../ui/Shell'
import { useSite } from '../SiteContext'

const LABEL: Record<string, string> = { restaurant_admin: 'Administrator', manager: 'Manager', cashier: 'Cashier', kitchen: 'Kitchen', waiter: 'Waiter', waitress: 'Waitress', delivery: 'Delivery', platform_admin: 'Platform admin' }

export default function ManageLayout() {
  const { me, loading, signOut } = useAuth()
  const loc = useLocation()
  const { unread } = useNotifications()
  const { site } = useSite()
  if (loading) return <PageLoader />
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  const role = me.role ?? ''
  const manage = can(role, 'manage.use')
  const admin = can(role, 'admin.use')
  // The menu only decides what to SHOW; every endpoint enforces roles and branches on the server.
  const groups: NavGroup[] = [
    { label: 'Service', items: [
      ...(manage ? [{ to: '/manage/dashboard', label: 'Dashboard', icon: BarChart3 }] : []),
      ...(can(role, 'pos.use') ? [{ to: '/manage/cashier', label: 'Point of sale', icon: Banknote }] : []),
      ...(can(role, 'orders.view') ? [{ to: '/manage/orders', label: 'Orders', icon: Receipt }] : []),
      ...(can(role, 'kitchen.use') ? [{ to: '/manage/kitchen', label: 'Kitchen display', icon: ChefHat }] : []),
      ...(can(role, 'floor.use') ? [{ to: '/manage/floor', label: 'Floor and bookings', icon: Grid3x3 }] : []),
      ...(manage ? [{ to: '/manage/tables', label: 'Tables and QR', icon: QrCode }, { to: '/manage/catering', label: 'Catering', icon: CalendarDays }, { to: '/manage/shifts', label: 'Shifts', icon: Clock }] : []),
    ] },
    { label: 'Menu and stock', items: manage ? [
      { to: '/manage/products', label: 'Products', icon: Package }, { to: '/manage/categories', label: 'Categories', icon: Tags }, { to: '/manage/inventory', label: 'Inventory', icon: Boxes },
      { to: '/manage/stock', label: 'Stock and purchasing', icon: Truck },
    ] : [] },
    { label: 'Business', items: [
      ...(manage ? [{ to: '/manage/reports', label: 'Reports', icon: FileBarChart }, { to: '/manage/finance', label: 'Expenses and invoices', icon: HandCoins }, { to: '/manage/customers', label: 'Customers', icon: Contact }, { to: '/manage/staff', label: 'Staff', icon: Users }] : []),
      ...(admin ? [{ to: '/manage/branches', label: 'Branches', icon: Building2 }] : []),
      ...(manage ? [{ to: '/manage/payroll', label: 'Payroll', icon: Wallet }] : []),
      ...(can(role, 'mypay.view') ? [{ to: '/manage/my-pay', label: 'My pay', icon: Wallet }] : []),
      { to: '/manage/notifications', label: 'Notifications', icon: Bell, count: unread || undefined },
      { to: '/manage/security', label: 'Security', icon: ShieldCheck },
    ] },
    { label: 'Website', items: manage ? [
      { to: '/manage/website-contact', label: 'Website contact', icon: Inbox },
      { to: '/manage/services', label: 'Services', icon: Store }, { to: '/manage/gallery', label: 'Gallery', icon: Image },
      ...(admin ? [{ to: '/manage/site', label: 'Website content', icon: Settings }, { to: '/manage/builder', label: 'Page builder', icon: LayoutTemplate }] : []),
    ] : [] },
  ]
  const logo = site.restaurant.logo ? (site.restaurant.logo.startsWith('http') ? site.restaurant.logo : `${API_URL}${site.restaurant.logo}`) : null
  return (
    <Shell brand={site.restaurant.name} tagline="Restaurant workspace" logo={logo} groups={groups} user={{ name: me.full_name || me.email, role: LABEL[role] ?? role, email: me.email, avatar: me.avatar }} onLogout={() => void signOut()} profilePath="/manage/profile" footerLink={{ to: '/', label: 'View website' }}>
      {me.mfa?.enforced && me.mfa.required && !me.mfa.enabled ? <MfaSettings forced /> : STAFF_ALL.includes(role) ? (canOpen(role, loc.pathname.split('/')[2] ?? '') ? <Outlet /> : <Empty title="This page is not available for your role">Ask the restaurant administrator if you need access. <Link to="/manage/orders">Go to orders</Link></Empty>) : <Empty title="No access">This area is for restaurant staff. <Link to="/account">Go to your account</Link></Empty>}
    </Shell>
  )
}


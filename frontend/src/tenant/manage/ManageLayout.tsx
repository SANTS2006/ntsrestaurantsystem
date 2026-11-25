import { Banknote, BarChart3, Boxes, Building2, CalendarDays, ChefHat, Contact, Grid3x3, HandCoins, Truck, Clock, FileBarChart, Image, Package, QrCode, Receipt, Settings, Store, Tags, Users, Wallet, ShieldCheck } from 'lucide-react'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { API_URL } from '../../lib/config'
import { useAuth } from '../../lib/auth'
import { Empty, PageLoader } from '../../ui/kit'
import { MfaSettings } from '../../ui/Mfa'
import Shell, { type NavGroup } from '../../ui/Shell'
import { useSite } from '../SiteContext'

const CATALOG_ROLES = ['restaurant_admin', 'manager', 'platform_admin']
const STAFF = ['restaurant_admin', 'manager', 'cashier', 'kitchen', 'waiter', 'waitress', 'delivery', 'platform_admin']
const TILL = ['cashier', 'manager', 'restaurant_admin', 'platform_admin']
const KITCHEN = ['kitchen', 'manager', 'restaurant_admin', 'platform_admin', 'cashier']
const LABEL: Record<string, string> = { restaurant_admin: 'Administrator', manager: 'Manager', cashier: 'Cashier', kitchen: 'Kitchen', waiter: 'Waiter', waitress: 'Waitress', delivery: 'Delivery', platform_admin: 'Platform admin' }

const MANAGE_ONLY = ['dashboard', 'customers', 'stock', 'finance', 'tables', 'catering', 'shifts', 'products', 'categories', 'inventory', 'reports', 'staff', 'payroll', 'services', 'gallery']
const ADMIN_ONLY = ['branches', 'site']

/** UI gate for a friendlier screen than a raw 403; the API still enforces every role and branch rule. */
function allowed(role: string, section: string) {
  if (MANAGE_ONLY.includes(section)) return CATALOG_ROLES.includes(role)
  if (ADMIN_ONLY.includes(section)) return role === 'restaurant_admin' || role === 'platform_admin'
  if (section === 'cashier') return TILL.includes(role)
  if (section === 'kitchen') return KITCHEN.includes(role)
  if (section === 'floor') return TILL.includes(role)
  return true
}

export default function ManageLayout() {
  const { me, loading, signOut } = useAuth()
  const loc = useLocation()
  const { site } = useSite()
  if (loading) return <PageLoader />
  if (!me) return <Navigate to="/login" replace />
  const role = me.role ?? ''
  const manage = CATALOG_ROLES.includes(role)
  const admin = role === 'restaurant_admin' || role === 'platform_admin'
  // The menu only decides what to SHOW; every endpoint enforces roles and branches on the server.
  const groups: NavGroup[] = [
    { label: 'Service', items: [
      ...(manage ? [{ to: '/manage/dashboard', label: 'Dashboard', icon: BarChart3 }] : []),
      ...(TILL.includes(role) ? [{ to: '/manage/cashier', label: 'Point of sale', icon: Banknote }] : []),
      { to: '/manage/orders', label: 'Orders', icon: Receipt },
      ...(KITCHEN.includes(role) ? [{ to: '/manage/kitchen', label: 'Kitchen display', icon: ChefHat }] : []),
      ...(TILL.includes(role) ? [{ to: '/manage/floor', label: 'Floor and bookings', icon: Grid3x3 }] : []),
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
      { to: '/manage/my-pay', label: 'My pay', icon: Wallet },
      { to: '/manage/security', label: 'Security', icon: ShieldCheck },
    ] },
    { label: 'Website', items: manage ? [
      { to: '/manage/services', label: 'Services', icon: Store }, { to: '/manage/gallery', label: 'Gallery', icon: Image },
      ...(admin ? [{ to: '/manage/site', label: 'Website content', icon: Settings }] : []),
    ] : [] },
  ]
  const logo = site.restaurant.logo ? (site.restaurant.logo.startsWith('http') ? site.restaurant.logo : `${API_URL}${site.restaurant.logo}`) : null
  return (
    <Shell brand={site.restaurant.name} tagline="Restaurant workspace" logo={logo} groups={groups} user={{ name: me.full_name || me.email, role: LABEL[role] ?? role, email: me.email, avatar: me.avatar }} onLogout={() => void signOut()} profilePath="/manage/profile" footerLink={{ to: '/', label: 'View website' }}>
      {me.mfa?.enforced && me.mfa.required && !me.mfa.enabled ? <MfaSettings forced /> : STAFF.includes(role) ? (allowed(role, loc.pathname.split('/')[2] ?? '') ? <Outlet /> : <Empty title="This page is not available for your role">Ask the restaurant administrator if you need access. <Link to="/manage/orders">Go to orders</Link></Empty>) : <Empty title="No access">This area is for restaurant staff. <Link to="/account">Go to your account</Link></Empty>}
    </Shell>
  )
}


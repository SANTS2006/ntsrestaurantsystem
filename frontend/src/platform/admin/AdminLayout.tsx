import { Activity, BarChart3, Bell, CreditCard, LayoutDashboard, ScrollText, Settings, ShieldCheck, Store } from 'lucide-react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../../lib/auth'
import { PageLoader } from '../../ui/kit'
import { MfaSettings } from '../../ui/Mfa'
import Shell, { type NavGroup } from '../../ui/Shell'

const groups: NavGroup[] = [
  { label: 'Platform', items: [
    { to: '/admin', label: 'Dashboard', icon: LayoutDashboard, end: true },
    { to: '/admin/restaurants', label: 'Restaurants', icon: Store },
    { to: '/admin/plans', label: 'Plans', icon: CreditCard },
  ] },
  { label: 'Insight', items: [{ to: '/admin/reports', label: 'Reports', icon: BarChart3 }, { to: '/admin/audit', label: 'Audit log', icon: ScrollText }, { to: '/admin/system', label: 'System', icon: Activity }] },
  { label: 'Configuration', items: [{ to: '/admin/notifications', label: 'Notifications', icon: Bell }, { to: '/admin/settings', label: 'Settings', icon: Settings }, { to: '/admin/security', label: 'Security', icon: ShieldCheck }] },
]

export default function AdminLayout() {
  const { me, loading, signOut } = useAuth()
  if (loading) return <PageLoader />
  // UI gate only; every admin endpoint independently enforces platform-admin access on the server.
  if (me?.role !== 'platform_admin') return <Navigate to="/login" replace />
  const gated = me.mfa?.enforced && me.mfa.required && !me.mfa.enabled
  return <Shell brand="Platform" tagline="Administration" logo="/logo-64.png" groups={groups} user={{ name: me.full_name || me.email, role: 'Platform admin', email: me.email, avatar: me.avatar }} onLogout={() => void signOut()} profilePath="/admin/profile">{gated ? <MfaSettings forced /> : undefined}</Shell>
}

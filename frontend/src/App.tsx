import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { IS_PLATFORM_SITE } from './lib/config'
import ForgotPasswordPage from './platform/ForgotPassword'
import Login from './platform/Login'
import { About, Contact, Faq, Features, Home, Legal, Pricing } from './platform/site/Pages'
import SiteLayout from './platform/site/SiteLayout'
import RestaurantApp from './tenant/RestaurantApp'
import { PageLoader } from './ui/kit'
import { NotFound } from './ui/NotFound'

const AdminLayout = lazy(() => import('./platform/admin/AdminLayout'))
const Dashboard = lazy(() => import('./platform/admin/Dashboard'))
const AuditLog = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.AuditLog })))
const PlatformReports = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.PlatformReports })))
const PlatformSettings = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.PlatformSettings })))
const Plans = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.Plans })))
const Restaurants = lazy(() => import('./platform/admin/Restaurants'))
const Security = lazy(() => import('./ui/Mfa').then((m) => ({ default: m.MfaSettings })))
const Profile = lazy(() => import('./ui/Profile').then((m) => ({ default: m.ProfileSettings })))
const Notifications = lazy(() => import('./ui/Notifications').then((m) => ({ default: m.NotificationsPage })))
const NotificationDetail = lazy(() => import('./ui/Notifications').then((m) => ({ default: m.NotificationDetailPage })))
const System = lazy(() => import('./platform/admin/System'))
const WebsiteMessages = lazy(() => import('./ui/WebsiteMessages'))
const PageBuilder = lazy(() => import('./ui/builder/Builder'))
const PlatformContent = lazy(() => import('./platform/admin/WebsiteContent'))

const SITE_LINKS = [{ to: '/', label: 'Back to home' }, { to: '/features', label: 'See features' }, { to: '/contact', label: 'Contact us' }]

export default function App() {
  if (!IS_PLATFORM_SITE) {
    return <Routes><Route path="*" element={<RestaurantApp />} /></Routes>
  }
  return (
    <Suspense fallback={<PageLoader />}>
    <Routes>
      <Route element={<SiteLayout />}>
        <Route index element={<Home />} />
        <Route path="features" element={<Features />} />
        <Route path="pricing" element={<Pricing />} />
        <Route path="about" element={<About />} />
        <Route path="faq" element={<Faq />} />
        <Route path="contact" element={<Contact />} />
        <Route path="legal/:slug" element={<Legal />} />
        <Route path="*" element={<NotFound links={SITE_LINKS} />} />
      </Route>
      <Route path="login" element={<Login />} />
      <Route path="forgot-password" element={<ForgotPasswordPage />} />
      <Route path="admin" element={<AdminLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="restaurants" element={<Restaurants />} />
        <Route path="plans" element={<Plans />} />
        <Route path="reports" element={<PlatformReports />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="system" element={<System />} />
        <Route path="security" element={<Security />} />
        <Route path="profile" element={<Profile />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="notifications/:nid" element={<NotificationDetail />} />
        <Route path="settings" element={<PlatformSettings />} />
        <Route path="messages" element={<WebsiteMessages subtitle="Messages sent through the main website’s contact form." />} />
        <Route path="website" element={<PlatformContent />} />
        <Route path="builder" element={<PageBuilder />} />
        <Route path="*" element={<NotFound title="That page is not part of the admin area" links={[{ to: '/admin', label: 'Go to the dashboard' }]} />} />
      </Route>
    </Routes>
    </Suspense>
  )
}

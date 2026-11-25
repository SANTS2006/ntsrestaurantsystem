import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { IS_PLATFORM_SITE } from './lib/config'
import Login from './platform/Login'
import { About, Contact, Faq, Features, Home, Legal, Pricing } from './platform/site/Pages'
import SiteLayout from './platform/site/SiteLayout'
import RestaurantApp from './tenant/RestaurantApp'
import { Empty, PageLoader } from './ui/kit'

const AdminLayout = lazy(() => import('./platform/admin/AdminLayout'))
const Dashboard = lazy(() => import('./platform/admin/Dashboard'))
const AuditLog = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.AuditLog })))
const PlatformReports = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.PlatformReports })))
const PlatformSettings = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.PlatformSettings })))
const Plans = lazy(() => import('./platform/admin/Misc').then((m) => ({ default: m.Plans })))
const Restaurants = lazy(() => import('./platform/admin/Restaurants'))
const Security = lazy(() => import('./ui/Mfa').then((m) => ({ default: m.MfaSettings })))
const Profile = lazy(() => import('./ui/Profile').then((m) => ({ default: m.ProfileSettings })))
const System = lazy(() => import('./platform/admin/System'))

function NotFound() {
  return <div className="container section"><Empty title="Page not found" /></div>
}

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
      </Route>
      <Route path="login" element={<Login />} />
      <Route path="admin" element={<AdminLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="restaurants" element={<Restaurants />} />
        <Route path="plans" element={<Plans />} />
        <Route path="reports" element={<PlatformReports />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="system" element={<System />} />
        <Route path="security" element={<Security />} />
        <Route path="profile" element={<Profile />} />
        <Route path="settings" element={<PlatformSettings />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
    </Suspense>
  )
}

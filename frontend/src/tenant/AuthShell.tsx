import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { API_URL } from '../lib/config'
import { AuthLayout } from '../ui/Auth'
import { useDocumentTitle } from '../ui/kit'
import { useSite } from './SiteContext'

/** Sign-in, register and password pages of a restaurant, in the restaurant's own name, logo and colours. */
export function Shell({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  const { site } = useSite()
  const r = site.restaurant
  useDocumentTitle(`${title} | ${r.name}`)
  const logo = r.logo ? (r.logo.startsWith('http') ? r.logo : `${API_URL}${r.logo}`) : null
  return (
    <AuthLayout
      brand={r.name}
      logo={logo}
      tagline={r.description || `Welcome to ${r.name}`}
      title={title}
      subtitle={subtitle}
      back={<Link to="/">&larr; Back to {r.name}</Link>}
      footer={footer}
    >
      {children}
    </AuthLayout>
  )
}

// The API is called on the same origin as the page, under the restaurant's path prefix (the backend reads the slug from the URL).
// Production: the backend serves this app, so the API is on the same origin (VITE_API_URL is empty at build time).
// Development: http://localhost:8000 next to the Vite server on :5173 (open http://localhost:5173/<slug>).
const meta = (name: string): string | undefined => document.querySelector(`meta[name="${name}"]`)?.getAttribute('content') ?? undefined

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? `${window.location.protocol}//${window.location.hostname}:8000`
/** Absolute origin for `new URL(...)` and WebSocket addresses (API_URL is empty when the API is on the same origin). */
export const API_ORIGIN: string = API_URL || window.location.origin

// Hostnames that serve the platform (marketing site + platform admin). Anything else is a restaurant tenant.
// The server injects them as a <meta> tag, so one build works for any domain.
const PLATFORM_HOSTS: string[] = (meta('platform-hosts') || (import.meta.env.VITE_PLATFORM_HOSTS as string | undefined) || 'localhost')
  .split(',')
  .map((h) => h.trim().toLowerCase())
  .filter(Boolean)

export const GOOGLE_CLIENT_ID: string | undefined = meta('google-client-id') || (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) || undefined

export function isPlatformHost(hostname: string = window.location.hostname): boolean {
  return PLATFORM_HOSTS.includes(hostname.toLowerCase())
}

// Restaurants live under a path: https://<platform domain>/<slug>/menu. The first path segment is the restaurant slug unless it is one of
// the platform's own pages. (A verified custom domain has no prefix.) The router uses TENANT_BASE as its basename, so every in-app link
// and every API / WebSocket address is prefixed automatically. Keep this list in step with RESERVED_SLUGS in backend/apps/tenants/models.py.
const PLATFORM_ROUTES = new Set(['', 'features', 'pricing', 'about', 'faq', 'contact', 'legal', 'login', 'admin', 'forgot-password', 'register', 'terms', 'privacy'])
export function tenantBase(pathname: string = window.location.pathname, hostname: string = window.location.hostname): string {
  if (!isPlatformHost(hostname)) return ''
  const first = pathname.split('/')[1]?.toLowerCase() ?? ''
  return PLATFORM_ROUTES.has(first) ? '' : `/${first}`
}
export const TENANT_BASE: string = tenantBase()
/** True on the marketing site and platform admin (the platform host without a restaurant slug). */
export const IS_PLATFORM_SITE: boolean = isPlatformHost() && TENANT_BASE === ''
/** Root of every API call of this page: same origin in production, the Django dev server in development. */
export const API_BASE: string = `${API_URL}${TENANT_BASE}`

// The API must be called on the SAME hostname as the page, because the backend resolves the restaurant from the Host header.
// Production: the backend serves this app, so the API is on the same origin (VITE_API_URL is empty at build time).
// Development: <slug>.localhost:8000 next to the Vite server on :5173.
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

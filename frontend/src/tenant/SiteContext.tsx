import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { api } from '../lib/api'
import { ErrorState, Skeleton, useAsync } from '../ui/kit'

export type Variation = { id: number; kind: string; name: string; price_delta: string; is_default: boolean }
export type Addon = { id: number; name: string; price: string; max_quantity: number }
export type PublicProduct = {
  id: number; slug: string; name: string; description: string; image: string | null; price: string; regular_price: string
  offer_label: string; on_offer: boolean; is_featured: boolean; is_popular: boolean; prep_time_minutes: number | null
  ingredients: string[]; allow_instructions: boolean; sold_out: boolean; category_slug: string; category_name: string
  variations: Variation[]; addons: Addon[]
}
export type MenuCategory = { id: number; slug: string; name: string; description: string; products: PublicProduct[] }
export type Site = {
  restaurant: { name: string; slug: string; logo: string | null; primary_color: string; secondary_color: string; description: string; contact_email: string; contact_phone: string; address: string; city: string; country: string }
  url: string; hero_title: string; hero_subtitle: string; about_text: string; delivery_info: string; faqs: { q: string; a: string }[]
  currency: string; online_payments: boolean; delivery_enabled: boolean; pickup_enabled: boolean; seo_title: string; seo_description: string
  branches: { id: number; name: string; address: string; phone: string; email: string; operating_hours: Record<string, string> }[]
  policies: { slug: string; title: string }[]
}

type Ctx = { site: Site; money: (v: string | number) => string }
const SiteCtx = createContext<Ctx | null>(null)
export const useSite = () => {
  const c = useContext(SiteCtx)
  if (!c) throw new Error('useSite outside SiteProvider')
  return c
}

export function formatMoney(value: string | number, currency: string): string {
  const n = Number(value)
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(n)
  } catch {
    return `${currency} ${n.toFixed(2)}`
  }
}

/** Loads the restaurant's public data once and applies its brand colours to the whole page. */
export function SiteProvider({ children }: { children: ReactNode }) {
  const { data, loading, error, reload } = useAsync(() => api<Site>('/catalog/public/site/', { auth: false }), [])
  useEffect(() => {
    if (!data) return
    const r = document.documentElement.style
    r.setProperty('--brand', data.restaurant.primary_color)
    r.setProperty('--brand-2', data.restaurant.secondary_color)
    return () => { r.removeProperty('--brand'); r.removeProperty('--brand-2') }
  }, [data])
  const value = useMemo(() => (data ? { site: data, money: (v: string | number) => formatMoney(v, data.currency) } : null), [data])
  if (loading) return <div className="container section"><Skeleton h={48} /><div style={{ height: 16 }} /><Skeleton h={200} /></div>
  if (error || !value) return <div className="container section"><ErrorState message={error ?? 'Restaurant not found.'} onRetry={reload} /></div>
  return <SiteCtx.Provider value={value}>{children}</SiteCtx.Provider>
}

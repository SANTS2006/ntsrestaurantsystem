// The texts of the platform website. The server holds the defaults and whatever the platform owner changed in "Website content".
import { createContext, useContext } from 'react'

export type Titled = { title: string; text: string }
export type Question = { q: string; a: string }
export type PlatformLocation = { name: string; address: string; latitude: string; longitude: string; phone: string; hours: string }

export type SiteTexts = {
  footer: { about: string; cta_title: string; cta_text: string; cta_button: string }
  home: {
    pill: string; title: string; title_highlight: string; lead: string; primary_button: string; secondary_button: string; perks: { text: string }[]
    features_eyebrow: string; features_title: string; features_text: string; steps_eyebrow: string; steps_title: string; steps: Titled[]
    security_title: string; security_text: string; pricing_title: string; cta_title: string; cta_text: string
  }
  features: { eyebrow: string; title: string; lead: string; items: Titled[] }
  pricing: { eyebrow: string; title: string; lead: string; note: string }
  about: { eyebrow: string; title: string; lead: string; sections: Titled[] }
  faq: { eyebrow: string; title: string; lead: string; items: Question[] }
  contact: { eyebrow: string; title: string; lead: string; form_title: string; phone: string; hours: string; locations: PlatformLocation[] }
  legal: Record<string, Titled[]>
  seo: Record<'home' | 'features' | 'pricing' | 'about' | 'faq' | 'contact', Titled>
}

export type PlatformSite = { content: SiteTexts; images: Partial<Record<string, string>>; draft_legal: string[] }

export const SiteTextsContext = createContext<PlatformSite | null>(null)
/** The website's texts. Only for pages inside the platform website layout, which renders them after the texts have loaded. */
export function useSiteTexts(): PlatformSite {
  const c = useContext(SiteTextsContext)
  if (!c) throw new Error('useSiteTexts outside the platform website')
  return c
}

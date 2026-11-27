// The page builder's data. The server checks all of it again (backend/apps/website/builder.py).
import type { ModelKind } from '../Scene3D'

export type Layout = 'cards' | 'accordion' | 'carousel' | 'split' | 'gallery' | 'banner' | 'text'
export type ModelChoice = 'auto' | 'none' | ModelKind
export type Pictured = { image: number | null; image_url?: string | null }
export type Linked = { button_label: string; button_link: string }
export type Item = Pictured & Linked & { title: string; text: string }
export type Block = Pictured & Linked & {
  layout: Layout; placement: 'top' | 'bottom'; background: 'plain' | 'soft' | 'brand' | 'dark'; animation: 'rise' | 'zoom' | 'left' | 'right' | 'flip' | 'none'
  columns: 2 | 3 | 4; model: Exclude<ModelChoice, 'auto'>; visible: boolean; autoplay: boolean; eyebrow: string; title: string; text: string; items: Item[]
}
export type Hero = Pictured & Linked & { eyebrow: string; title: string; lead: string; model: ModelChoice }
export type Design = { hero: Hero; blocks: Block[] }

export const LAYOUTS: { id: Layout; label: string; hint: string; items: boolean }[] = [
  { id: 'cards', label: 'Cards', hint: 'A grid of cards, each with a picture, title, text and button.', items: true },
  { id: 'carousel', label: 'Carousel', hint: 'Slides visitors can swipe or step through.', items: true },
  { id: 'accordion', label: 'Accordion', hint: 'Titles that open to show their text. Good for questions and details.', items: true },
  { id: 'split', label: 'Picture and text', hint: 'Text beside a large picture or a 3D model.', items: false },
  { id: 'gallery', label: 'Picture gallery', hint: 'A wall of pictures with captions.', items: true },
  { id: 'banner', label: 'Banner', hint: 'A bold strip with a message and a button.', items: false },
  { id: 'text', label: 'Text', hint: 'A heading and paragraphs.', items: false },
]
export const MODEL_NAMES: [ModelChoice, string][] = [['auto', 'Suggested for this page'], ['none', 'No 3D model'], ['cloche', 'Serving dome'], ['burger', 'Burger'], ['drink', 'Cold drink'], ['cake', 'Celebration cake'], ['globe', 'Globe']]

const SUGGESTED: Record<string, ModelKind> = {
  home: 'cloche', features: 'globe', pricing: 'cake', about: 'cloche', faq: 'drink', contact: 'globe', menu: 'burger', services: 'cloche', gallery: 'cake', catering: 'cake', reserve: 'drink',
}

/** The 3D model a page shows: the owner's choice, or the one suggested for the page. */
export function modelFor(page: string, choice?: ModelChoice | null): ModelKind | null {
  if (choice === 'none') return null
  if (choice && choice !== 'auto') return choice
  return SUGGESTED[page] ?? null
}

/** Which designed page an address of a website shows; empty for pages the builder does not cover (cart, a single dish, policies...). */
export function pageIdOf(pathname: string): string {
  const [first = '', second] = pathname.replace(/^\/+|\/+$/g, '').split('/')
  if (!first) return 'home'
  if (first === 'legal') return 'legal'
  return second ? '' : first
}

export const emptyHero = (): Hero => ({ eyebrow: '', title: '', lead: '', button_label: '', button_link: '', model: 'auto', image: null })
export const emptyItem = (): Item => ({ title: '', text: '', image: null, button_label: '', button_link: '' })
export const newBlock = (layout: Layout): Block => ({
  layout, placement: 'bottom', background: layout === 'banner' ? 'brand' : 'plain', animation: 'rise', columns: 3, model: 'none', visible: true, autoplay: false,
  eyebrow: '', title: '', text: '', image: null, button_label: '', button_link: '', items: LAYOUTS.find((l) => l.id === layout)?.items ? [emptyItem()] : [],
})

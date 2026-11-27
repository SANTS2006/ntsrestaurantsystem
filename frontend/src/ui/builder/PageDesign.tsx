import { ArrowRight, ChevronLeft, ChevronRight } from 'lucide-react'
import { Suspense, createContext, lazy, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { useAsync } from '../kit'
import { Rise, Tilt } from '../fx'
import { Paragraphs, RichText } from '../RichText'
import { plain } from '../boldText'
import type { Block, Design, Item } from './types'

const Scene3D = lazy(() => import('../Scene3D'))

const Designs = createContext<Record<string, Design>>({})

/** Loads what the owner built for this website. The pages work without it, so a failure here changes nothing. */
export function PageDesigns({ children }: { children: ReactNode }) {
  const { data } = useAsync(() => api<{ pages: Record<string, Design> }>('/website/public/pages/', { auth: false }), [])
  return <Designs.Provider value={data?.pages ?? {}}>{children}</Designs.Provider>
}

export const usePageDesign = (page: string): Design | undefined => useContext(Designs)[page]

/** A page of this website opens in place; anything else (https, phone, email) opens as an ordinary link. */
export function SmartLink({ to, className, children }: { to: string; className?: string; children: ReactNode }) {
  if (to.startsWith('/') && !to.startsWith('//')) return <Link to={to} className={className}>{children}</Link>
  const web = to.startsWith('https://')
  return <a href={web || /^(tel|mailto):/.test(to) ? to : '#'} className={className} {...(web ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>{children}</a>
}

export function PageBlocks({ page, placement }: { page: string; placement: 'top' | 'bottom' }) {
  const blocks = usePageDesign(page)?.blocks.filter((b) => b.placement === placement) ?? []
  return <>{blocks.map((b, i) => <BlockView key={`${placement}-${i}`} block={b} />)}</>
}

function Enter({ block, index = 0, children }: { block: Block; index?: number; children: ReactNode }) {
  if (block.animation === 'none') return <>{children}</>
  return <Rise index={index} from={block.animation === 'rise' ? 'up' : block.animation}>{children}</Rise>
}

function Action({ label, to, className = 'btn' }: { label: string; to: string; className?: string }) {
  return label && to ? <SmartLink to={to} className={className}>{label} <ArrowRight size={16} aria-hidden /></SmartLink> : null
}

function Head({ block }: { block: Block }) {
  if (!block.eyebrow && !block.title && !block.text) return null
  return (
    <header className="pb-head">
      {block.eyebrow && <p className="eyebrow"><RichText text={block.eyebrow} /></p>}
      {block.title && <h2><RichText text={block.title} /></h2>}
      <Paragraphs text={block.text} />
    </header>
  )
}

function CardBody({ item }: { item: Item }) {
  return (
    <article className="pb-card">
      {item.image_url && <div className="pb-card-pic"><img src={item.image_url} alt={plain(item.title)} loading="lazy" decoding="async" /></div>}
      <div className="pb-card-text">
        {item.title && <h3><RichText text={item.title} /></h3>}
        <Paragraphs text={item.text} />
        <Action label={item.button_label} to={item.button_link} className="btn sm" />
      </div>
    </article>
  )
}

function Carousel({ block }: { block: Block }) {
  const track = useRef<HTMLDivElement>(null)
  const [at, setAt] = useState(0)
  const [paused, setPaused] = useState(false)
  const count = block.items.length
  const go = (n: number) => {
    const el = track.current
    const next = (n + count) % count
    const slide = el?.children[next] as HTMLElement | undefined
    if (el && slide) el.scrollTo?.({ left: slide.offsetLeft - el.offsetLeft, behavior: 'smooth' })
    setAt(next)
  }
  useEffect(() => {
    const still = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!block.autoplay || paused || still || count < 2) return
    const t = setTimeout(() => go(at + 1), 5000)
    return () => clearTimeout(t)
  })
  return (
    <div className="pb-carousel" role="group" aria-roledescription="carousel" aria-label={plain(block.title) || 'Slides'}
      onPointerEnter={() => setPaused(true)} onPointerLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <div className="pb-track" ref={track}
        onScroll={(e) => { const el = e.currentTarget; const w = (el.firstElementChild as HTMLElement | null)?.offsetWidth ?? 0; if (w) setAt(Math.min(count - 1, Math.round(el.scrollLeft / (w + 18)))) }}>
        {block.items.map((item, i) => <div className="pb-slide" key={i} role="group" aria-label={`Slide ${i + 1} of ${count}`}><CardBody item={item} /></div>)}
      </div>
      {count > 1 && (
        <div className="pb-controls">
          <button type="button" className="icon-btn" onClick={() => go(at - 1)} aria-label="Previous slide"><ChevronLeft size={18} aria-hidden /></button>
          <span className="pb-dots">{block.items.map((_, i) => <button type="button" key={i} aria-label={`Slide ${i + 1}`} aria-current={i === at} onClick={() => go(i)} />)}</span>
          <button type="button" className="icon-btn" onClick={() => go(at + 1)} aria-label="Next slide"><ChevronRight size={18} aria-hidden /></button>
        </div>
      )}
    </div>
  )
}

/** One section of a page, as the owner chose to show it. Also used as the live preview in the builder. */
export function BlockView({ block }: { block: Block }) {
  const visual = block.model !== 'none'
    ? <div className="pb-model"><Suspense fallback={null}><Scene3D kind={block.model} /></Suspense></div>
    : block.image_url ? <div className="pb-visual"><img src={block.image_url} alt={plain(block.title)} loading="lazy" /></div> : null
  let body: ReactNode = null
  if (block.layout === 'cards') {
    body = <><Head block={block} /><div className={`pb-grid cols-${block.columns}`}>{block.items.map((item, i) => <Enter block={block} index={i % block.columns} key={i}><Tilt max={5}><CardBody item={item} /></Tilt></Enter>)}</div></>
  } else if (block.layout === 'carousel') {
    body = <><Head block={block} /><Enter block={block}><Carousel block={block} /></Enter></>
  } else if (block.layout === 'accordion') {
    body = <><Head block={block} /><div className="faq-list pb-accordion">{block.items.map((item, i) => (
      <Enter block={block} index={i % 4} key={i}><details><summary><RichText text={item.title} /></summary>
        {item.image_url && <img className="pb-acc-pic" src={item.image_url} alt={plain(item.title)} loading="lazy" />}
        <Paragraphs text={item.text} /><Action label={item.button_label} to={item.button_link} className="btn sm" /></details></Enter>))}</div></>
  } else if (block.layout === 'gallery') {
    body = <><Head block={block} /><div className="gallery-grid">{block.items.filter((i) => i.image_url).map((item, i) => (
      <Enter block={block} index={i % 4} key={i}><figure><img src={item.image_url!} alt={plain(item.title)} loading="lazy" />{item.title && <figcaption><RichText text={item.title} /></figcaption>}</figure></Enter>))}</div></>
  } else if (block.layout === 'split') {
    body = <div className={`pb-split ${visual ? '' : 'alone'} ${block.animation === 'right' ? 'flipped' : ''}`}>
      <Enter block={block}><div><Head block={block} /><Action label={block.button_label} to={block.button_link} /></div></Enter>
      {visual && <Enter block={block} index={1}>{visual}</Enter>}
    </div>
  } else if (block.layout === 'banner') {
    body = <Enter block={block}><div className={`pb-banner ${visual ? 'with-visual' : ''}`}><div><Head block={block} /><Action label={block.button_label} to={block.button_link} className="btn lg" /></div>{visual}</div></Enter>
  } else {
    body = <Enter block={block}><div className="pb-text"><Head block={block} /><Action label={block.button_label} to={block.button_link} /></div></Enter>
  }
  return <section className={`pb-section bg-${block.background} pb-${block.layout}-section`}><div className="container">{body}</div></section>
}

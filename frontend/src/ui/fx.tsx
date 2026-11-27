import { useEffect, useRef, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Reveal } from './kit'

/** A card that leans in 3D towards the pointer, with a soft light following it. Mouse only; still on touch and reduced motion. */
export function Tilt({ children, className = '', max = 7 }: { children: ReactNode; className?: string; max?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const move = (e: ReactPointerEvent) => {
    const el = ref.current
    if (!el || e.pointerType !== 'mouse') return
    const b = el.getBoundingClientRect()
    const x = (e.clientX - b.left) / b.width
    const y = (e.clientY - b.top) / b.height
    el.style.setProperty('--rx', `${(0.5 - y) * max}deg`)
    el.style.setProperty('--ry', `${(x - 0.5) * max}deg`)
    el.style.setProperty('--mx', `${x * 100}%`)
    el.style.setProperty('--my', `${y * 100}%`)
  }
  const leave = () => { ref.current?.style.setProperty('--rx', '0deg'); ref.current?.style.setProperty('--ry', '0deg') }
  return <div ref={ref} className={`tilt ${className}`} onPointerMove={move} onPointerLeave={leave}>{children}</div>
}

/** Slides content in when it scrolls into view, a little later for each following item. */
export function Rise({ children, index = 0, from = 'up' }: { children: ReactNode; index?: number; from?: 'up' | 'left' | 'right' | 'zoom' | 'flip' }) {
  return <div className="rise" style={{ '--d': `${Math.min(index, 8) * 80}ms` } as CSSProperties}><Reveal className={`from-${from}`}>{children}</Reveal></div>
}

export function SectionHead({ eyebrow, title, text, center = true }: { eyebrow: string; title: string; text?: string; center?: boolean }) {
  return (
    <Reveal className={`section-head ${center ? 'center' : ''}`}>
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      {text && <p className="muted">{text}</p>}
    </Reveal>
  )
}

/** Adds the "raised header" shadow once the page is scrolled, and starts each page at the top. Draws nothing itself. */
export function ScrollFx() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo?.({ top: 0, behavior: 'instant' as ScrollBehavior }) }, [pathname])
  useEffect(() => {
    const update = () => document.documentElement.classList.toggle('scrolled', window.scrollY > 12)
    update()
    window.addEventListener('scroll', update, { passive: true })
    return () => { window.removeEventListener('scroll', update); document.documentElement.classList.remove('scrolled') }
  }, [pathname])
  return null
}

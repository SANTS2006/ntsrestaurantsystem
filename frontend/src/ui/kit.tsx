import { Component, createContext, useCallback, useContext, useEffect, useId, useRef, useState, type InputHTMLAttributes, type ReactNode } from 'react'
import { tokenStore } from '../lib/api'
import { registerRefresh } from '../lib/refresh'

import { Spinner as BrandSpin } from './Loaders'
export { LoadingBlock, PageLoader, Spinner } from './Loaders'

export function Skeleton({ h = 18, w = '100%' }: { h?: number; w?: string }) {
  // Larger placeholders (tables, cards, pages) show the branded loader on top of the shimmer.
  return <div className="skeleton" style={{ height: h, width: w, display: 'grid', placeItems: 'center', color: 'var(--brand)' }} aria-hidden>{h >= 80 && <BrandSpin />}</div>
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="alert error" role="alert">
      {message} {onRetry && <button className="btn sm secondary" onClick={onRetry}>Retry</button>}
    </div>
  )
}

type FieldProps = {
  label: string
  error?: string
  hint?: string
  children: (p: { id: string; 'aria-invalid': boolean; 'aria-describedby'?: string }) => ReactNode
}
export function Field({ label, error, hint, children }: FieldProps) {
  const id = useId()
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-invalid': !!error, 'aria-describedby': error ? `${id}-e` : undefined })}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span className="err" id={`${id}-e`}>{error}</span>}
    </div>
  )
}

/** A password box with a SHOW / HIDE button. Use it for every password field. */
export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'className'>) {
  const [show, setShow] = useState(false)
  return (
    <div className="pw">
      <input {...props} className="input" type={show ? 'text' : 'password'} />
      <button type="button" className="pw-toggle" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}>{show ? 'HIDE' : 'SHOW'}</button>
    </div>
  )
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    ref.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="btn sm secondary" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div style={{ marginTop: 16 }}>{children}</div>
      </div>
    </div>
  )
}

type Toast = { id: number; text: string }
const ToastCtx = createContext<(t: string) => void>(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((text: string) => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, text }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className="toast">{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  )
}

/** Fades content in once it scrolls into view (skipped for users who prefer reduced motion). */
export function Reveal({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') return setShown(true)
    const io = new IntersectionObserver(([e]) => e.isIntersecting && (setShown(true), io.disconnect()), { threshold: 0.12 })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return <div ref={ref} className={`reveal ${shown ? 'in' : ''} ${className}`}>{children}</div>
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <div className="container section"><ErrorState message="Something went wrong displaying this page." onRetry={() => location.reload()} /></div>
    ) : this.props.children
  }
}

export function useDocumentTitle(title: string, description?: string) {
  useEffect(() => {
    document.title = title
    if (description) {
      let m = document.querySelector('meta[name="description"]')
      if (!m) {
        m = document.createElement('meta')
        m.setAttribute('name', 'description')
        document.head.appendChild(m)
      }
      m.setAttribute('content', description)
    }
  }, [title, description])
}

const LIVE_POLL_MS = 30000

/** Async-data hook with loading / error / reload. Signed-in screens also refresh themselves quietly (every 30 s while the tab is
 *  visible, when it regains focus, and whenever something is pushed or the refresh button is pressed): no flicker, and the data object
 *  keeps its identity when nothing changed, so a form being edited is not reset. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true })
  const [tick, setTick] = useState(0)
  const quiet = useRef(false)
  useEffect(() => {
    let live = true
    const silent = quiet.current
    quiet.current = false
    if (!silent) setState((s) => ({ ...s, loading: true, error: null }))
    fn().then(
      (data) => live && setState((s) => (silent && s.data !== null && JSON.stringify(s.data) === JSON.stringify(data) ? s : { data, error: null, loading: false })),
      (e: Error) => live && setState((s) => (silent && s.data !== null ? s : { data: null, error: e.message, loading: false })),
    )
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  const reload = useCallback(() => setTick((t) => t + 1), []) // stable identity: safe to use in effect dependencies
  const refresh = useCallback(() => { quiet.current = true; setTick((t) => t + 1) }, [])
  useEffect(() => registerRefresh(refresh), [refresh])
  useEffect(() => {
    const t = setInterval(() => { if (document.visibilityState === 'visible' && tokenStore.get()) refresh() }, LIVE_POLL_MS)
    const vis = () => document.visibilityState === 'visible' && tokenStore.get() && refresh()
    document.addEventListener('visibilitychange', vis)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', vis) }
  }, [refresh])
  return { ...state, reload }
}

/* ------------------------------------------------------------------------------------------ premium building blocks */
export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
      {children && <div className="toolbar" style={{ margin: 0 }}>{children}</div>}
    </div>
  )
}

export function Kpi({ label, value, sub, icon, spark }: { label: string; value: string; sub?: ReactNode; icon?: ReactNode; spark?: ReactNode }) {
  return (
    <div className="card kpi">
      <div className="top"><span>{label}</span>{icon && <span className="chipicon" aria-hidden>{icon}</span>}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
      {spark}
    </div>
  )
}

/** Side drawer: focus moves in, Escape or the backdrop closes it. */
export function Drawer({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    ref.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <>
      <div className="drawer-back" onMouseDown={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <header><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="Close">✕</button></header>
        <div className="body">{children}</div>
        {footer && <div style={{ padding: '14px 22px', borderTop: '1px solid var(--border)' }}>{footer}</div>}
      </aside>
    </>
  )
}

export function SearchInput({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label: string }) {
  return (
    <div className="search" style={{ minWidth: 220, flex: '1 1 220px', maxWidth: 360 }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
      <input className="input" type="search" placeholder={placeholder} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

export function Pager({ page, hasPrev, hasNext, onPage, total }: { page: number; hasPrev: boolean; hasNext: boolean; onPage: (p: number) => void; total?: number }) {
  if (!hasPrev && !hasNext) return total !== undefined ? <div className="pager"><span className="muted">{total} result{total === 1 ? '' : 's'}</span></div> : null
  return (
    <div className="pager">
      <span className="muted">{total !== undefined ? `${total} results · ` : ''}Page {page}</span>
      <span style={{ display: 'flex', gap: 8 }}><button className="btn sm secondary" disabled={!hasPrev} onClick={() => onPage(page - 1)}>Previous</button><button className="btn sm secondary" disabled={!hasNext} onClick={() => onPage(page + 1)}>Next</button></span>
    </div>
  )
}

/** Click-to-open menu; closes on outside click and Escape. */
export function Dropdown({ trigger, children, label }: { trigger: ReactNode; children: ReactNode; label: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', off)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', off); document.removeEventListener('keydown', key) }
  }, [open])
  return (
    <div className="dropdown" ref={ref}>
      <button className="user-btn" aria-haspopup="menu" aria-expanded={open} aria-label={label} onClick={() => setOpen(!open)}>{trigger}</button>
      {open && <div className="menu" role="menu" onClick={() => setOpen(false)}>{children}</div>}
    </div>
  )
}

import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, api } from '../../lib/api'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle } from '../../ui/kit'
import { formatMoney, type MenuCategory, type PublicProduct } from '../SiteContext'

type TableData = {
  restaurant: { name: string; primary_color: string; secondary_color: string }
  branch: string; table: string; currency: string; can_request: boolean; identification: 'none' | 'name' | 'phone'; menu: MenuCategory[]
}
type Line = { key: string; p: PublicProduct; variation_id: number | null; quantity: number; addons: Record<number, number>; instructions: string }
type Sent = { public_id: string; total: string }

/** Diner-facing page opened by scanning a table's QR code. Sends a REQUEST; it is not an order until a cashier confirms it. */
export default function QRMenu() {
  const { token = '' } = useParams()
  const data = useAsync(() => api<TableData>(`/qr-menu/public/${token}/`, { auth: false }), [token])
  const d = data.data
  const money = (v: string | number) => formatMoney(v, d?.currency ?? 'SLE')
  useDocumentTitle(d ? `${d.table} · ${d.restaurant.name}` : 'Table menu')
  useEffect(() => {
    if (!d) return
    const r = document.documentElement.style
    r.setProperty('--brand', d.restaurant.primary_color)
    return () => { r.removeProperty('--brand') }
  }, [d])

  const [q, setQ] = useState('')
  const [lines, setLines] = useState<Line[]>([])
  const [picking, setPicking] = useState<PublicProduct | null>(null)
  const [f, setF] = useState({ customer_name: '', customer_phone: '', notes: '', website: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const storeKey = `nts.qr.${token}`
  const [sent, setSent] = useState<Sent | null>(() => { try { return JSON.parse(sessionStorage.getItem(storeKey) ?? 'null') } catch { return null } })
  const [status, setStatus] = useState<{ status: string; reject_reason: string } | null>(null)

  // Keep the diner informed: poll the request status until staff have handled it.
  useEffect(() => {
    if (!sent) return
    let stop = false
    const tick = async () => {
      try {
        const s = await api<{ status: string; reject_reason: string }>(`/qr-menu/public/${token}/requests/${sent.public_id}/`, { auth: false })
        if (!stop) setStatus(s)
        if (s.status !== 'new') return
      } catch { /* try again */ }
      if (!stop) setTimeout(tick, 5000)
    }
    void tick()
    return () => { stop = true }
  }, [sent, token])

  const items = useMemo(() => lines.map((l) => ({ product_id: l.p.id, variation_id: l.variation_id, quantity: l.quantity, addons: Object.entries(l.addons).filter(([, n]) => n > 0).map(([id, n]) => ({ id: Number(id), quantity: n })), instructions: l.instructions })), [lines])
  const quote = useAsync(() => (items.length ? api<{ total: string; lines: { line_total: string }[] }>('/orders/quote/', { body: { items, fulfilment: 'pickup' }, auth: false }) : Promise.resolve(null)), [JSON.stringify(items)])

  function add(p: PublicProduct, o?: Partial<Line>) {
    const base = { variation_id: p.variations.find((v) => v.is_default)?.id ?? null, quantity: 1, addons: {}, instructions: '', ...o }
    const key = JSON.stringify([p.id, base.variation_id, base.addons, base.instructions])
    setLines((c) => (c.find((l) => l.key === key) ? c.map((l) => (l.key === key ? { ...l, quantity: Math.min(50, l.quantity + base.quantity) } : l)) : [...c, { key, p, ...(base as Omit<Line, 'key' | 'p'>) }]))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (d && d.identification !== 'none' && !f.customer_name.trim()) local.customer_name = 'Please enter your name.'
    if (d?.identification === 'phone' && !f.customer_phone.trim()) local.customer_phone = 'Please enter your phone number.'
    if (f.customer_phone && !/^[0-9+()\-\s]{6,30}$/.test(f.customer_phone)) local.customer_phone = 'Enter a valid phone number.'
    setErrors(local)
    if (Object.keys(local).length || !items.length) return
    setBusy(true)
    try {
      const r = await api<Sent>(`/qr-menu/public/${token}/requests/`, { body: { items, ...f }, auth: false })
      const s = { public_id: r.public_id, total: r.total }
      try { sessionStorage.setItem(storeKey, JSON.stringify(s)) } catch { /* ignore */ }
      setSent(s); setLines([])
    } catch (err) {
      const fe = err instanceof ApiError ? err.fieldErrors() : {}
      setErrors({ form: fe.items ?? fe.detail ?? (err instanceof ApiError ? err.message : 'Something went wrong. Please try again.'), ...fe })
    } finally { setBusy(false) }
  }

  if (data.loading) return <div className="container section"><Skeleton h={120} /></div>
  if (data.error || !d) return <div className="container section"><Empty title="This QR code is not valid">Please ask a member of staff for help.</Empty></div>

  if (sent) {
    const s = status?.status ?? 'new'
    return (
      <div className="container section" style={{ maxWidth: 560 }}>
        <div className="card">
          <h1 style={{ fontSize: '1.5rem' }}>{d.restaurant.name} · {d.table}</h1>
          {s === 'new' && <><div className="alert" aria-live="polite">Your request was sent. <Spinner /> Waiting for a member of staff to confirm it…</div><p className="muted">It is not an order until it is confirmed. Total: {money(sent.total)}</p></>}
          {s === 'converted' && <div className="alert ok" aria-live="polite">Your order is confirmed. Thank you!</div>}
          {s === 'rejected' && <div className="alert error" aria-live="polite">Sorry, the staff could not take this request{status?.reject_reason ? `: ${status.reject_reason}` : '.'} Please ask a member of staff.</div>}
          {s !== 'new' && <button className="btn" onClick={() => { try { sessionStorage.removeItem(storeKey) } catch { /* ignore */ } setSent(null); setStatus(null) }}>Order something else</button>}
        </div>
      </div>
    )
  }

  const products = d.menu.flatMap((c) => c.products).filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="container section">
      <h1 style={{ fontSize: '1.6rem', marginBottom: 2 }}>{d.restaurant.name}</h1>
      <p className="muted">{d.branch} · <b>{d.table}</b></p>
      {!d.can_request && <div className="alert warn">Ordering from your table is not available right now. Please ask a member of staff.</div>}
      <input className="input" style={{ maxWidth: 360, marginBottom: 16 }} type="search" placeholder="Search the menu" aria-label="Search the menu" value={q} onChange={(e) => setQ(e.target.value)} />
      {d.menu.length === 0 ? <Empty title="The menu is being prepared" /> : d.menu.map((c) => {
        const list = c.products.filter((p) => products.includes(p))
        return list.length ? (
          <div key={c.slug} style={{ marginBottom: 24 }}><h2 style={{ fontSize: '1.2rem' }}>{c.name}</h2>
            <div className="grid g3">{list.map((p) => (
              <button key={p.id} className="card lift" style={{ textAlign: 'left', opacity: p.sold_out ? 0.55 : 1 }} disabled={p.sold_out || !d.can_request}
                onClick={() => (p.variations.length > 1 || p.addons.length || (p.variations.length === 1 && !p.variations[0].is_default) || p.allow_instructions ? setPicking(p) : add(p))}>
                <b>{p.name}</b>{p.sold_out && <span className="badge suspended" style={{ marginLeft: 6 }}>Sold out</span>}<br />
                <span className="muted" style={{ fontSize: '.9rem' }}>{p.description.slice(0, 70)}</span><br /><b>{money(p.price)}</b>{p.on_offer && <s className="muted" style={{ marginLeft: 6 }}>{money(p.regular_price)}</s>}
              </button>))}</div></div>
        ) : null
      })}

      {lines.length > 0 && (
        <form className="card" style={{ position: 'sticky', bottom: 8, boxShadow: 'var(--shadow)' }} onSubmit={submit} noValidate>
          <h2 style={{ fontSize: '1.1rem' }}>Your request</h2>
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          {lines.map((l, i) => (
            <div key={l.key} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
              <span style={{ flex: 1 }}>{l.p.name}{l.variation_id ? ` (${l.p.variations.find((v) => v.id === l.variation_id)?.name})` : ''}{l.instructions && <span className="muted"> · {l.instructions}</span>}</span>
              <button type="button" className="btn sm secondary" aria-label={`Fewer ${l.p.name}`} onClick={() => setLines((c) => (l.quantity <= 1 ? c.filter((x) => x.key !== l.key) : c.map((x) => (x.key === l.key ? { ...x, quantity: x.quantity - 1 } : x))))}>−</button>
              <b>{l.quantity}</b>
              <button type="button" className="btn sm secondary" aria-label={`More ${l.p.name}`} onClick={() => setLines((c) => c.map((x) => (x.key === l.key ? { ...x, quantity: Math.min(50, x.quantity + 1) } : x)))}>+</button>
              <span style={{ minWidth: 70, textAlign: 'right' }}>{quote.data?.lines[i] ? money(quote.data.lines[i].line_total) : ''}</span>
            </div>
          ))}
          {quote.error && <ErrorState message={quote.error} onRetry={quote.reload} />}
          {quote.data && <p style={{ fontSize: '1.15rem' }}><b>Total: {money(quote.data.total)}</b> <span className="muted">(you pay the cashier)</span></p>}
          {d.identification !== 'none' && <Field label="Your name" error={errors.customer_name}>{(p) => <input {...p} className="input" placeholder="Enter your name" value={f.customer_name} onChange={(e) => setF({ ...f, customer_name: e.target.value })} />}</Field>}
          {d.identification === 'phone' && <Field label="Phone number" error={errors.customer_phone}>{(p) => <input {...p} className="input" type="tel" placeholder="Enter your phone number" value={f.customer_phone} onChange={(e) => setF({ ...f, customer_phone: e.target.value })} />}</Field>}
          <Field label="Note for the staff (optional)">{(p) => <input {...p} className="input" maxLength={200} placeholder="e.g. no pepper, extra plates" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />}</Field>
          {/* honeypot: hidden from people, tempting to bots */}
          <div aria-hidden style={{ position: 'absolute', left: '-9999px' }}><label>Website<input tabIndex={-1} autoComplete="off" value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} /></label></div>
          <button className="btn" style={{ width: '100%' }} disabled={busy || !!quote.error || !quote.data}>{busy ? <Spinner /> : 'Send request to staff'}</button>
          <p className="hint">This sends a request to the cashier. It becomes an order only when staff confirm it.</p>
        </form>
      )}
      {picking && <Picker p={picking} money={money} onClose={() => setPicking(null)} onAdd={(o) => { add(picking, o); setPicking(null) }} />}
    </div>
  )
}

function Picker({ p, money, onClose, onAdd }: { p: PublicProduct; money: (v: string) => string; onClose: () => void; onAdd: (o: Partial<Line>) => void }) {
  const [vid, setVid] = useState<number | null>(p.variations.find((v) => v.is_default)?.id ?? null)
  const [adds, setAdds] = useState<Record<number, number>>({})
  const [note, setNote] = useState('')
  const [qty, setQty] = useState(1)
  return (
    <Modal title={p.name} onClose={onClose}>
      {p.variations.length > 0 && <Field label="Choose an option">{(f) => <select {...f} className="input" value={vid ?? ''} onChange={(e) => setVid(e.target.value ? Number(e.target.value) : null)}>{!p.variations.some((v) => v.is_default) && <option value="">Select…</option>}{p.variations.map((v) => <option key={v.id} value={v.id}>{v.name}{Number(v.price_delta) > 0 ? ` (+${money(v.price_delta)})` : ''}</option>)}</select>}</Field>}
      {p.addons.map((a) => <label key={a.id} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}><input className="input" style={{ width: 64 }} type="number" min={0} max={a.max_quantity} aria-label={`${a.name} quantity`} value={adds[a.id] ?? 0} onChange={(e) => setAdds({ ...adds, [a.id]: Math.max(0, Math.min(a.max_quantity, Number(e.target.value) || 0)) })} />{a.name} <span className="muted">+{money(a.price)}</span></label>)}
      {p.allow_instructions && <Field label="Special instructions (optional)">{(f) => <input {...f} className="input" maxLength={200} placeholder="e.g. no pepper" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>}
      <Field label="Quantity">{(f) => <input {...f} className="input" type="number" min={1} max={50} value={qty} onChange={(e) => setQty(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} />}</Field>
      <button className="btn" disabled={p.variations.length > 0 && vid === null} onClick={() => onAdd({ variation_id: vid, quantity: qty, addons: adds, instructions: note.trim() })}>Add to request</button>
    </Modal>
  )
}

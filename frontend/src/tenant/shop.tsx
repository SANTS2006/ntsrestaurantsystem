import { Banknote, Check, Minus, Plus, ShoppingCart, Smartphone, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Empty, ErrorState, Field, PageLoader, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../ui/kit'
import { useCart, type CartLine } from './cart'
import { useSite, type PublicProduct } from './SiteContext'

/* ------------------------------------------------------------------ product purchase panel */
export function ProductBuy({ p }: { p: PublicProduct }) {
  const cart = useCart()
  const toast = useToast()
  const def = p.variations.find((v) => v.is_default) ?? null
  const [vid, setVid] = useState<number | null>(def?.id ?? null)
  const [qty, setQty] = useState(1)
  const [adds, setAdds] = useState<Record<number, number>>({})
  const [note, setNote] = useState('')
  const { money } = useSite()

  if (p.sold_out) return <div className="alert error">This dish is sold out right now.</div>
  const needsChoice = p.variations.length > 0 && vid === null

  function add(e: FormEvent) {
    e.preventDefault()
    if (needsChoice) return toast('Please choose an option first.')
    const v = p.variations.find((x) => x.id === vid)
    const addons = p.addons.filter((a) => (adds[a.id] ?? 0) > 0).map((a) => ({ id: a.id, name: a.name, quantity: adds[a.id] }))
    cart.add({ product_id: p.id, name: p.name, image: p.image, variation_id: vid, variation_name: v?.name ?? '', addons, quantity: qty, instructions: note.trim() })
    toast(`${p.name} added to your cart.`)
    setQty(1)
  }
  return (
    <form onSubmit={add} style={{ marginTop: 16 }}>
      <div className="opt-cols">
      {p.variations.length > 0 && (
        <Field label="Choose an option">
          {(f) => <select {...f} className="input" value={vid ?? ''} onChange={(e) => setVid(e.target.value ? Number(e.target.value) : null)}>
            {!def && <option value="">Select…</option>}
            {p.variations.map((v) => <option key={v.id} value={v.id}>{v.name}{Number(v.price_delta) > 0 ? ` (+${money(v.price_delta)})` : ''}</option>)}
          </select>}
        </Field>
      )}
      {p.addons.length > 0 && (
        <fieldset style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14 }}>
          <legend>Extras</legend>
          {p.addons.map((a) => (
            <label key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <input type="number" min={0} max={a.max_quantity} style={{ width: 64 }} className="input" aria-label={`${a.name} quantity`} value={adds[a.id] ?? 0}
                onChange={(e) => setAdds({ ...adds, [a.id]: Math.max(0, Math.min(a.max_quantity, Number(e.target.value) || 0)) })} />
              <span className="extra-text"><b>{a.name}</b><span className="muted">+{money(a.price)} each, max {a.max_quantity}</span></span>
            </label>
          ))}
        </fieldset>
      )}
      </div>
      {p.allow_instructions && (
        <Field label="Special instructions (optional)">
          {(f) => <textarea {...f} className="input" rows={2} maxLength={200} placeholder="e.g. no pepper, extra sauce" value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      )}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <button type="button" className="btn sm secondary" aria-label="Decrease quantity" onClick={() => setQty(Math.max(1, qty - 1))}><Minus size={14} /></button>
          <b aria-live="polite" style={{ minWidth: 24, textAlign: 'center' }}>{qty}</b>
          <button type="button" className="btn sm secondary" aria-label="Increase quantity" onClick={() => setQty(Math.min(50, qty + 1))}><Plus size={14} /></button>
        </span>
        <button className="btn"><ShoppingCart size={18} aria-hidden /> Add to cart</button>
      </div>
      <p className="hint" style={{ marginTop: 8 }}>The final price is calculated when you review your cart.</p>
    </form>
  )
}

/* ------------------------------------------------------------------ cart */
type Quote = {
  currency: string; subtotal: string; discount_total: string; tax_total: string; tax_rate_percent: string; delivery_fee: string; total: string
  lines: { quantity: number; unit_price: string; line_total: string }[]
}

export function useQuote(fulfilment: 'pickup' | 'delivery') {
  const cart = useCart()
  const items = JSON.stringify(cart.apiItems())
  return useAsync(
    () => (cart.lines.length ? api<Quote>('/orders/quote/', { body: { items: JSON.parse(items), fulfilment }, auth: false }) : Promise.resolve(null)),
    [items, fulfilment],
  )
}

function Totals({ q, delivery }: { q: Quote; delivery?: boolean }) {
  const { money } = useSite()
  const row = (l: string, v: string, bold = false) => <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: bold ? 700 : 400, fontSize: bold ? '1.15rem' : undefined }}><span>{l}</span><span>{money(v)}</span></div>
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {row('Subtotal', q.subtotal)}
      {Number(q.discount_total) > 0 && row('Discount', `-${q.discount_total}`)}
      {Number(q.tax_rate_percent) > 0 && row(`Tax (${Number(q.tax_rate_percent)}%)`, q.tax_total)}
      {delivery && row('Delivery fee', q.delivery_fee)}
      <hr style={{ border: 0, borderTop: '1px solid var(--border)', width: '100%' }} />
      {row('Total', q.total, true)}
    </div>
  )
}

export function CartPage() {
  useDocumentTitle('Your cart')
  const cart = useCart()
  const { money } = useSite()
  const { me } = useAuth()
  const quote = useQuote('pickup')
  return (
    <section className="section"><div className="container">
      <h1>Your cart</h1>
      {!cart.lines.length ? <Empty title="Your cart is empty"><Link className="btn" to="/menu">Browse the menu</Link></Empty> : (
        <div className="grid g2" style={{ alignItems: 'start', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 300px), 1fr))' }}>
          <div style={{ display: 'grid', gap: 12 }}>
            {cart.lines.map((l: CartLine, i) => {
              const priced = quote.data?.lines[i]
              return (
                <div className="card" key={l.key} style={{ display: 'flex', gap: 12 }}>
                  {l.image && <img src={l.image} alt="" width={64} height={64} style={{ objectFit: 'cover', borderRadius: 8 }} />}
                  <div style={{ flex: 1 }}>
                    <b>{l.name}</b>{l.variation_name && <span className="muted"> · {l.variation_name}</span>}
                    {l.addons.length > 0 && <div className="muted" style={{ fontSize: '.9rem' }}>{l.addons.map((a) => `${a.quantity}× ${a.name}`).join(', ')}</div>}
                    {l.instructions && <div className="muted" style={{ fontSize: '.9rem' }}>Note: {l.instructions}</div>}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                      <button className="btn sm secondary" aria-label={`Decrease ${l.name}`} onClick={() => cart.setQty(l.key, l.quantity - 1)}><Minus size={14} /></button>
                      <b>{l.quantity}</b>
                      <button className="btn sm secondary" aria-label={`Increase ${l.name}`} onClick={() => cart.setQty(l.key, l.quantity + 1)}><Plus size={14} /></button>
                      <button className="btn sm secondary" aria-label={`Remove ${l.name}`} onClick={() => cart.remove(l.key)}><Trash2 size={14} /></button>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>{priced ? <><b>{money(priced.line_total)}</b><div className="muted" style={{ fontSize: '.85rem' }}>{money(priced.unit_price)} each</div></> : <Skeleton h={18} w="60px" />}</div>
                </div>
              )
            })}
          </div>
          <div className="card">
            <h2 style={{ fontSize: '1.2rem' }}>Summary</h2>
            {quote.error && <ErrorState message={quote.error} onRetry={quote.reload} />}
            {quote.loading && !quote.data ? <Skeleton h={90} /> : quote.data && <Totals q={quote.data} />}
            <p className="hint">Delivery fees are added at checkout if you choose delivery.</p>
            <Link className="btn" style={{ width: '100%', marginTop: 8, pointerEvents: quote.error ? 'none' : undefined, opacity: quote.error ? 0.5 : 1 }} to={me ? '/checkout' : '/login?next=/checkout'}>
              {me ? 'Checkout' : 'Sign in to checkout'}
            </Link>
          </div>
        </div>
      )}
    </div></section>
  )
}

/* ------------------------------------------------------------------ checkout */
function PayOption({ checked, onSelect, icon, title, note, children }: { checked: boolean; onSelect: () => void; icon: ReactNode; title: string; note: string; children?: ReactNode }) {
  return (
    <label className={`pay-option ${checked ? 'selected' : ''}`}>
      <input type="radio" name="pay" checked={checked} onChange={onSelect} />
      <span className="ico">{icon}</span>
      <span className="text"><b>{title}</b><small>{note}</small>{children && <span className="brands">{children}</span>}</span>
      <span className="mark" aria-hidden><Check size={14} strokeWidth={3} /></span>
    </label>
  )
}

type Addr = { id: number; label: string; line1: string; line2: string; city: string; phone: string; is_default: boolean }
type Placed = { id: number }

export function CheckoutPage() {
  useDocumentTitle('Checkout')
  const { site, money } = useSite()
  const { me, loading } = useAuth()
  const cart = useCart()
  const toast = useToast()
  const navigate = useNavigate()
  const [fulfilment, setFulfilment] = useState<'pickup' | 'delivery'>(site.pickup_enabled ? 'pickup' : 'delivery')
  const [branch, setBranch] = useState<string>(site.branches.length === 1 ? String(site.branches[0].id) : '')
  const [phone, setPhone] = useState('')
  const [notes, setNotes] = useState('')
  const [payMethod, setPayMethod] = useState<'cash' | 'mobile_money'>('cash')
  const [addrId, setAddrId] = useState<string>('new')
  const [addr, setAddr] = useState({ line1: '', line2: '', city: '', delivery_notes: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [placing, setPlacing] = useState('')
  const quote = useQuote(fulfilment)
  const saved = useAsync(() => (me ? api<Addr[]>('/customers/addresses/') : Promise.resolve([])), [me?.id])
  const profile = useAsync(() => (me ? api<{ phone: string }>('/customers/me/') : Promise.resolve(null)), [me?.id])
  const attempt = useRef<{ payload: string; key: string }>({ payload: '', key: '' })

  useEffect(() => { if (profile.data?.phone && !phone) setPhone(profile.data.phone) }, [profile.data]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const d = saved.data?.find((a) => a.is_default) ?? saved.data?.[0]
    if (d) setAddrId(String(d.id))
  }, [saved.data])

  if (loading) return <div className="container section"><Spinner /></div>
  if (!me) return <Navigate to="/login?next=/checkout" replace />
  if (me.role !== 'customer') return <div className="container section"><Empty title="Checkout is for customer accounts">Sign in with a customer account to order.</Empty></div>
  if (placing) return <PageLoader label={placing} /> // keeps the emptied cart from flashing while the payment opens
  if (!cart.lines.length) return <div className="container section"><Empty title="Your cart is empty"><Link className="btn" to="/menu">Browse the menu</Link></Empty></div>

  async function place(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!/^[0-9+()\-\s]{6,30}$/.test(phone)) local.phone = 'Enter a valid phone number.'
    if (site.branches.length > 1 && !branch) local.branch = 'Choose a branch.'
    if (fulfilment === 'delivery' && addrId === 'new' && (!addr.line1.trim() || !addr.city.trim())) local.address = 'Enter the street and city.'
    setErrors(local)
    if (Object.keys(local).length) return
    const payload: Record<string, unknown> = {
      items: cart.apiItems(), fulfilment, payment_method: payMethod, contact_phone: phone.trim(), notes: notes.trim(),
      ...(branch ? { branch_id: Number(branch) } : {}),
      ...(fulfilment === 'delivery' ? (addrId === 'new' ? { address: addr } : { address_id: Number(addrId) }) : {}),
    }
    // Same request => same idempotency key (a retry after a network failure can never double-order);
    // a changed request gets a fresh key.
    const serialized = JSON.stringify(payload)
    if (attempt.current.payload !== serialized) attempt.current = { payload: serialized, key: crypto.randomUUID() }
    setBusy(true)
    try {
      const order = await api<Placed>('/orders/checkout/', { body: payload, headers: { 'Idempotency-Key': attempt.current.key } })
      if (payMethod === 'mobile_money') {
        setPlacing('Opening your payment')
        cart.clear()
        try {
          const pay = await api<{ id: number; redirect_url: string; ussd_code: string }>('/payments/initiate/', { body: { order_id: order.id, phone: phone.trim() }, headers: { 'Idempotency-Key': crypto.randomUUID() } })
          if (pay.redirect_url) {
            window.location.assign(pay.redirect_url) // same tab: Monime brings the customer back to the success page
            return
          }
          navigate(`/pay/${pay.id}?order=${order.id}`) // the dial-code payment screen; it moves to the success page by itself
          return
        } catch (e) {
          toast(e instanceof ApiError ? (e.fieldErrors().detail ?? e.message) : 'The payment could not be started.')
          navigate(`/account/orders/${order.id}`) // the order is kept: the customer can pay from here
          return
        }
      }
      cart.clear()
      toast('Order placed. The restaurant will confirm it shortly.')
      navigate(`/account/orders/${order.id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        const f = err.fieldErrors()
        setErrors({ form: f.items ?? f.detail ?? f.status ?? err.message, ...f })
      } else setErrors({ form: 'Something went wrong. Please try again.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="section"><div className="container">
      <h1>Checkout</h1>
      <form onSubmit={place} noValidate className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 300px), 1fr))', alignItems: 'start' }}>
        <div className="card">
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          <fieldset style={{ border: 0, padding: 0, margin: '0 0 14px' }}>
            <legend style={{ fontWeight: 600 }}>How would you like your order?</legend>
            {site.pickup_enabled && <label style={{ display: 'block' }}><input type="radio" name="f" checked={fulfilment === 'pickup'} onChange={() => setFulfilment('pickup')} /> Pickup</label>}
            {site.delivery_enabled && <label style={{ display: 'block' }}><input type="radio" name="f" checked={fulfilment === 'delivery'} onChange={() => setFulfilment('delivery')} /> Delivery</label>}
          </fieldset>
          {site.branches.length > 1 && (
            <Field label="Branch" error={errors.branch ?? errors.branch_id}>
              {(f) => <select {...f} className="input" value={branch} onChange={(e) => setBranch(e.target.value)}><option value="">Choose a branch</option>{site.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
            </Field>
          )}
          {fulfilment === 'delivery' && (
            <>
              {(saved.data ?? []).length > 0 && (
                <Field label="Delivery address">
                  {(f) => <select {...f} className="input" value={addrId} onChange={(e) => setAddrId(e.target.value)}>
                    {saved.data!.map((a) => <option key={a.id} value={a.id}>{a.label}: {a.line1}, {a.city}</option>)}<option value="new">Use a new address</option>
                  </select>}
                </Field>
              )}
              {addrId === 'new' && (
                <>
                  <Field label="Street address" error={errors.address}>{(f) => <input {...f} className="input" placeholder="Enter your delivery address" value={addr.line1} onChange={(e) => setAddr({ ...addr, line1: e.target.value })} />}</Field>
                  <Field label="Apartment, landmark (optional)">{(f) => <input {...f} className="input" placeholder="e.g. next to the market" value={addr.line2} onChange={(e) => setAddr({ ...addr, line2: e.target.value })} />}</Field>
                  <Field label="City">{(f) => <input {...f} className="input" placeholder="Enter your city" value={addr.city} onChange={(e) => setAddr({ ...addr, city: e.target.value })} />}</Field>
                </>
              )}
            </>
          )}
          <Field label="Phone number" error={errors.phone ?? errors.contact_phone}>{(f) => <input {...f} className="input" type="tel" autoComplete="tel" placeholder="Enter your phone number" value={phone} onChange={(e) => setPhone(e.target.value)} />}</Field>
          <Field label="Notes for the restaurant (optional)">{(f) => <textarea {...f} className="input" rows={2} maxLength={300} placeholder="Anything we should know?" value={notes} onChange={(e) => setNotes(e.target.value)} />}</Field>
        </div>
        <div className="card">
          <h2 style={{ fontSize: '1.2rem' }}>Order summary</h2>
          {cart.lines.map((l, i) => <div key={l.key} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}><span>{l.quantity} × {l.name}{l.variation_name ? ` (${l.variation_name})` : ''}</span><span>{quote.data ? money(quote.data.lines[i]?.line_total ?? 0) : ''}</span></div>)}
          <hr style={{ border: 0, borderTop: '1px solid var(--border)' }} />
          {quote.error && <ErrorState message={quote.error} onRetry={quote.reload} />}
          {quote.loading && !quote.data ? <Skeleton h={90} /> : quote.data && <Totals q={quote.data} delivery={fulfilment === 'delivery'} />}
          <fieldset className="pay-options">
            <legend>Payment method</legend>
            <PayOption checked={payMethod === 'cash'} onSelect={() => setPayMethod('cash')} icon={<Banknote size={22} aria-hidden />} title="Cash" note={`Pay when you ${fulfilment === 'delivery' ? 'receive' : 'pick up'} your order`} />
            {site.online_payments && (
              <PayOption checked={payMethod === 'mobile_money'} onSelect={() => setPayMethod('mobile_money')} icon={<Smartphone size={22} aria-hidden />} title="Mobile money" note="Orange Money or Afrimoney">
                <span className="pay-brand orange">Orange Money</span><span className="pay-brand afri">Afrimoney</span>
              </PayOption>
            )}
          </fieldset>
          <button className="btn lg" style={{ width: '100%', marginTop: 4 }} disabled={busy || !!quote.error || !quote.data}>{busy ? <Spinner /> : payMethod === 'mobile_money' && quote.data ? `Place order and pay ${money(quote.data.total)}` : 'Place order'}</button>
          <p className="hint">The total shown is calculated by the restaurant&apos;s system when you place the order.</p>
        </div>
      </form>
    </div></section>
  )
}

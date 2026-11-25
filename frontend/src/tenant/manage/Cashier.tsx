import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import RequestsPanel from '../qr/RequestsPanel'
import { ApiError, api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Empty, ErrorState, Field, Modal, PageHeader, SearchInput, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite, type MenuCategory, type PublicProduct } from '../SiteContext'

const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const money2 = /^\d+(\.\d{1,2})?$/

export type ShiftData = {
  id: number; status: string; branch_id: number; branch_name: string; opened_at: string; closed_at: string | null; opening_cash: string
  expected_cash?: string; actual_cash?: string; variance?: string; cashier?: string; close_notes?: string
  totals?: { cash_sales: string; cash_refunds: string; cash_in: string; cash_out: string; mobile_money_sales: string; cash_transactions: string; mobile_money_transactions: string }
}
type Adj = { id: number; kind: string; amount: string; reason: string; status: string; decided_by: string | null; decision_note: string }

export default function Cashier() {
  useDocumentTitle('Cashier')
  const [tab, setTab] = useState<'order' | 'qr' | 'shift' | 'sales'>('order')
  const [qrCount, setQrCount] = useState(0)
  const shift = useAsync(() => api<{ shift: ShiftData | null; adjustments: Adj[] }>('/cashier/shift/current/'), [])
  // Totals are computed by the server; refresh them whenever the cashier looks at them or takes an order.
  const { reload } = shift
  useEffect(() => { if (tab !== 'order') reload() }, [tab, reload])
  return (
    <>
      <PageHeader title="Point of sale" subtitle="Take orders and payments, print receipts">
        <div className="seg" role="tablist" aria-label="Point of sale sections">
          {([['order', 'New order'], ['qr', `Table requests${qrCount ? ` (${qrCount})` : ''}`], ['shift', 'My shift'], ['sales', 'My sales']] as const).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
        {shift.data && <span className={`badge ${shift.data.shift ? 'active' : 'suspended'}`}>{shift.data.shift ? `Shift open · ${shift.data.shift.branch_name}` : 'No open shift'}</span>}
      </PageHeader>
      {shift.error && <ErrorState message={shift.error} onRetry={shift.reload} />}
      {tab === 'order' && <NewOrder hasShift={!!shift.data?.shift} goShift={() => setTab('shift')} onCreated={reload} />}
      {/* mounted even on other tabs so live requests keep arriving */}
      <div hidden={tab !== 'qr'}><RequestsPanel onCount={setQrCount} /></div>
      {tab === 'shift' && <ShiftPanel data={shift.data} loading={shift.loading} reload={shift.reload} />}
      {tab === 'sales' && <Sales />}
    </>
  )
}

/* ------------------------------------------------------------------ new in-person order */
type Line = { key: string; product: PublicProduct; variation_id: number | null; quantity: number; addons: Record<number, number>; instructions: string }
type Discount = { type: 'percent' | 'amount'; value: string; reason: string }
type Quote = { subtotal: string; discount_total: string; tax_total: string; delivery_fee: string; total: string; lines: { line_total: string; unit_price: string }[] }

function NewOrder({ hasShift, goShift, onCreated }: { hasShift: boolean; goShift: () => void; onCreated: () => void }) {
  const { site, money } = useSite()
  const { me } = useAuth()
  const toast = useToast()
  const menu = useAsync(() => api<MenuCategory[]>('/catalog/public/menu/', { auth: false }), [])
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const [lines, setLines] = useState<Line[]>([])
  const [picking, setPicking] = useState<PublicProduct | null>(null)
  const [f, setF] = useState({ fulfilment: 'dine_in', contact_name: '', contact_phone: '', contact_email: '', notes: '', line1: '', city: '', payment: 'cash', amount_received: '', payer_phone: '', branch: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [discount, setDiscount] = useState<Discount | null>(null)
  const [dForm, setDForm] = useState<Discount>({ type: 'percent', value: '', reason: '' })
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<{ number: string; change: string | null; receipt: number | null; status: string } | null>(null)
  const attempt = useRef({ payload: '', key: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  const items = useMemo(() => lines.map((l) => ({ product_id: l.product.id, variation_id: l.variation_id, quantity: l.quantity, addons: Object.entries(l.addons).filter(([, n]) => n > 0).map(([id, n]) => ({ id: Number(id), quantity: n })), instructions: l.instructions })), [lines])
  const quoteFulfilment = f.fulfilment === 'delivery' ? 'delivery' : 'pickup'
  // staff pricing endpoint: it is the only one that accepts a discount, and it enforces the cashier limit on the server
  const quote = useAsync(() => (items.length ? api<Quote>('/cashier/quote/', { body: { items, fulfilment: quoteFulfilment, ...(discount ? { discount } : {}) } }) : Promise.resolve(null)), [JSON.stringify(items), quoteFulfilment, JSON.stringify(discount)])
  const products = (menu.data ?? []).filter((c) => !cat || c.slug === cat).flatMap((c) => c.products).filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()))
  const change = quote.data && money2.test(f.amount_received) ? Number(f.amount_received) - Number(quote.data.total) : null

  function addProduct(p: PublicProduct, line?: Omit<Line, 'key' | 'product'>) {
    const base = { variation_id: p.variations.find((v) => v.is_default)?.id ?? null, quantity: 1, addons: {}, instructions: '', ...line }
    const key = JSON.stringify([p.id, base.variation_id, base.addons, base.instructions])
    setLines((cur) => (cur.find((l) => l.key === key) ? cur.map((l) => (l.key === key ? { ...l, quantity: Math.min(50, l.quantity + base.quantity) } : l)) : [...cur, { key, product: p, ...base }]))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!items.length) local.items = 'Add at least one item.'
    if (f.contact_phone && !/^[0-9+()\-\s]{6,30}$/.test(f.contact_phone)) local.contact_phone = 'Enter a valid phone number.'
    if (f.fulfilment === 'delivery' && (!f.contact_phone || !f.line1 || !f.city)) local.address = 'Delivery needs a phone number, street and city.'
    if (f.payment === 'cash' && !money2.test(f.amount_received)) local.amount_received = 'Enter the cash received, e.g. 50.00.'
    if (f.payment === 'cash' && quote.data && Number(f.amount_received) < Number(quote.data.total)) local.amount_received = `At least ${money(quote.data.total)} is due.`
    if (f.payment === 'mobile_money' && !(f.payer_phone || f.contact_phone)) local.payer_phone = "Enter the customer's mobile money number."
    setErrors(local)
    if (Object.keys(local).length) return
    const payload = {
      items, fulfilment: f.fulfilment, ...(discount ? { discount } : {}), ...(f.branch ? { branch_id: Number(f.branch) } : {}), contact_name: f.contact_name || 'Walk-in customer', contact_phone: f.contact_phone, contact_email: f.contact_email, notes: f.notes,
      ...(f.fulfilment === 'delivery' ? { address: { line1: f.line1, city: f.city } } : {}),
      payment: f.payment, ...(f.payment === 'cash' ? { amount_received: f.amount_received } : {}), ...(f.payment === 'mobile_money' ? { payer_phone: f.payer_phone || f.contact_phone } : {}),
    }
    const s = JSON.stringify(payload)
    if (attempt.current.payload !== s) attempt.current = { payload: s, key: crypto.randomUUID() } // a retry of the same order reuses the key
    setBusy(true)
    try {
      const r = await api<{ order: { number: string; status_label: string }; payment?: { receipt_id: number | null }; change_given?: string | null }>('/cashier/orders/', { body: payload, headers: { 'Idempotency-Key': attempt.current.key } })
      setDone({ number: r.order.number, change: r.change_given ?? null, receipt: r.payment?.receipt_id ?? null, status: r.order.status_label })
      toast(`Order ${r.order.number} created.`)
      onCreated()
    } catch (err) {
      setErrors({ form: msg(err) })
    } finally { setBusy(false) }
  }
  const reset = () => { setDone(null); setLines([]); setDiscount(null); setDForm({ type: 'percent', value: '', reason: '' }); setF({ ...f, contact_name: '', contact_phone: '', contact_email: '', notes: '', amount_received: '', payer_phone: '', line1: '', city: '' }); attempt.current = { payload: '', key: '' } }

  if (done) return (
    <div className="card" style={{ maxWidth: 520 }}>
      <h2>Order {done.number} created</h2>
      <p>Status: <b>{done.status}</b></p>
      {done.change !== null && <p style={{ fontSize: '1.5rem' }}>Change to give: <b>{money(done.change)}</b></p>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {done.receipt && <Link className="btn" to={`/receipts/${done.receipt}`} target="_blank">Print receipt</Link>}
        <button className="btn secondary" onClick={reset}>New order</button>
      </div>
    </div>
  )
  if (!hasShift && me?.role === 'cashier') return <div className="alert warn">Open your shift before taking orders with cash. <button className="btn sm" onClick={goShift}>Open shift</button></div>

  const total = quote.data ? Number(quote.data.total) : 0
  const cashOptions = quote.data ? Array.from(new Set([total, ...[5, 10, 50, 100].map((s) => Math.ceil(total / s) * s)].filter((v) => v >= total))).slice(0, 4) : []
  const qty = lines.reduce((n, l) => n + l.quantity, 0)
  return (
    <div className="pos">
      <section aria-label="Menu">
        <div className="toolbar" style={{ marginBottom: 12 }}>
          <SearchInput value={q} onChange={setQ} placeholder="Search the menu" label="Search products" />
        </div>
        <div className="chips" role="group" aria-label="Categories" style={{ marginBottom: 16 }}>
          <button className="chip" aria-pressed={!cat} onClick={() => setCat('')}>All</button>
          {(menu.data ?? []).map((c) => <button key={c.slug} className="chip" aria-pressed={cat === c.slug} onClick={() => setCat(c.slug)}>{c.name}</button>)}
        </div>
        {menu.loading ? <div className="tiles"><Skeleton h={190} /><Skeleton h={190} /><Skeleton h={190} /></div> : menu.error ? <ErrorState message={menu.error} onRetry={menu.reload} /> : !products.length ? <Empty title="No products found" /> : (
          <div className="tiles">
            {products.map((p) => (
              <button key={p.id} className="tile" disabled={p.sold_out}
                onClick={() => (p.variations.length > 1 || p.addons.length || (p.variations.length === 1 && !p.variations[0].is_default) ? setPicking(p) : addProduct(p))}>
                <span className="pic">{p.image ? <img src={p.image} alt="" loading="lazy" /> : p.name.charAt(0)}</span>
                <span className="info"><b>{p.name}</b><span>{money(p.price)}</span>{p.sold_out && <span className="badge suspended" style={{ width: 'fit-content' }}>Sold out</span>}</span>
              </button>
            ))}
          </div>
        )}
      </section>
      <form className="card pos-cart" onSubmit={submit} noValidate aria-label="Current order">
        <header><h2>Current order</h2><span className="badge">{qty} item{qty === 1 ? '' : 's'}</span></header>
        <div className="lines">
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          {errors.items && <div className="alert error">{errors.items}</div>}
          {!lines.length ? <p className="muted" style={{ padding: '18px 0', margin: 0, textAlign: 'center' }}>Tap a dish to start the order.</p> : lines.map((l, i) => (
            <div className="cart-line" key={l.key}>
              <span className="name">{l.product.name}<small>{l.variation_id ? l.product.variations.find((v) => v.id === l.variation_id)?.name : ''}{Object.values(l.addons).some((n) => n > 0) ? ' + extras' : ''}{l.instructions ? ` · ${l.instructions}` : ''}</small></span>
              <span className="stepper">
                <button type="button" aria-label={`Decrease ${l.product.name}`} onClick={() => setLines((c) => (l.quantity <= 1 ? c.filter((x) => x.key !== l.key) : c.map((x) => (x.key === l.key ? { ...x, quantity: x.quantity - 1 } : x))))}>−</button>
                <b>{l.quantity}</b>
                <button type="button" aria-label={`Increase ${l.product.name}`} onClick={() => setLines((c) => c.map((x) => (x.key === l.key ? { ...x, quantity: Math.min(50, x.quantity + 1) } : x)))}>+</button>
              </span>
              <b className="num" style={{ minWidth: 64, textAlign: 'right' }}>{quote.data?.lines[i] ? money(quote.data.lines[i].line_total) : ''}</b>
            </div>
          ))}
        </div>
        <div className="foot">
          {quote.error && <ErrorState message={quote.error} onRetry={quote.reload} />}
          <div className="totals">
            {quote.data && <>{Number(quote.data.discount_total) > 0 && <div><span>Discount</span><span className="num">−{money(quote.data.discount_total)}</span></div>}<div><span>Tax</span><span className="num">{money(quote.data.tax_total)}</span></div>
              {f.fulfilment === 'delivery' && <div><span>Delivery</span><span className="num">{money(quote.data.delivery_fee)}</span></div>}</>}
            <div className="grand"><b>Total</b><b className="num">{quote.data ? money(quote.data.total) : money('0.00')}</b></div>
          </div>
          {site.branches.length > 1 && me?.role !== 'cashier' && <Field label="Branch">{(p) => <select {...p} className="input" value={f.branch} onChange={set('branch')}><option value="">Choose a branch</option>{site.branches.filter((b) => me?.role === 'manager' ? me.branch_ids.includes(b.id) : true).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>}
          {lines.length > 0 && (
            <details style={{ marginBottom: 12 }} open={!!discount || undefined}>
              <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Discount{discount ? ` · ${discount.type === 'percent' ? `${discount.value}%` : money(discount.value)} (${discount.reason})` : ''}</summary>
              <div style={{ paddingTop: 10 }}>
                {quote.error && discount && <div className="alert error" role="alert">{quote.error}</div>}
                <div className="seg" role="group" aria-label="Discount type" style={{ marginBottom: 8 }}>
                  <button type="button" aria-pressed={dForm.type === 'percent'} onClick={() => setDForm({ ...dForm, type: 'percent' })}>Percent</button>
                  <button type="button" aria-pressed={dForm.type === 'amount'} onClick={() => setDForm({ ...dForm, type: 'amount' })}>Amount</button>
                </div>
                <div className="grid g2">
                  <Field label={dForm.type === 'percent' ? 'Percent off' : 'Amount off'}>{(p) => <input {...p} className="input" inputMode="decimal" placeholder={dForm.type === 'percent' ? 'e.g. 10' : 'e.g. 5.00'} value={dForm.value} onChange={(e) => setDForm({ ...dForm, value: e.target.value })} />}</Field>
                  <Field label="Reason (recorded)">{(p) => <input {...p} className="input" maxLength={200} placeholder="e.g. loyalty, complaint" value={dForm.reason} onChange={(e) => setDForm({ ...dForm, reason: e.target.value })} />}</Field>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="button" className="btn sm" disabled={!money2.test(dForm.value) || Number(dForm.value) <= 0 || dForm.reason.trim().length < 3} onClick={() => setDiscount({ ...dForm, value: dForm.value.trim(), reason: dForm.reason.trim() })}>Apply discount</button>
                  {discount && <button type="button" className="btn sm secondary" onClick={() => { setDiscount(null); setDForm({ type: 'percent', value: '', reason: '' }) }}>Remove</button>}
                </div>
                {me?.role === 'cashier' && <p className="hint">Larger discounts need a manager.</p>}
              </div>
            </details>
          )}
          <div className="seg" role="group" aria-label="Order type" style={{ width: '100%', marginBottom: 12 }}>
            {[['dine_in', 'Dine in'], ['pickup', 'Takeaway'], ...(site.delivery_enabled ? [['delivery', 'Delivery']] : [])].map(([v, l]) => <button type="button" key={v} style={{ flex: 1 }} aria-pressed={f.fulfilment === v} onClick={() => setF({ ...f, fulfilment: v })}>{l}</button>)}
          </div>
          <details style={{ marginBottom: 12 }} open={f.fulfilment === 'delivery' || !!f.contact_name || !!f.contact_phone || undefined}>
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Customer and notes</summary>
            <div style={{ paddingTop: 10 }}>
              <Field label="Customer name (optional)">{(p) => <input {...p} className="input" placeholder="Enter the customer name" value={f.contact_name} onChange={set('contact_name')} />}</Field>
              <div className="grid g2"><Field label="Phone" error={errors.contact_phone}>{(p) => <input {...p} className="input" type="tel" placeholder="Enter phone number" value={f.contact_phone} onChange={set('contact_phone')} />}</Field>
                <Field label="Email (for the receipt)">{(p) => <input {...p} className="input" type="email" placeholder="Optional" value={f.contact_email} onChange={set('contact_email')} />}</Field></div>
              {f.fulfilment === 'delivery' && <>{errors.address && <p className="err">{errors.address}</p>}<div className="grid g2"><Field label="Street">{(p) => <input {...p} className="input" placeholder="Delivery address" value={f.line1} onChange={set('line1')} />}</Field><Field label="City">{(p) => <input {...p} className="input" placeholder="City" value={f.city} onChange={set('city')} />}</Field></div></>}
              <Field label="Instructions">{(p) => <input {...p} className="input" placeholder="e.g. table 4, no pepper" value={f.notes} onChange={set('notes')} />}</Field>
            </div>
          </details>
          <div className="seg" role="group" aria-label="Payment method" style={{ width: '100%', marginBottom: 12 }}>
            {[['cash', 'Cash'], ...(site.online_payments ? [['mobile_money', 'Mobile money']] : []), ['pay_later', 'Pay later']].map(([v, l]) => <button type="button" key={v} style={{ flex: 1 }} aria-pressed={f.payment === v} onClick={() => setF({ ...f, payment: v })}>{l}</button>)}
          </div>
          {f.payment === 'cash' && <>
            {cashOptions.length > 0 && <div className="quick-cash">{cashOptions.map((v, i) => <button type="button" key={v} className="btn sm secondary" onClick={() => setF({ ...f, amount_received: v.toFixed(2) })}>{i === 0 && v === total ? 'Exact' : money(v.toFixed(2))}</button>)}</div>}
            <Field label="Cash received" error={errors.amount_received}>{(p) => <input {...p} className="input" inputMode="decimal" placeholder="e.g. 50.00" value={f.amount_received} onChange={set('amount_received')} />}</Field>
            {change !== null && change >= 0 && <p style={{ fontSize: '1.15rem' }}>Change due: <b>{money(change.toFixed(2))}</b></p>}</>}
          {f.payment === 'mobile_money' && <Field label="Mobile money number" error={errors.payer_phone}>{(p) => <input {...p} className="input" type="tel" placeholder="Customer mobile number" value={f.payer_phone} onChange={set('payer_phone')} />}</Field>}
          <button className="btn lg" style={{ width: '100%' }} disabled={busy || !items.length || !!quote.error}>{busy ? <Spinner /> : `Charge ${quote.data ? money(quote.data.total) : ''}`.trim()}</button>
          {lines.length > 0 && <button type="button" className="btn ghost sm" style={{ width: '100%', marginTop: 6 }} onClick={() => setLines([])}>Clear order</button>}
        </div>
      </form>
      {picking && <OptionPicker p={picking} onClose={() => setPicking(null)} onAdd={(l) => { addProduct(picking, l); setPicking(null) }} />}
    </div>
  )
}

function OptionPicker({ p, onClose, onAdd }: { p: PublicProduct; onClose: () => void; onAdd: (l: { variation_id: number | null; quantity: number; addons: Record<number, number>; instructions: string }) => void }) {
  const { money } = useSite()
  const [vid, setVid] = useState<number | null>(p.variations.find((v) => v.is_default)?.id ?? null)
  const [adds, setAdds] = useState<Record<number, number>>({})
  const [note, setNote] = useState('')
  const [qty, setQty] = useState(1)
  return (
    <Modal title={p.name} onClose={onClose}>
      {p.variations.length > 0 && <Field label="Option">{(f) => <select {...f} className="input" value={vid ?? ''} onChange={(e) => setVid(e.target.value ? Number(e.target.value) : null)}>{!p.variations.some((v) => v.is_default) && <option value="">Select…</option>}{p.variations.map((v) => <option key={v.id} value={v.id}>{v.name} {Number(v.price_delta) > 0 ? `(+${money(v.price_delta)})` : ''}</option>)}</select>}</Field>}
      {p.addons.map((a) => <label key={a.id} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}><input className="input" style={{ width: 64 }} type="number" min={0} max={a.max_quantity} value={adds[a.id] ?? 0} onChange={(e) => setAdds({ ...adds, [a.id]: Math.max(0, Math.min(a.max_quantity, Number(e.target.value) || 0)) })} aria-label={`${a.name} quantity`} />{a.name} <span className="muted">+{money(a.price)}</span></label>)}
      {p.allow_instructions && <Field label="Instructions">{(f) => <input {...f} className="input" placeholder="e.g. no pepper" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>}
      <Field label="Quantity">{(f) => <input {...f} className="input" type="number" min={1} max={50} value={qty} onChange={(e) => setQty(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} />}</Field>
      <button className="btn" disabled={p.variations.length > 0 && vid === null} onClick={() => onAdd({ variation_id: vid, quantity: qty, addons: adds, instructions: note.trim() })}>Add to order</button>
    </Modal>
  )
}

/* ------------------------------------------------------------------ shift */
function ShiftPanel({ data, loading, reload }: { data: { shift: ShiftData | null; adjustments: Adj[] } | null; loading: boolean; reload: () => void }) {
  const { site, money } = useSite()
  const { me } = useAuth()
  const toast = useToast()
  const [opening, setOpening] = useState('')
  const [branch, setBranch] = useState('')
  const [counted, setCounted] = useState('')
  const [notes, setNotes] = useState('')
  const [adj, setAdj] = useState({ kind: 'cash_out', amount: '', reason: '' })
  const [error, setError] = useState('')
  const [closed, setClosed] = useState<ShiftData | null>(null)
  const myBranches = site.branches.filter((b) => me?.branch_ids.includes(b.id))
  useEffect(() => { if (myBranches.length === 1) setBranch(String(myBranches[0].id)) }, [myBranches.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn: () => Promise<unknown>, ok: string) => { setError(''); try { await fn(); toast(ok); reload() } catch (e) { setError(msg(e)) } }
  if (loading && !data) return <Skeleton h={140} />
  const s = data?.shift
  if (closed) return (
    <div className="card" style={{ maxWidth: 480 }}><h2>Shift closed</h2>
      <p>Expected {money(closed.expected_cash ?? '0')} · Counted {money(closed.actual_cash ?? '0')}</p>
      <p style={{ fontSize: '1.3rem' }}>Variance: <b style={{ color: Number(closed.variance) === 0 ? 'var(--ok)' : 'var(--danger)' }}>{money(closed.variance ?? '0')}</b></p>
      <button className="btn" onClick={() => { setClosed(null); reload() }}>Done</button></div>
  )
  if (!s) return (
    <form className="card" style={{ maxWidth: 420 }} noValidate onSubmit={(e) => { e.preventDefault(); if (!money2.test(opening)) return setError('Enter the opening cash, e.g. 100.00.'); void run(() => api('/cashier/shift/open/', { body: { opening_cash: opening, ...(branch ? { branch_id: Number(branch) } : {}) } }), 'Shift opened.') }}>
      <h2 style={{ fontSize: '1.2rem' }}>Open your shift</h2>
      {error && <div className="alert error" role="alert">{error}</div>}
      {myBranches.length > 1 && <Field label="Branch">{(p) => <select {...p} className="input" value={branch} onChange={(e) => setBranch(e.target.value)}><option value="">Choose a branch</option>{myBranches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>}
      <Field label="Opening cash in the till">{(p) => <input {...p} className="input" inputMode="decimal" placeholder="e.g. 100.00" value={opening} onChange={(e) => setOpening(e.target.value)} />}</Field>
      <button className="btn">Open shift</button>
    </form>
  )
  const t = s.totals!
  return (
    <div className="grid g2" style={{ alignItems: 'start' }}>
      <div className="card"><h2 style={{ fontSize: '1.2rem' }}>{s.branch_name}</h2>
        <p className="muted">Opened {new Date(s.opened_at).toLocaleString()}</p>
        <table className="tbl"><tbody>
          <tr><td>Opening cash</td><td style={{ textAlign: 'right' }}>{money(s.opening_cash)}</td></tr>
          <tr><td>Cash sales ({t.cash_transactions})</td><td style={{ textAlign: 'right' }}>{money(t.cash_sales)}</td></tr>
          <tr><td>Cash refunds</td><td style={{ textAlign: 'right' }}>−{money(t.cash_refunds)}</td></tr>
          <tr><td>Approved cash in / out</td><td style={{ textAlign: 'right' }}>+{money(t.cash_in)} / −{money(t.cash_out)}</td></tr>
          <tr><td><b>Expected cash in till</b></td><td style={{ textAlign: 'right' }}><b>{money(s.expected_cash ?? '0')}</b></td></tr>
          <tr><td className="muted">Mobile money sales ({t.mobile_money_transactions})</td><td className="muted" style={{ textAlign: 'right' }}>{money(t.mobile_money_sales)}</td></tr>
        </tbody></table>
        <h3 style={{ marginTop: 16 }}>Cash adjustments</h3>
        {(data?.adjustments ?? []).length === 0 ? <p className="muted">None.</p> : data!.adjustments.map((a) => <p key={a.id}>{a.kind === 'cash_in' ? '+' : '−'}{money(a.amount)} · {a.reason} · <span className={`badge ${a.status === 'approved' ? 'active' : a.status === 'rejected' ? 'suspended' : ''}`}>{a.status}</span></p>)}
        <form noValidate onSubmit={(e) => { e.preventDefault(); if (!money2.test(adj.amount) || adj.reason.trim().length < 3) return setError('Enter an amount and a reason.'); void run(async () => { await api(`/cashier/shifts/${s.id}/adjustments/`, { body: adj }); setAdj({ kind: 'cash_out', amount: '', reason: '' }) }, 'Adjustment sent for approval.') }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <select className="input" style={{ width: 150 }} aria-label="Adjustment type" value={adj.kind} onChange={(e) => setAdj({ ...adj, kind: e.target.value })}><option value="cash_out">Cash out</option><option value="cash_in">Cash in</option></select>
            <input className="input" style={{ width: 110 }} placeholder="Amount" aria-label="Adjustment amount" value={adj.amount} onChange={(e) => setAdj({ ...adj, amount: e.target.value })} />
            <input className="input" style={{ flex: 1, minWidth: 140 }} placeholder="Reason (needs manager approval)" aria-label="Adjustment reason" value={adj.reason} onChange={(e) => setAdj({ ...adj, reason: e.target.value })} />
            <button className="btn sm secondary">Request</button></div>
        </form>
      </div>
      <form className="card" noValidate onSubmit={(e: FormEvent) => { e.preventDefault(); if (!money2.test(counted)) return setError('Enter the cash you counted.'); void run(async () => { setClosed(await api<ShiftData>(`/cashier/shifts/${s.id}/close/`, { body: { actual_cash: counted, notes } })) }, 'Shift closed.') }}>
        <h2 style={{ fontSize: '1.2rem' }}>Close shift</h2>
        {error && <div className="alert error" role="alert">{error}</div>}
        <p className="muted">Count the cash in the till and enter the total. The system compares it with what is expected.</p>
        <Field label="Counted cash">{(p) => <input {...p} className="input" inputMode="decimal" placeholder="e.g. 250.00" value={counted} onChange={(e) => setCounted(e.target.value)} />}</Field>
        <Field label="Notes (required if there is a difference)">{(p) => <input {...p} className="input" placeholder="Explain any difference" value={notes} onChange={(e) => setNotes(e.target.value)} />}</Field>
        <button className="btn danger">Close shift</button>
      </form>
    </div>
  )
}

/* ------------------------------------------------------------------ my sales */
function Sales() {
  const { money } = useSite()
  const d = useAsync(() => api<{ periods: Record<'today' | 'week' | 'month', { total: string; cash: string; mobile_money: string; transactions: number; orders_processed: number }>; recent_transactions: { reference: string; order_number: string; method: string; amount: string; paid_at: string }[] }>('/cashier/dashboard/'), [])
  if (d.loading) return <Skeleton h={160} />
  if (d.error || !d.data) return <ErrorState message={d.error ?? 'Could not load.'} onRetry={d.reload} />
  return (
    <>
      <div className="grid g3">{(['today', 'week', 'month'] as const).map((k) => { const p = d.data!.periods[k]; return (
        <div className="card stat" key={k}><span className="muted">{k === 'today' ? 'Today' : k === 'week' ? 'Last 7 days' : 'This month'}</span><b>{money(p.total)}</b>
          <span>Cash {money(p.cash)} · Mobile {money(p.mobile_money)}</span><span className="muted">{p.orders_processed} orders · {p.transactions} payments</span></div>) })}</div>
      <h2 style={{ fontSize: '1.2rem', marginTop: 20 }}>My recent transactions</h2>
      <div className="card table-wrap">{!d.data.recent_transactions.length ? <Empty title="No transactions yet" /> : (
        <table className="tbl"><thead><tr><th>When</th><th>Order</th><th>Method</th><th>Amount</th></tr></thead><tbody>
          {d.data.recent_transactions.map((t) => <tr key={t.reference}><td>{new Date(t.paid_at).toLocaleString()}</td><td>{t.order_number}</td><td>{t.method}</td><td>{money(t.amount)}</td></tr>)}
        </tbody></table>)}</div>
    </>
  )
}

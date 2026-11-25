import { Home, LifeBuoy, LogOut, MapPin, Package, Shield, User } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, NavLink, Navigate, Outlet, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, tokenStore, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'

const msg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

export function AccountLayout() {
  const { me, loading, logout } = useAuth()
  const { site } = useSite()
  const navigate = useNavigate()
  if (loading) return <div className="container section"><Spinner /></div>
  if (!me) return <Navigate to="/login?next=/account" replace />
  if (me.role !== 'customer') return <Navigate to="/manage" replace />
  const items = [['/account', 'Overview', Home, true], ['/account/orders', 'My orders', Package, false], ['/account/profile', 'Profile', User, false],
    ['/account/addresses', 'Addresses', MapPin, false], ['/account/security', 'Security', Shield, false], ['/account/support', 'Support', LifeBuoy, false]] as const
  return (
    <div className="admin" style={{ minHeight: 'calc(100vh - 64px)' }}>
      <aside className="side" aria-label="My account">
        <strong style={{ padding: '6px 12px' }}>{me.full_name || me.email}</strong>
        {items.map(([to, l, Icon, end]) => <NavLink key={to} to={to} end={end}><Icon size={18} aria-hidden /> {l}</NavLink>)}
        <Link to="/menu" style={{ marginTop: 8 }}>Back to {site.restaurant.name}</Link>
        <button className="btn secondary sm" style={{ marginTop: 'auto' }} onClick={() => { logout(); navigate('/') }}><LogOut size={16} aria-hidden /> Sign out</button>
      </aside>
      <div className="main"><Outlet /></div>
    </div>
  )
}

/* ------------------------------------------------------------------ orders */
export type OrderRow = { id: number; number: string; contact_name: string; status: string; status_label: string; fulfilment: string; payment_method: string; payment_status: string; total: string; item_count: number; branch_name: string; created_at: string; cancellation_requested: boolean }
type Detail = OrderRow & {
  contact_name: string; contact_phone: string; delivery_address: Record<string, string>; customer_notes: string; subtotal: string; tax_total: string; tax_rate_percent: string; delivery_fee: string
  amount_paid: string; discount_total: string; can_cancel: boolean; can_request_cancel: boolean; cancellation_reason: string
  payments: { id: number; method: string; status: string; amount: string; receipt_id: number | null }[]
  items: { product_name: string; variation_name: string; unit_price: string; quantity: number; line_total: string; addons: { name: string; quantity: number }[]; instructions: string }[]
  history: { status: string; status_label: string; note: string; created_at: string; actor_role: string }[]
}

function PayPanel({ order, onChange }: { order: Detail; onChange: (o: Detail) => void }) {
  const toast = useToast()
  const [phone, setPhone] = useState(order.contact_phone)
  const [busy, setBusy] = useState(false)
  const pending = order.payments.find((p) => p.status === 'pending')
  // While a payment is pending, ask the server to verify it with the provider (the browser never decides).
  useEffect(() => {
    if (!pending) return
    const t = setInterval(async () => { try { await api(`/payments/my/${pending.id}/`); onChange(await api<Detail>(`/orders/my/${order.id}/`)) } catch { /* retry */ } }, 6000)
    return () => clearInterval(t)
  }, [pending?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  async function pay() {
    setBusy(true)
    try {
      const r = await api<{ redirect_url: string }>('/payments/initiate/', { body: { order_id: order.id, phone }, headers: { 'Idempotency-Key': crypto.randomUUID() } })
      if (r.redirect_url) window.open(r.redirect_url, '_blank', 'noopener')
      onChange(await api<Detail>(`/orders/my/${order.id}/`)); toast('Approve the payment on your phone.')
    } catch (e) { toast(msg(e)) } finally { setBusy(false) }
  }
  const receipts = order.payments.filter((p) => p.receipt_id)
  return (
    <div style={{ marginTop: 12 }}>
      {order.payment_method === 'mobile_money' && ['awaiting_payment', 'payment_processing'].includes(order.status) && order.payment_status !== 'paid' && (
        pending ? <div className="alert" aria-live="polite">Waiting for payment confirmation… <Spinner /></div> : (
          <div className="alert"><label>Mobile money number <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Enter your phone number" /></label>
            <button className="btn" style={{ marginTop: 8 }} disabled={busy} onClick={pay}>{busy ? <Spinner /> : 'Pay now'}</button></div>))}
      {order.payments.some((p) => p.status === 'failed') && !pending && order.payment_status !== 'paid' && <p className="err">The last payment attempt did not go through.</p>}
      {receipts.length > 0 ? receipts.map((p) => <p key={p.id}><Link className="btn sm secondary" to={`/receipts/${p.receipt_id}`}>View receipt</Link></p>) : <p className="hint">A receipt is issued as soon as the payment is confirmed.</p>}
    </div>
  )
}

export function StatusBadge({ s, label }: { s: string; label: string }) {
  const cls = s === 'completed' ? 'active' : s === 'cancelled' || s === 'refunded' ? 'suspended' : ''
  return <span className={`badge ${cls}`}>{label}</span>
}

export function Overview() {
  useDocumentTitle('My account')
  const { money } = useSite()
  const d = useAsync(() => api<{ total_orders: number; current_orders: number; completed_orders: number; cancelled_orders: number; recent_orders: OrderRow[]; recent_transactions: OrderRow[]; recent_activity: { order_id: number; order_number: string; status_label: string; created_at: string }[] }>('/customers/dashboard/'), [])
  const stat = (l: string, v?: number) => <div className="card stat"><span className="muted">{l}</span>{d.loading ? <Skeleton h={30} w="50%" /> : <b>{v ?? 0}</b>}</div>
  return (
    <>
      <h1 className="page-title">Welcome back</h1>
      {d.error && <ErrorState message={d.error} onRetry={d.reload} />}
      <div className="grid g3" style={{ marginBottom: 20 }}>{stat('Total orders', d.data?.total_orders)}{stat('Current orders', d.data?.current_orders)}{stat('Completed', d.data?.completed_orders)}{stat('Cancelled', d.data?.cancelled_orders)}</div>
      <div className="grid g2">
        <div className="card"><h2 style={{ fontSize: '1.1rem' }}>Recent orders</h2>
          {!d.data?.recent_orders.length ? <Empty title="No orders yet"><Link className="btn" to="/menu">Start ordering</Link></Empty> :
            d.data.recent_orders.map((o) => <Link key={o.id} to={`/account/orders/${o.id}`} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', textDecoration: 'none', color: 'inherit' }}><span>{o.number} <StatusBadge s={o.status} label={o.status_label} /></span><b>{money(o.total)}</b></Link>)}
        </div>
        <div className="card"><h2 style={{ fontSize: '1.1rem' }}>Recent activity</h2>
          {!d.data?.recent_activity.length ? <p className="muted">Nothing yet.</p> : d.data.recent_activity.map((a, i) => <p key={i} style={{ margin: '6px 0' }}>{a.order_number}: <b>{a.status_label}</b> <span className="muted">{new Date(a.created_at).toLocaleString()}</span></p>)}
          <h2 style={{ fontSize: '1.1rem', marginTop: 16 }}>Recent transactions</h2>
          {!d.data?.recent_transactions.length ? <p className="muted">Payments will appear here once online payment is enabled.</p> : d.data.recent_transactions.map((o) => <p key={o.id} style={{ margin: '6px 0' }}>{o.number}: {money(o.total)} ({o.payment_status})</p>)}
        </div>
      </div>
    </>
  )
}

export function Orders() {
  useDocumentTitle('My orders')
  const { money } = useSite()
  const [page, setPage] = useState(1)
  const list = useAsync(() => api<Page<OrderRow>>('/orders/my/', { params: { page } }), [page])
  return (
    <>
      <h1 className="page-title">My orders</h1>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={100} /> : !list.data?.results.length ? <Empty title="You have not placed an order yet"><Link className="btn" to="/menu">Browse the menu</Link></Empty> : (
          <table className="tbl"><thead><tr><th>Order</th><th>Date</th><th>Status</th><th>Total</th><th /></tr></thead><tbody>
            {list.data.results.map((o) => <tr key={o.id}><td>{o.number}</td><td>{new Date(o.created_at).toLocaleDateString()}</td><td><StatusBadge s={o.status} label={o.status_label} /></td><td>{money(o.total)}</td><td><Link className="btn sm secondary" to={`/account/orders/${o.id}`}>View</Link></td></tr>)}
          </tbody></table>
        )}
      </div>
      {list.data && (list.data.next || list.data.previous) && <div className="toolbar" style={{ marginTop: 12 }}><button className="btn sm secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button><span className="muted">Page {page}</span><button className="btn sm secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button></div>}
    </>
  )
}

const POLL_MS = 10000
const FINAL = ['completed', 'cancelled', 'refunded']

export function OrderDetail() {
  const { id = '' } = useParams()
  const { money } = useSite()
  const toast = useToast()
  const [order, setOrder] = useState<Detail | null>(null)
  const [error, setError] = useState('')
  const [live, setLive] = useState(true)

  // Near-real-time tracking: poll while the tab is visible and the order is still moving.
  // (WebSocket push arrives with the realtime phase; polling stays as the fallback.)
  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      if (stop) return
      if (!document.hidden) {
        try {
          const o = await api<Detail>(`/orders/my/${id}/`)
          if (stop) return
          setOrder(o); setError(''); setLive(!FINAL.includes(o.status))
          if (FINAL.includes(o.status)) return
        } catch (e) { if (!stop) setError(msg(e)); if (e instanceof ApiError && e.status === 404) return }
      }
      timer = setTimeout(tick, POLL_MS)
    }
    void tick()
    return () => { stop = true; clearTimeout(timer) }
  }, [id])
  useDocumentTitle(order ? `Order ${order.number}` : 'Order')

  async function cancel() {
    const reason = prompt(order?.can_cancel ? 'Reason for cancelling (optional):' : 'Why would you like to cancel?') ?? null
    if (reason === null) return
    try {
      const r = await api<{ outcome: string; order: Detail }>(`/orders/my/${id}/cancel/`, { body: { reason } })
      setOrder(r.order)
      toast(r.outcome === 'cancelled' ? 'Order cancelled.' : 'Cancellation requested. The restaurant will respond.')
    } catch (e) { toast(msg(e)) }
  }
  if (!order) return error ? <ErrorState message={error} /> : <Skeleton h={200} />
  const a = order.delivery_address
  return (
    <>
      <p><Link to="/account/orders">← All orders</Link></p>
      <div className="toolbar"><h1 style={{ fontSize: '1.7rem', margin: 0 }}>Order {order.number}</h1><StatusBadge s={order.status} label={order.status_label} />{live && <span className="muted" aria-live="polite">Updating automatically</span>}</div>
      {error && <div className="alert error">{error}</div>}
      {order.cancellation_requested && <div className="alert warn">Cancellation requested. Waiting for the restaurant.</div>}
      <div className="grid g2" style={{ alignItems: 'start' }}>
        <div className="card"><h2 style={{ fontSize: '1.1rem' }}>Tracking</h2>
          <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {order.history.map((h, i) => <li key={i} style={{ display: 'flex', gap: 10, paddingBottom: 12 }}><span aria-hidden style={{ width: 12, height: 12, borderRadius: '50%', background: i === order.history.length - 1 ? 'var(--brand)' : 'var(--border)', marginTop: 6 }} /><div><b>{h.status_label}</b><div className="muted" style={{ fontSize: '.85rem' }}>{new Date(h.created_at).toLocaleString()}{h.note ? ` · ${h.note}` : ''}</div></div></li>)}
          </ol>
          {(order.can_cancel || order.can_request_cancel) && <button className="btn danger sm" onClick={cancel}>{order.can_cancel ? 'Cancel order' : 'Request cancellation'}</button>}
        </div>
        <div className="card"><h2 style={{ fontSize: '1.1rem' }}>Items</h2>
          {order.items.map((i, k) => <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}><span>{i.quantity} × {i.product_name}{i.variation_name ? ` (${i.variation_name})` : ''}{i.addons.length > 0 && <span className="muted"> · {i.addons.map((x) => `${x.quantity}× ${x.name}`).join(', ')}</span>}{i.instructions && <div className="muted" style={{ fontSize: '.85rem' }}>Note: {i.instructions}</div>}</span><span>{money(i.line_total)}</span></div>)}
          <hr style={{ border: 0, borderTop: '1px solid var(--border)' }} />
          <div style={{ display: 'grid', gap: 4 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Subtotal</span><span>{money(order.subtotal)}</span></div>
            {Number(order.tax_rate_percent) > 0 && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Tax</span><span>{money(order.tax_total)}</span></div>}
            {order.fulfilment === 'delivery' && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Delivery</span><span>{money(order.delivery_fee)}</span></div>}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700 }}><span>Total</span><span>{money(order.total)}</span></div>
          </div>
          <p className="muted" style={{ marginTop: 12 }}>Payment: {order.payment_method === 'cash' ? 'cash on ' + (order.fulfilment === 'delivery' ? 'delivery' : 'pickup') : order.payment_method} · {order.payment_status}</p>
          <p className="muted">{order.fulfilment === 'delivery' ? `Delivery to ${a.line1}${a.line2 ? ', ' + a.line2 : ''}, ${a.city}` : `Pickup at ${order.branch_name}`}</p>
          <PayPanel order={order} onChange={setOrder} />
        </div>
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ profile */
type Prof = { email: string; full_name: string; phone: string; avatar: string | null; preferences: { order_emails: boolean; promotions: boolean } }
export function Profile() {
  useDocumentTitle('Profile')
  const toast = useToast()
  const { reload } = useAuth()
  const p = useAsync(() => api<Prof>('/customers/me/'), [])
  const [v, setV] = useState({ full_name: '', phone: '' })
  const [prefs, setPrefs] = useState({ order_emails: true, promotions: false })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [emailOpen, setEmailOpen] = useState(false)
  useEffect(() => { if (p.data) { setV({ full_name: p.data.full_name, phone: p.data.phone }); setPrefs(p.data.preferences) } }, [p.data])

  async function save(e: FormEvent) {
    e.preventDefault()
    if (!v.full_name.trim()) return setErrors({ full_name: 'Enter your full name.' })
    setBusy(true); setErrors({})
    try { await api('/customers/me/', { method: 'PATCH', body: { ...v, preferences: prefs } }); toast('Profile saved.'); await reload(); p.reload() } catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Error' }) } finally { setBusy(false) }
  }
  async function avatar(file: File | undefined) {
    if (!file) return
    const fd = new FormData(); fd.append('image', file)
    try { await api('/customers/me/avatar/', { body: fd }); toast('Photo updated.'); p.reload() } catch (err) { toast(err instanceof ApiError ? (err.fieldErrors().image ?? err.message) : 'Upload failed.') }
  }
  return (
    <>
      <h1 className="page-title">Profile</h1>
      {p.error && <ErrorState message={p.error} onRetry={p.reload} />}
      {p.loading ? <Skeleton h={160} /> : p.data && (
        <form className="card" style={{ maxWidth: 560 }} onSubmit={save} noValidate>
          {errors.form && !errors.full_name && !errors.phone && <div className="alert error">{errors.form}</div>}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
            {p.data.avatar ? <img src={p.data.avatar} alt="Your photo" width={72} height={72} style={{ borderRadius: '50%', objectFit: 'cover' }} /> : <span className="swatch" style={{ width: 72, height: 72, borderRadius: '50%' }} aria-hidden />}
            <label className="btn sm secondary">Change photo<input type="file" hidden accept="image/png,image/jpeg,image/webp" onChange={(e) => avatar(e.target.files?.[0])} /></label>
          </div>
          <Field label="Full name" error={errors.full_name}>{(f) => <input {...f} className="input" placeholder="Enter your full name" value={v.full_name} onChange={(e) => setV({ ...v, full_name: e.target.value })} />}</Field>
          <Field label="Phone number" error={errors.phone}>{(f) => <input {...f} className="input" type="tel" placeholder="Enter your phone number" value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />}</Field>
          <Field label="Email address" hint="Changing it requires your password and a code sent to the new address.">{(f) => <span style={{ display: 'flex', gap: 8 }}><input {...f} className="input" value={p.data!.email} readOnly /><button type="button" className="btn secondary" onClick={() => setEmailOpen(true)}>Change</button></span>}</Field>
          <fieldset style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14 }}><legend>Notifications</legend>
            <label style={{ display: 'block' }}><input type="checkbox" checked={prefs.order_emails} onChange={(e) => setPrefs({ ...prefs, order_emails: e.target.checked })} /> Email me when my order status changes</label>
            <label style={{ display: 'block' }}><input type="checkbox" checked={prefs.promotions} onChange={(e) => setPrefs({ ...prefs, promotions: e.target.checked })} /> Send me offers and news</label>
          </fieldset>
          <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save changes'}</button>
        </form>
      )}
      {emailOpen && <EmailChange onClose={() => setEmailOpen(false)} onDone={() => { setEmailOpen(false); void reload(); p.reload() }} />}
    </>
  )
}

function EmailChange({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [step, setStep] = useState<'request' | 'confirm'>('request')
  const [v, setV] = useState({ new_email: '', password: '', code: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault(); setError('')
    if (step === 'request') {
      if (!/^\S+@\S+\.\S+$/.test(v.new_email)) return setError('Enter a valid email address.')
      if (!v.password) return setError('Enter your password.')
    } else if (v.code.trim().length !== 6) return setError('Enter the 6-character code.')
    setBusy(true)
    try {
      if (step === 'request') { await api('/customers/me/email-change/', { body: { new_email: v.new_email.trim(), password: v.password } }); setStep('confirm') }
      else { const t = await api<{ access: string; refresh: string }>('/customers/me/email-change/confirm/', { body: { code: v.code.trim() } }); tokenStore.set(t); toast('Email address changed.'); onDone() }
    } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }
  return (
    <Modal title="Change email address" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {error && <div className="alert error" role="alert">{error}</div>}
        {step === 'request' ? <>
          <Field label="New email address">{(f) => <input {...f} className="input" type="email" placeholder="Enter your new email address" value={v.new_email} onChange={(e) => setV({ ...v, new_email: e.target.value })} />}</Field>
          <Field label="Current password">{(f) => <input {...f} className="input" type="password" placeholder="Enter your password" value={v.password} onChange={(e) => setV({ ...v, password: e.target.value })} />}</Field>
        </> : <>
          <div className="alert">If the address can be used, a code was sent to it. It expires in 10 minutes.</div>
          <Field label="Verification code">{(f) => <input {...f} className="input" maxLength={6} placeholder="Enter the 6-character code" value={v.code} onChange={(e) => setV({ ...v, code: e.target.value.toUpperCase() })} />}</Field>
        </>}
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : step === 'request' ? 'Send code' : 'Confirm change'}</button>
      </form>
    </Modal>
  )
}

/* ------------------------------------------------------------------ addresses */
type Addr = { id: number; label: string; recipient_name: string; phone: string; line1: string; line2: string; city: string; delivery_notes: string; is_default: boolean }
export function Addresses() {
  useDocumentTitle('Addresses')
  const toast = useToast()
  const list = useAsync(() => api<Addr[]>('/customers/addresses/'), [])
  const [edit, setEdit] = useState<Addr | 'new' | null>(null)
  const del = async (a: Addr) => { if (!confirm('Delete this address?')) return; try { await api(`/customers/addresses/${a.id}/`, { method: 'DELETE' }); list.reload() } catch (e) { toast(msg(e)) } }
  const makeDefault = async (a: Addr) => { try { await api(`/customers/addresses/${a.id}/`, { method: 'PATCH', body: { is_default: true } }); list.reload() } catch (e) { toast(msg(e)) } }
  return (
    <>
      <div className="toolbar"><h1 style={{ fontSize: '1.7rem', margin: 0, flex: 1 }}>Addresses</h1><button className="btn" onClick={() => setEdit('new')}>Add address</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {list.loading ? <Skeleton h={100} /> : !list.data?.length ? <Empty title="No saved addresses">Add one to check out faster.</Empty> : (
        <div className="grid g2">{list.data.map((a) => <div className="card" key={a.id}><b>{a.label}</b> {a.is_default && <span className="badge active">default</span>}<p style={{ margin: '6px 0' }}>{a.line1}{a.line2 ? `, ${a.line2}` : ''}<br />{a.city}{a.phone && <><br />{a.phone}</>}</p>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}><button className="btn sm secondary" onClick={() => setEdit(a)}>Edit</button>{!a.is_default && <button className="btn sm secondary" onClick={() => makeDefault(a)}>Make default</button>}<button className="btn sm danger" onClick={() => del(a)}>Delete</button></div></div>)}</div>
      )}
      {edit && <AddressForm initial={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
    </>
  )
}

function AddressForm({ initial, onClose, onSaved }: { initial: Addr | null; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ label: initial?.label ?? 'Home', line1: initial?.line1 ?? '', line2: initial?.line2 ?? '', city: initial?.city ?? '', phone: initial?.phone ?? '', delivery_notes: initial?.delivery_notes ?? '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })
  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!v.line1.trim()) local.line1 = 'Enter the street address.'
    if (!v.city.trim()) local.city = 'Enter the city.'
    setErrors(local)
    if (Object.keys(local).length) return
    setBusy(true)
    try { await api(initial ? `/customers/addresses/${initial.id}/` : '/customers/addresses/', { method: initial ? 'PATCH' : 'POST', body: v }); onSaved() } catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Error' }) } finally { setBusy(false) }
  }
  const f = (k: keyof typeof v, label: string, ph: string) => <Field label={label} error={errors[k]}>{(p) => <input {...p} className="input" placeholder={ph} value={v[k]} onChange={set(k)} />}</Field>
  return (
    <Modal title={initial ? 'Edit address' : 'Add address'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && !Object.keys(errors).some((k) => k !== 'form') && <div className="alert error">{errors.form}</div>}
        {f('label', 'Label', 'e.g. Home')}{f('line1', 'Street address', 'Enter your delivery address')}{f('line2', 'Apartment, landmark (optional)', 'e.g. near the market')}{f('city', 'City', 'Enter your city')}{f('phone', 'Phone for the courier (optional)', 'Enter your phone number')}{f('delivery_notes', 'Delivery notes (optional)', 'e.g. call on arrival')}
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save address'}</button>
      </form>
    </Modal>
  )
}

/* ------------------------------------------------------------------ security & support */
export function Security() {
  useDocumentTitle('Security')
  const toast = useToast()
  const { reload } = useAuth()
  const [v, setV] = useState({ current_password: '', new_password: '', confirm: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault(); setError('')
    if (!v.current_password) return setError('Enter your current password.')
    if (v.new_password.length < 10) return setError('Use at least 10 characters for the new password.')
    if (v.new_password !== v.confirm) return setError('The new passwords do not match.')
    setBusy(true)
    try {
      const t = await api<{ access: string; refresh: string }>('/auth/change-password/', { body: { current_password: v.current_password, new_password: v.new_password } })
      tokenStore.set(t) // every older session is now signed out; this one continues
      await reload(); setV({ current_password: '', new_password: '', confirm: '' }); toast('Password changed. Other devices were signed out.')
    } catch (err) { setError(err instanceof ApiError && Array.isArray(err.details) ? (err.details as string[]).join(' ') : msg(err)) } finally { setBusy(false) }
  }
  return (
    <>
      <h1 className="page-title">Security</h1>
      <form className="card" style={{ maxWidth: 480 }} onSubmit={submit} noValidate>
        <h2 style={{ fontSize: '1.1rem' }}>Change password</h2>
        {error && <div className="alert error" role="alert">{error}</div>}
        <Field label="Current password">{(p) => <input {...p} className="input" type="password" autoComplete="current-password" placeholder="Enter your current password" value={v.current_password} onChange={(e) => setV({ ...v, current_password: e.target.value })} />}</Field>
        <Field label="New password">{(p) => <input {...p} className="input" type="password" autoComplete="new-password" placeholder="Enter your new password" value={v.new_password} onChange={(e) => setV({ ...v, new_password: e.target.value })} />}</Field>
        <Field label="Confirm new password">{(p) => <input {...p} className="input" type="password" autoComplete="new-password" placeholder="Re-enter your new password" value={v.confirm} onChange={(e) => setV({ ...v, confirm: e.target.value })} />}</Field>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Change password'}</button>
      </form>
    </>
  )
}

export function Support() {
  useDocumentTitle('Support')
  const { site } = useSite()
  const r = site.restaurant
  return (
    <>
      <h1 className="page-title">Customer support</h1>
      <div className="card" style={{ maxWidth: 560 }}>
        <p>Need help with an order? Contact {r.name} directly and quote your order number.</p>
        {r.contact_phone && <p>Phone: <a href={`tel:${r.contact_phone}`}>{r.contact_phone}</a></p>}
        {r.contact_email && <p>Email: <a href={`mailto:${r.contact_email}`}>{r.contact_email}</a></p>}
        {!r.contact_phone && !r.contact_email && <p className="muted">The restaurant has not published contact details yet.</p>}
        <p><Link to="/policies/refund-and-cancellation-policy">Refund and cancellation policy</Link></p>
      </div>
    </>
  )
}

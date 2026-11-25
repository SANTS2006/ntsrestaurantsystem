import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { Empty, ErrorState, Field, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import type { Plan } from '../site/Pages'

type Settings = { platform_name: string; whatsapp_number: string; support_email: string }

export function PlatformSettings() {
  useDocumentTitle('Platform settings')
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api<Settings>('/platform/settings/'), [])
  const [v, setV] = useState<Settings>({ platform_name: '', whatsapp_number: '', support_email: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (data) setV(data) }, [data])

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    try {
      await api('/platform/settings/', { method: 'PATCH', body: v })
      toast('Settings saved.')
    } catch (err) {
      setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Unexpected error.' })
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <h1 className="page-title">Settings</h1>
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading ? <Skeleton h={160} /> : (
        <form className="card" style={{ maxWidth: 520 }} onSubmit={save} noValidate>
          <Field label="Platform name" error={errors.platform_name}>{(p) => <input {...p} className="input" placeholder="Enter the platform name" value={v.platform_name} onChange={(e) => setV({ ...v, platform_name: e.target.value })} />}</Field>
          <Field label="WhatsApp number" error={errors.whatsapp_number} hint="International format, digits only (e.g. 23276123456). Powers the floating WhatsApp button.">{(p) => <input {...p} className="input" inputMode="numeric" placeholder="Enter the WhatsApp number" value={v.whatsapp_number} onChange={(e) => setV({ ...v, whatsapp_number: e.target.value })} />}</Field>
          <Field label="Support email" error={errors.support_email}>{(p) => <input {...p} className="input" type="email" placeholder="Enter the support email" value={v.support_email} onChange={(e) => setV({ ...v, support_email: e.target.value })} />}</Field>
          <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save settings'}</button>
        </form>
      )}
    </>
  )
}

export function Plans() {
  useDocumentTitle('Subscription plans')
  const toast = useToast()
  const list = useAsync(() => api<Page<Plan & { is_active: boolean }>>('/platform/plans/'), [])
  const [f, setF] = useState({ name: '', slug: '', price: '', description: '', features: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  async function add(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    try {
      await api('/platform/plans/', { body: { ...f, features: f.features.split('\n').map((x) => x.trim()).filter(Boolean) } })
      setF({ name: '', slug: '', price: '', description: '', features: '' })
      toast('Plan created.')
      list.reload()
    } catch (err) {
      setErrors(err instanceof ApiError ? err.fieldErrors() : {})
    } finally {
      setBusy(false)
    }
  }
  async function toggle(p: Plan & { is_active: boolean }) {
    try {
      await api(`/platform/plans/${p.id}/`, { method: 'PATCH', body: { is_active: !p.is_active } })
      list.reload()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Failed.')
    }
  }
  return (
    <>
      <h1 className="page-title">Subscription plans</h1>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap" style={{ marginBottom: 20 }}>
        {list.loading ? <Skeleton h={80} /> : !list.data?.results.length ? <Empty title="No plans yet" /> : (
          <table className="tbl"><thead><tr><th>Name</th><th>Price</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((p) => (
              <tr key={p.id}><td>{p.name}</td><td>{p.price} {p.currency}/{p.interval}</td><td><span className={`badge ${p.is_active ? 'active' : 'suspended'}`}>{p.is_active ? 'active' : 'hidden'}</span></td>
                <td><button className="btn sm secondary" onClick={() => toggle(p)}>{p.is_active ? 'Hide' : 'Show'}</button></td></tr>
            ))}
          </tbody></table>
        )}
      </div>
      <form className="card" style={{ maxWidth: 520 }} onSubmit={add} noValidate>
        <h2 style={{ fontSize: '1.2rem' }}>Add a plan</h2>
        <Field label="Name" error={errors.name}>{(p) => <input {...p} className="input" placeholder="e.g. Starter" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
        <Field label="Slug" error={errors.slug}>{(p) => <input {...p} className="input" placeholder="e.g. starter" value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value })} />}</Field>
        <Field label="Monthly price" error={errors.price}>{(p) => <input {...p} className="input" inputMode="decimal" placeholder="e.g. 29.00" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} />}</Field>
        <Field label="Description" error={errors.description}>{(p) => <input {...p} className="input" placeholder="Short description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />}</Field>
        <Field label="Features (one per line)" error={errors.features}>{(p) => <textarea {...p} className="input" rows={4} placeholder="One feature per line" value={f.features} onChange={(e) => setF({ ...f, features: e.target.value })} />}</Field>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Create plan'}</button>
      </form>
    </>
  )
}

type Log = { id: number; created_at: string; action: string; actor_email: string | null; restaurant_name: string | null; ip_address: string | null }
export function AuditLog() {
  useDocumentTitle('Audit log')
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [dates, setDates] = useState({ from: '', to: '' })
  const [page, setPage] = useState(1)
  const list = useAsync(() => api<Page<Log>>('/platform/audit-logs/', { params: { action, actor, ...dates, page } }), [action, actor, dates.from, dates.to, page])
  return (
    <>
      <h1 className="page-title">Audit log</h1>
      <div className="toolbar"><input className="input" style={{ maxWidth: 280 }} placeholder="Filter by action, e.g. restaurant." aria-label="Filter by action" value={action} onChange={(e) => { setAction(e.target.value); setPage(1) }} />
        <input className="input" style={{ maxWidth: 220 }} placeholder="Actor email" aria-label="Filter by actor" value={actor} onChange={(e) => { setActor(e.target.value); setPage(1) }} />
        <label>From <input className="input" style={{ width: 150 }} type="date" value={dates.from} onChange={(e) => { setDates({ ...dates, from: e.target.value }); setPage(1) }} /></label>
        <label>To <input className="input" style={{ width: 150 }} type="date" value={dates.to} onChange={(e) => { setDates({ ...dates, to: e.target.value }); setPage(1) }} /></label></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={100} /> : !list.data?.results.length ? <Empty title="No audit entries" /> : (
          <table className="tbl"><thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Restaurant</th><th>IP</th></tr></thead><tbody>
            {list.data.results.map((l) => <tr key={l.id}><td>{new Date(l.created_at).toLocaleString()}</td><td>{l.action}</td><td>{l.actor_email ?? '–'}</td><td>{l.restaurant_name ?? '–'}</td><td>{l.ip_address ?? '–'}</td></tr>)}
          </tbody></table>
        )}
      </div>
      {list.data && (list.data.next || list.data.previous) && (
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button className="btn sm secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="muted">Page {page}</span>
          <button className="btn sm secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </>
  )
}

type PReport = {
  totals_by_currency: { currency: string; restaurants: number; orders: number; booked: string; net: string }[]
  restaurants: { id: number; name: string; slug: string; status: string; currency: string; orders: number; booked: string; collected: string; refunds: string; net: string }[]
  new_restaurants_by_month: { month: string; count: number }[]
  notes: string[]
}
const fmt = (cur: string, v: string) => `${cur} ${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export function PlatformReports() {
  useDocumentTitle('Platform reports')
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  const today = new Date()
  const [from, setFrom] = useState(iso(new Date(today.getTime() - 29 * 86400000)))
  const [to, setTo] = useState(iso(today))
  const r = useAsync(() => api<PReport>('/reports/platform/', { params: { from, to } }), [from, to])
  const d = r.data
  return (
    <>
      <h1 className="page-title">Platform reports</h1>
      <div className="toolbar">
        <label>From <input className="input" style={{ width: 150 }} type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>To <input className="input" style={{ width: 150 }} type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {r.loading && !d ? <Skeleton h={200} /> : d && (
        <>
          <div className="grid g3" style={{ marginBottom: 16 }}>
            {d.totals_by_currency.map((t) => <div className="card stat" key={t.currency}><span className="muted">{t.currency}: {t.restaurants} restaurant(s), {t.orders} orders</span><b>{fmt(t.currency, t.net)}</b><span className="muted">net received · {fmt(t.currency, t.booked)} booked</span></div>)}
          </div>
          <div className="card table-wrap">
            {!d.restaurants.length ? <Empty title="No restaurants" /> : (
              <table className="tbl"><thead><tr><th>Restaurant</th><th>Status</th><th>Orders</th><th>Booked</th><th>Collected</th><th>Refunds</th><th>Net</th></tr></thead><tbody>
                {d.restaurants.map((x) => <tr key={x.id}><td><b>{x.name}</b><div className="muted" style={{ fontSize: '.8rem' }}>{x.slug}</div></td><td><span className={`badge ${x.status === 'active' ? 'active' : 'suspended'}`}>{x.status}</span></td><td>{x.orders}</td><td>{fmt(x.currency, x.booked)}</td><td>{fmt(x.currency, x.collected)}</td><td>{fmt(x.currency, x.refunds)}</td><td><b>{fmt(x.currency, x.net)}</b></td></tr>)}
              </tbody></table>)}
          </div>
          <h3 style={{ marginTop: 16 }}>New restaurants by month</h3>
          <p className="muted">{d.new_restaurants_by_month.map((n) => `${n.month}: ${n.count}`).join(' · ') || 'None'}</p>
          <p className="muted">{d.notes.join(' ')}</p>
        </>
      )}
    </>
  )
}

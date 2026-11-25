import { Clock, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { Empty, ErrorState, PageHeader, Skeleton, useDocumentTitle, useToast } from '../../ui/kit'
import type { OrderRow } from '../account/pages'
import { useSite } from '../SiteContext'

type Ticket = OrderRow & {
  customer_notes: string; table_label?: string
  items: { product_name: string; variation_name: string; quantity: number; addons: { name: string; quantity: number }[]; instructions: string }[]
  allowed_transitions: { status: string; label: string }[]
}

const COLUMNS: { key: string; title: string; statuses: string[]; empty: string }[] = [
  { key: 'new', title: 'New', statuses: ['confirmed', 'received'], empty: 'No new orders.' },
  { key: 'prep', title: 'Preparing', statuses: ['preparing'], empty: 'Nothing on the stove.' },
  { key: 'ready', title: 'Ready to go', statuses: ['ready_for_pickup', 'out_for_delivery'], empty: 'Nothing waiting.' },
]
const REFRESH_MS = 10000
const age = (m: number) => (m < 90 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} days`)
const FULFIL: Record<string, string> = { dine_in: 'Dine in', pickup: 'Pickup', delivery: 'Delivery' }

/** Live kitchen board. Everything shown is read from the orders API; moves are validated by the server for the signed-in role. */
export default function Kitchen() {
  useDocumentTitle('Kitchen display')
  const toast = useToast()
  const { site } = useSite()
  const [branch, setBranch] = useState('')
  const [tickets, setTickets] = useState<Ticket[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [updated, setUpdated] = useState<Date | null>(null)

  const load = useCallback(async () => {
    try {
      const page = await api<Page<Ticket>>('/orders/manage/', { params: { active: 1, page_size: 60, branch, include: 'items' } }) // items come with the list: one request
      const wanted = page.results.filter((o) => COLUMNS.some((c) => c.statuses.includes(o.status)))
      setTickets(wanted.sort((a, b) => a.created_at.localeCompare(b.created_at)))
      setError('')
      setUpdated(new Date())
    } catch (e) { setError(e instanceof ApiError ? e.message : 'Could not load orders.') }
  }, [branch])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden) { setNow(Date.now()); void load() } }, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  async function move(t: Ticket, to: string, label: string) {
    setBusy(t.id)
    try { await api(`/orders/manage/${t.id}/transition/`, { body: { status: to, note: '' } }); toast(`${t.number}: ${label}`); await load() } catch (e) { toast(e instanceof ApiError ? e.message : 'Could not update the order.'); void load() } finally { setBusy(null) }
  }

  return (
    <>
      <PageHeader title="Kitchen display" subtitle={updated ? `Updated ${updated.toLocaleTimeString()} · refreshes every 10 seconds` : 'Loading orders…'}>
        {site.branches.length > 1 && <select className="input" style={{ width: 190 }} aria-label="Branch" value={branch} onChange={(e) => { setTickets(null); setBranch(e.target.value) }}><option value="">All my branches</option>{site.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
        <button className="btn sm secondary" onClick={() => void load()}><RefreshCw size={14} aria-hidden /> Refresh</button>
      </PageHeader>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {!tickets && !error ? <div className="kds"><Skeleton h={220} /><Skeleton h={220} /><Skeleton h={220} /></div> : tickets && (
        <div className="kds">
          {COLUMNS.map((col) => {
            const list = tickets.filter((t) => col.statuses.includes(t.status))
            return (
              <section className="kds-col" key={col.key} aria-label={col.title}>
                <h2>{col.title} <span className="badge">{list.length}</span></h2>
                {!list.length ? <Empty title={col.empty} /> : list.map((t) => {
                  const mins = Math.max(0, Math.floor((now - new Date(t.created_at).getTime()) / 60000))
                  const cls = mins >= 25 ? 'late' : mins >= 12 ? 'warn' : ''
                  const actions = t.allowed_transitions.filter((a) => a.status !== 'cancelled')
                  return (
                    <article className={`ticket ${cls}`} key={t.id}>
                      <header><b>{t.number}</b><span className="muted" style={{ display: 'flex', gap: 4, alignItems: 'center' }}><Clock size={14} aria-hidden /> {age(mins)}</span></header>
                      <div className="muted" style={{ fontSize: '.85rem' }}>{FULFIL[t.fulfilment] ?? t.fulfilment}{t.table_label ? ` · ${t.table_label}` : ''} · {t.branch_name} · {t.contact_name}</div>
                      <ul>{t.items.map((i, k) => (
                        <li key={k}><b>{i.quantity}×</b><span>{i.product_name}{i.variation_name ? ` (${i.variation_name})` : ''}
                          {i.addons.length > 0 && <small className="muted" style={{ display: 'block' }}>+ {i.addons.map((a) => `${a.quantity}× ${a.name}`).join(', ')}</small>}
                          {i.instructions && <small style={{ display: 'block', color: 'var(--warn)', fontWeight: 600 }}>Note: {i.instructions}</small>}</span></li>))}</ul>
                      {t.customer_notes && <p className="alert warn" style={{ padding: '6px 10px', margin: '0 0 10px' }}>{t.customer_notes}</p>}
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {actions.length ? actions.map((a) => <button key={a.status} className="btn" disabled={busy === t.id} onClick={() => move(t, a.status, a.label)}>{a.status === 'preparing' ? 'Start preparing' : a.status === 'received' ? 'Accept' : a.status === 'completed' ? 'Hand over' : `Mark ${a.label.toLowerCase()}`}</button>) : <span className="muted">No action for your role at this step.</span>}
                      </div>
                    </article>
                  )
                })}
              </section>
            )
          })}
        </div>
      )}
    </>
  )
}

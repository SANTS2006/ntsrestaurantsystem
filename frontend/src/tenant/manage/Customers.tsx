import { useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { Drawer, Empty, ErrorState, PageHeader, Pager, SearchInput, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { Avatar } from '../../ui/Shell'
import { useSite } from '../SiteContext'

type Row = { id: number; name: string; email: string; phone: string; avatar: string | null; orders: number; spent: string; last_order: string | null }
type Detail = Row & { joined: string | null; email_verified: boolean; addresses: { id: number; label: string; recipient: string; phone: string; address: string; notes: string }[]; recent_orders: { id: number; number: string; status: string; total: string; branch: string; created_at: string }[]; notes: { id: number; text: string; author: string | null; created_at: string }[] }

export default function Customers() {
  useDocumentTitle('Customers')
  const { money } = useSite()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number | null>(null)
  const list = useAsync(() => api<Page<Row>>('/customers/directory/', { params: { q, page } }), [q, page])
  return (
    <>
      <PageHeader title="Customers" subtitle="People who have ordered from you. Contact details are private: every profile you open is recorded." />
      <div className="toolbar"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Name, email or phone" label="Search customers" /></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title="No customers found" /> : (
          <table className="tbl"><thead><tr><th>Customer</th><th>Contact</th><th>Orders</th><th>Spent</th><th>Last order</th><th /></tr></thead><tbody>
            {list.data.results.map((c) => <tr key={c.id}><td><span className="person"><Avatar name={c.name} src={c.avatar} /><b>{c.name}</b></span></td><td>{c.email}<div className="muted" style={{ fontSize: '.8rem' }}>{c.phone}</div></td><td>{c.orders}</td><td>{money(c.spent)}</td><td>{c.last_order ? new Date(c.last_order).toLocaleDateString() : '–'}</td><td><button className="btn sm" onClick={() => setOpen(c.id)}>Open</button></td></tr>)}
          </tbody></table>)}
      </div>
      {list.data && <Pager page={page} hasPrev={!!list.data.previous} hasNext={!!list.data.next} onPage={setPage} total={list.data.count} />}
      {open !== null && <Profile id={open} onClose={() => setOpen(null)} />}
    </>
  )
}

function Profile({ id, onClose }: { id: number; onClose: () => void }) {
  const { money } = useSite()
  const toast = useToast()
  const d = useAsync(() => api<Detail>(`/customers/directory/${id}/`), [id])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  async function add(e: FormEvent) {
    e.preventDefault()
    if (note.trim().length < 2) return toast('Write a note first.')
    setBusy(true)
    try { await api(`/customers/directory/${id}/`, { body: { text: note.trim() } }); setNote(''); toast('Note added.'); d.reload() } catch (x) { toast(x instanceof ApiError ? x.message : 'Failed.') } finally { setBusy(false) }
  }
  const c = d.data
  return (
    <Drawer title={c?.name ?? 'Customer'} onClose={onClose}>
      {d.error && <ErrorState message={d.error} />}
      {!c ? !d.error && <Skeleton h={160} /> : (
        <>
          <div className="person-card">
            <Avatar name={c.name} src={c.avatar} className="xl" />
            <div>
              <b>{c.name}</b>
              <p><a href={`mailto:${c.email}`}>{c.email}</a>{!c.email_verified && <span className="badge"> email not verified</span>}</p>
              <p>{c.phone ? <a href={`tel:${c.phone}`}>{c.phone}</a> : <span className="muted">No phone number</span>}</p>
              <small className="muted">{c.joined ? `Customer since ${new Date(c.joined).toLocaleDateString()}` : ''}{c.last_order ? ` · Last order ${new Date(c.last_order).toLocaleDateString()}` : ''}</small>
            </div>
          </div>
          <div className="grid g3" style={{ marginBottom: 16 }}>
            <div className="card stat"><span className="muted">Orders</span><b>{c.orders}</b></div>
            <div className="card stat"><span className="muted">Spent</span><b>{money(c.spent)}</b></div>
          </div>
          <h3>Delivery addresses</h3>
          {!c.addresses?.length ? <p className="muted">No saved addresses.</p> : c.addresses.map((a) => <div className="list-row" key={a.id}><span><b>{a.label}</b> <span className="muted">{[a.recipient, a.address, a.phone, a.notes].filter(Boolean).join(' · ')}</span></span></div>)}
          <h3 style={{ marginTop: 16 }}>Staff notes</h3>
          <form onSubmit={add} style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input className="input" aria-label="New note" placeholder="e.g. allergic to peanuts, prefers window seat" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn" disabled={busy}>Add</button>
          </form>
          {!c.notes.length ? <p className="muted">No notes yet. Notes are visible to staff only and cannot be edited or deleted.</p> : <ul className="feed">{c.notes.map((n) => <li key={n.id}><span className="dot" /><span>{n.text}<br /><small className="muted">{n.author ?? 'Staff'} · {new Date(n.created_at).toLocaleString()}</small></span></li>)}</ul>}
          <h3 style={{ marginTop: 16 }}>Recent orders</h3>
          {!c.recent_orders.length ? <p className="muted">None in your branches.</p> : c.recent_orders.map((o) => <div className="list-row" key={o.id}><span><b>{o.number}</b> <span className="muted">{o.branch} · {new Date(o.created_at).toLocaleDateString()}</span></span><span><b>{money(o.total)}</b> <span className="badge">{o.status.replace(/_/g, ' ')}</span></span></div>)}
        </>
      )}
    </Drawer>
  )
}

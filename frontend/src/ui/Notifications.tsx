import { ArrowLeft, CheckCheck, ChevronRight, ExternalLink, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useNotifications, type AppNotification } from '../lib/live'
import { useConfirm } from './dialogs'
import { Empty, ErrorState, PageHeader, Pager, Skeleton, useAsync, useDocumentTitle, useToast } from './kit'
import { ago, kindIcon, kindLabel, notificationsBase } from './notificationMeta'

type Listing = { unread: number; count: number; page: number; has_next: boolean; items: AppNotification[] }
type Detail = AppNotification & { read_at: string | null; details: { heading: string; fields: { label: string; value: string }[]; items: string[] } | null }

/** Every notification of the signed-in person, newest first, with filters and paging. */
export function NotificationsPage() {
  useDocumentTitle('Notifications')
  const { me } = useAuth()
  const base = notificationsBase(me?.role)
  const toast = useToast()
  const confirm = useConfirm()
  const { markRead, clearRead, pull } = useNotifications()
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const [page, setPage] = useState(1)
  const list = useAsync(() => api<Listing>('/notifications/', { params: { page, unread: filter === 'unread' ? 1 : undefined } }), [page, filter])
  const d = list.data

  async function readAll() { await markRead(); list.reload(); toast('All notifications marked as read.') }
  async function clear() {
    if (!(await confirm({ title: 'Delete read notifications?', message: 'Unread notifications are kept.', confirmLabel: 'Delete', danger: true }))) return
    await clearRead(); await pull(); setPage(1); list.reload()
  }

  return (
    <>
      <PageHeader title="Notifications" subtitle={d ? `${d.unread} unread` : 'Everything that happened that concerns you'}>
        <button className="btn sm secondary" disabled={!d?.unread} onClick={() => void readAll()}><CheckCheck size={14} aria-hidden /> Mark all read</button>
        <button className="btn sm secondary" onClick={() => void clear()}><Trash2 size={14} aria-hidden /> Delete read</button>
      </PageHeader>
      <div className="chips" role="group" aria-label="Filter" style={{ marginBottom: 14 }}>
        {(['all', 'unread'] as const).map((f) => <button key={f} className="chip" aria-pressed={filter === f} onClick={() => { setFilter(f); setPage(1) }}>{f === 'all' ? 'All' : 'Unread'}</button>)}
      </div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {list.loading && !d ? <Skeleton h={180} /> : d && !d.items.length ? <Empty title={filter === 'unread' ? 'Nothing unread' : 'No notifications yet'}>New orders, payments and other activity appear here.</Empty> : d && (
        <ul className="notif-list">
          {d.items.map((n) => (
            <li key={n.id}>
              <Link to={`${base}/${n.id}`} className={`notif-card ${n.read ? '' : 'unread'} ${n.kind === 'order_ready' ? 'ready' : ''}`}>
                <span className="ico">{kindIcon(n.kind)}</span>
                <span className="text"><b>{n.title}</b>{n.body && <span>{n.body}</span>}<small>{kindLabel(n.kind)} · {ago(n.created_at)}</small></span>
                {!n.read && <span className="badge info">New</span>}
                <ChevronRight size={18} aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {d && <Pager page={page} hasPrev={page > 1} hasNext={d.has_next} onPage={setPage} total={d.count} />}
    </>
  )
}

/** One notification in full, with the order, reservation or request it is about. */
export function NotificationDetailPage() {
  const { nid } = useParams()
  const { me } = useAuth()
  const base = notificationsBase(me?.role)
  const navigate = useNavigate()
  const { pull } = useNotifications()
  const d = useAsync(() => api<Detail>(`/notifications/${nid}/`), [nid])
  const n = d.data
  useDocumentTitle(n ? n.title : 'Notification')
  useEffect(() => { if (n) void pull() }, [n?.id]) // eslint-disable-line react-hooks/exhaustive-deps -- opening marks it read: update the bell

  return (
    <>
      <p><Link to={base}><ArrowLeft size={14} aria-hidden /> All notifications</Link></p>
      {d.error && <ErrorState message={d.error} onRetry={d.reload} />}
      {d.loading && !n ? <Skeleton h={220} /> : n && (
        <article className="card notif-detail">
          <header>
            <span className={`ico ${n.kind === 'order_ready' ? 'ready' : ''}`}>{kindIcon(n.kind, 26)}</span>
            <div><h1>{n.title}</h1><p className="muted">{kindLabel(n.kind)} · {new Date(n.created_at).toLocaleString()}</p></div>
          </header>
          {n.body && <p className="lead">{n.body}</p>}
          {n.details ? (
            <>
              <h2>{n.details.heading}</h2>
              <dl>{n.details.fields.map((f) => <div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl>
              {n.details.items.length > 0 && <><h3>Items</h3><ul>{n.details.items.map((i, k) => <li key={k}>{i}</li>)}</ul></>}
            </>
          ) : <p className="muted">There are no further details for this notification.</p>}
          <p className="muted" style={{ fontSize: '.85rem' }}>{n.read_at ? `Read ${new Date(n.read_at).toLocaleString()}` : ''}</p>
          {n.link && <button className="btn" onClick={() => navigate(n.link)}><ExternalLink size={16} aria-hidden /> Open related page</button>}
        </article>
      )}
    </>
  )
}

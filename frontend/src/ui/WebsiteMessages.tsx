import { Mail, MessageCircle, Phone, Send, StickyNote } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, api, type Page } from '../lib/api'
import { Drawer, Empty, ErrorState, PageHeader, Pager, SearchInput, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from './kit'
import { useConfirm } from './dialogs'
import { Avatar } from './Shell'

type Status = 'new' | 'in_progress' | 'replied' | 'closed' | 'spam'
type Row = { id: number; reference: string; name: string; email: string; phone: string; business_name: string; topic_label: string; subject: string; preview: string; status: Status; status_label: string; branch: string | null; created_at: string }
type Detail = Row & {
  message: string; city: string; preferred_contact: string; preferred_contact_label: string; page: string; consented_at: string; has_account: boolean
  ip_address: string | null; user_agent: string; handled_by: string | null; updated_at: string
  activity: { id: number; kind: 'reply' | 'note' | 'status'; text: string; author: string | null; created_at: string }[]
}
type Listing = Page<Row> & { counts: Record<Status, number> }

const STATUSES: [Status, string][] = [['new', 'New'], ['in_progress', 'In progress'], ['replied', 'Replied'], ['closed', 'Closed'], ['spam', 'Spam']]
const TONE: Record<Status, string> = { new: 'info', in_progress: 'warn', replied: 'active', closed: '', spam: 'suspended' }
const when = (iso: string) => new Date(iso).toLocaleString()

/** "Website contact": everything visitors sent through the contact form, and what the team did about each message. */
export default function WebsiteMessages({ subtitle }: { subtitle: string }) {
  useDocumentTitle('Website contact')
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState<Status | ''>('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const open = Number(params.get('open')) || null
  const show = (id: number | null) => setParams((p) => { if (id) p.set('open', String(id)); else p.delete('open'); return p }, { replace: true })
  const list = useAsync(() => api<Listing>('/website/messages/', { params: { status: filter, q, page } }), [filter, q, page])
  const counts = list.data?.counts

  return (
    <>
      <PageHeader title="Website contact" subtitle={subtitle} />
      <div className="chips" role="group" aria-label="Filter by status" style={{ marginBottom: 12 }}>
        <button className="chip" aria-pressed={filter === ''} onClick={() => { setFilter(''); setPage(1) }}>All</button>
        {STATUSES.map(([id, label]) => <button key={id} className="chip" aria-pressed={filter === id} onClick={() => { setFilter(id); setPage(1) }}>{label}{counts?.[id] ? <span className="chip-count">{counts[id]}</span> : null}</button>)}
      </div>
      <div className="toolbar"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Name, email, phone or words" label="Search messages" /></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={160} /> : !list.data?.results.length ? (
          <Empty title={q || filter ? 'No messages match' : 'No messages yet'}>Messages sent through the website’s contact form appear here.</Empty>
        ) : (
          <table className="tbl"><thead><tr><th>From</th><th>Message</th><th>About</th><th>Status</th><th>Received</th><th /></tr></thead><tbody>
            {list.data.results.map((m) => (
              <tr key={m.id} className={m.status === 'new' ? 'row-new' : ''}>
                <td><span className="person"><Avatar name={m.name} /><span><b>{m.name}</b><small className="muted">{m.email}</small>{m.phone && <small className="muted">{m.phone}</small>}</span></span></td>
                <td className="msg-cell"><b>{m.subject}</b><div className="muted clamp">{m.preview}</div></td>
                <td>{m.topic_label}{m.branch && <div className="muted">{m.branch}</div>}{m.business_name && <div className="muted">{m.business_name}</div>}</td>
                <td><span className={`badge ${TONE[m.status]}`}>{m.status_label}</span></td>
                <td>{when(m.created_at)}<div className="muted">{m.reference}</div></td>
                <td><button className="btn sm" onClick={() => show(m.id)}>Open</button></td>
              </tr>
            ))}
          </tbody></table>
        )}
      </div>
      {list.data && <Pager page={page} hasPrev={!!list.data.previous} hasNext={!!list.data.next} onPage={setPage} total={list.data.count} />}
      {open && <MessageDrawer key={open} id={open} onClose={() => show(null)} onChanged={list.reload} />}
    </>
  )
}

function MessageDrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const toast = useToast()
  const confirm = useConfirm()
  const loaded = useAsync(() => api<Detail>(`/website/messages/${id}/`), [id])
  const [m, setM] = useState<Detail | null>(null)
  const [reply, setReply] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')
  useEffect(() => { if (loaded.data) setM(loaded.data) }, [loaded.data])

  async function act(body: { action: 'reply' | 'note' | 'status'; text?: string; status?: Status }, done: string) {
    setBusy(body.action)
    try {
      setM(await api<Detail>(`/website/messages/${id}/`, { body }))
      toast(done)
      if (body.action === 'reply') setReply('')
      if (body.action === 'note') setNote('')
      onChanged()
    } catch (e) {
      toast(e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'That did not work. Please try again.')
    } finally {
      setBusy('')
    }
  }
  async function sendReply(e: FormEvent) {
    e.preventDefault()
    if (!m) return
    if (reply.trim().length < 2) return toast('Write your reply first.')
    if (await confirm({ title: `Email this reply to ${m.name}?`, message: `It is sent to ${m.email}.`, confirmLabel: 'Send reply' })) await act({ action: 'reply', text: reply.trim() }, 'Reply sent by email.')
  }
  async function setStatus(status: Status) {
    if (status === 'spam' && !(await confirm({ title: 'Mark as spam?', message: 'It is hidden from the main list. Nothing is deleted.', confirmLabel: 'Mark as spam', danger: true }))) return
    await act({ action: 'status', status }, 'Status updated.')
  }
  const digits = m?.phone.replace(/\D/g, '') ?? ''

  return (
    <Drawer title={m ? `${m.reference}: ${m.subject}` : 'Message'} onClose={onClose}>
      {loaded.error && <ErrorState message={loaded.error} />}
      {!m ? !loaded.error && <Skeleton h={220} /> : (
        <>
          <div className="person-card">
            <Avatar name={m.name} className="xl" />
            <div>
              <b>{m.name}</b>
              <p><a href={`mailto:${m.email}?subject=${encodeURIComponent(`Re: ${m.subject} (${m.reference})`)}`}><Mail size={14} aria-hidden /> {m.email}</a></p>
              {m.phone && <p><a href={`tel:${m.phone}`}><Phone size={14} aria-hidden /> {m.phone}</a>{digits.length >= 8 && <> · <a href={`https://wa.me/${digits}`} target="_blank" rel="noopener noreferrer"><MessageCircle size={14} aria-hidden /> WhatsApp</a></>}</p>}
              <small className="muted">Prefers: {m.preferred_contact_label}</small>
            </div>
          </div>
          <dl className="facts">
            <div><dt>Status</dt><dd><select className="input" aria-label="Status" value={m.status} disabled={!!busy} onChange={(e) => void setStatus(e.target.value as Status)}>{STATUSES.map(([s, l]) => <option key={s} value={s}>{l}</option>)}</select></dd></div>
            <div><dt>About</dt><dd>{m.topic_label}</dd></div>
            {m.branch && <div><dt>Location chosen</dt><dd>{m.branch}</dd></div>}
            {m.business_name && <div><dt>Their restaurant</dt><dd>{m.business_name}</dd></div>}
            {m.city && <div><dt>City</dt><dd>{m.city}</dd></div>}
            <div><dt>Received</dt><dd>{when(m.created_at)}</dd></div>
            <div><dt>Sent from page</dt><dd>{m.page || '–'}</dd></div>
            <div><dt>Has an account</dt><dd>{m.has_account ? 'Yes' : 'No'}</dd></div>
            <div><dt>Agreed to be contacted</dt><dd>{when(m.consented_at)}</dd></div>
            {m.handled_by && <div><dt>Last handled by</dt><dd>{m.handled_by}</dd></div>}
            {m.ip_address && <div><dt>Network address</dt><dd>{m.ip_address}</dd></div>}
            {m.user_agent && <div><dt>Browser</dt><dd className="clamp" title={m.user_agent}>{m.user_agent}</dd></div>}
          </dl>
          <h3>Message</h3>
          <p className="quote pre">{m.message}</p>

          <h3>Reply by email</h3>
          <form onSubmit={sendReply}>
            <textarea className="input" rows={4} aria-label="Your reply" placeholder="Enter your reply" maxLength={4000} value={reply} onChange={(e) => setReply(e.target.value)} />
            <button className="btn" style={{ marginTop: 8 }} disabled={!!busy || m.status === 'spam'}>{busy === 'reply' ? <Spinner /> : <><Send size={15} aria-hidden /> Send reply</>}</button>
          </form>

          <h3 style={{ marginTop: 18 }}>Internal note</h3>
          <form onSubmit={(e) => { e.preventDefault(); if (note.trim().length < 2) return toast('Write a note first.'); void act({ action: 'note', text: note.trim() }, 'Note added.') }} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input className="input" style={{ flex: '1 1 200px' }} aria-label="Internal note" placeholder="Enter a note for the team (not sent)" maxLength={4000} value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn secondary" disabled={!!busy}><StickyNote size={15} aria-hidden /> Add note</button>
          </form>

          <h3 style={{ marginTop: 18 }}>History</h3>
          {!m.activity.length ? <p className="muted">Nothing has been done with this message yet.</p> : (
            <ul className="feed">{m.activity.map((a) => <li key={a.id}><span className="dot" /><span><b>{a.kind === 'reply' ? 'Reply sent' : a.kind === 'note' ? 'Note' : 'Status'}:</b> <span className="pre">{a.text}</span><br /><small className="muted">{a.author ?? 'Team'} · {when(a.created_at)}</small></span></li>)}</ul>
          )}
        </>
      )}
    </Drawer>
  )
}

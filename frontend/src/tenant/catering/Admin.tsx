import { useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'
import { useConfirm, usePrompt } from '../../ui/dialogs'

type Row = { id: number; reference: string; status: string; status_label: string; customer_name: string; event_type_label: string; event_date: string; guests: number; branch: { id: number; name: string } | null; assigned_to: string | null; created_at: string }
type Quote = { id: number; version: number; status: string; items: { description: string; quantity: string; unit_price: string; line_total: string }[]; subtotal: string; discount: string; tax_total: string; total: string; valid_until: string; terms: string; sent_at: string | null; accepted_via: string; response_note: string }
type Detail = Row & {
  customer_email: string; customer_phone: string; event_location: string; services: string[]; food_preferences: string; budget: string | null; requirements: string; cancel_reason: string
  allowed_statuses: { status: string; label: string }[]
  history: { status: string; label: string; note: string; actor: string | null; created_at: string }[]
  notes: { id: number; kind: string; text: string; author: string | null; created_at: string }[]
  quotations: Quote[]
  payments: { id: number; kind: string; amount: string; method: string; reference: string; received_on: string; note: string; recorded_by: string | null }[]
  balance: { agreed_total: string; paid: string; balance: string }
}
type Member = { user_id: number; full_name: string; email: string }
const STATUSES = ['new', 'under_review', 'quotation_sent', 'accepted', 'in_progress', 'completed', 'rejected', 'cancelled']
const LABEL: Record<string, string> = { new: 'New', under_review: 'Under review', quotation_sent: 'Quotation sent', accepted: 'Accepted', in_progress: 'In progress', completed: 'Completed', rejected: 'Rejected', cancelled: 'Cancelled' }
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const money2 = /^\d+(\.\d{1,2})?$/

export default function CateringAdmin() {
  useDocumentTitle('Catering')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number | null>(null)
  const list = useAsync(() => api<Page<Row> & { counts: Record<string, number> }>('/catering/requests/', { params: { status, q, page } }), [status, q, page])
  return (
    <>
      <h1 className="page-title">Catering requests</h1>
      <div className="toolbar" role="group" aria-label="Filter by status">
        <button className={`btn sm ${status ? 'secondary' : ''}`} onClick={() => { setStatus(''); setPage(1) }}>All</button>
        {STATUSES.map((s) => <button key={s} className={`btn sm ${status === s ? '' : 'secondary'}`} onClick={() => { setStatus(s); setPage(1) }}>{LABEL[s]}{list.data ? ` (${list.data.counts[s] ?? 0})` : ''}</button>)}
      </div>
      <div className="toolbar"><input className="input" style={{ maxWidth: 280 }} type="search" placeholder="Reference, name or email" aria-label="Search requests" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /><button className="btn sm secondary" onClick={list.reload}>Refresh</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title="No catering requests" /> : (
          <table className="tbl"><thead><tr><th>Reference</th><th>Customer</th><th>Event</th><th>Date</th><th>Guests</th><th>Branch</th><th>Assigned</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((r) => <tr key={r.id}><td><b>{r.reference}</b></td><td>{r.customer_name}</td><td>{r.event_type_label}</td><td>{new Date(r.event_date).toLocaleDateString()}</td><td>{r.guests}</td><td>{r.branch?.name ?? <span className="badge suspended">unallocated</span>}</td><td>{r.assigned_to ?? '–'}</td>
              <td><span className={`badge ${r.status === 'accepted' || r.status === 'completed' ? 'active' : r.status === 'rejected' || r.status === 'cancelled' ? 'suspended' : ''}`}>{r.status_label}</span></td><td><button className="btn sm" onClick={() => setOpen(r.id)}>Open</button></td></tr>)}
          </tbody></table>)}
      </div>
      {list.data && (list.data.next || list.data.previous) && <div className="toolbar" style={{ marginTop: 12 }}><button className="btn sm secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button><span className="muted">Page {page}</span><button className="btn sm secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button></div>}
      {open !== null && <DetailModal id={open} onClose={() => setOpen(null)} onChanged={list.reload} />}
    </>
  )
}

function DetailModal({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const prompt = usePrompt()
  const { money } = useSite()
  const { me } = useAuth()
  const toast = useToast()
  const isAdmin = me?.role === 'restaurant_admin' || me?.role === 'platform_admin'
  const d = useAsync(() => api<Detail>(`/catering/requests/${id}/`), [id])
  const staff = useAsync(() => api<Page<Member>>('/staff/members/', { params: { active: 1, page_size: 100 } }), [])
  const branches = useAsync(() => (isAdmin ? api<Page<{ id: number; name: string }>>('/restaurants/branches/', { params: { page_size: 100 } }) : Promise.resolve(null)), [isAdmin])
  const [note, setNote] = useState('')
  const [mail, setMail] = useState({ subject: '', message: '' })
  const [busy, setBusy] = useState(false)
  const r = d.data

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true)
    try { await fn(); toast(ok); d.reload(); onChanged() } catch (e) { toast(msg(e)) } finally { setBusy(false) }
  }
  const post = (path: string, body: unknown = {}, headers?: Record<string, string>) => api(`/catering/requests/${id}/${path}/`, { body, headers })
  async function move(to: string, label: string) {
    let reason = ''
    if (to === 'rejected' || to === 'cancelled') { reason = (await prompt({ title: `Mark this ${label.toLowerCase()}`, message: 'The customer will see the reason.', label: 'Reason', required: true, multiline: true, danger: true, confirmLabel: 'Continue' })) ?? ''; if (!reason) return }
    void run(() => post('status', { status: to, note: reason }), `Marked ${label.toLowerCase()}.`)
  }
  if (!r) return <Modal title="Catering request" onClose={onClose}>{d.error ? <ErrorState message={d.error} /> : <Skeleton h={200} />}</Modal>
  const accepted = r.quotations.find((q) => q.status === 'accepted')
  return (
    <Modal title={`${r.reference}: ${r.event_type_label}`} onClose={onClose}>
      <p><span className="badge">{r.status_label}</span> {r.branch ? r.branch.name : <span className="badge suspended">unallocated</span>}</p>
      <div className="card" style={{ marginBottom: 12 }}>
        <b>{r.customer_name}</b> · <a href={`mailto:${r.customer_email}`}>{r.customer_email}</a> · <a href={`tel:${r.customer_phone}`}>{r.customer_phone}</a>
        <p style={{ margin: '6px 0' }}>{new Date(r.event_date).toLocaleDateString()} · {r.guests} guests · {r.event_location}</p>
        {r.services.length > 0 && <p className="muted" style={{ margin: 0 }}>Services: {r.services.join(', ')}</p>}
        {r.budget && <p className="muted" style={{ margin: 0 }}>Budget: {money(r.budget)}</p>}
        {r.food_preferences && <p style={{ margin: '6px 0 0' }}>Food: {r.food_preferences}</p>}
        {r.requirements && <p style={{ margin: '6px 0 0' }}>Notes: {r.requirements}</p>}
        {r.cancel_reason && <p className="err">Reason: {r.cancel_reason}</p>}
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
        {r.allowed_statuses.map((s) => <button key={s.status} className={`btn sm ${s.status === 'rejected' || s.status === 'cancelled' ? 'danger' : ''}`} disabled={busy} onClick={() => move(s.status, s.label)}>Mark {s.label.toLowerCase()}</button>)}
      </div>
      <div className="grid g2">
        <Field label="Assigned to">{(p) => <select {...p} className="input" value={staff.data?.results.find((m) => m.full_name === r.assigned_to || m.email === r.assigned_to)?.user_id ?? ''} onChange={(e) => run(() => post('assign', { user_id: e.target.value ? Number(e.target.value) : null }), 'Assignment updated.')}><option value="">Unassigned</option>{(staff.data?.results ?? []).map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name || m.email}</option>)}</select>}</Field>
        {isAdmin && <Field label="Branch">{(p) => <select {...p} className="input" value={r.branch?.id ?? ''} onChange={(e) => run(() => post('set-branch', { branch_id: e.target.value ? Number(e.target.value) : null }), 'Branch updated.')}><option value="">Unallocated</option>{(branches.data?.results ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>}
      </div>

      <Quotations r={r} busy={busy} run={run} post={post} />

      {(r.status === 'accepted' || r.status === 'in_progress' || r.status === 'completed' || r.status === 'cancelled') && <Payments r={r} accepted={!!accepted} busy={busy} onSaved={() => { d.reload(); onChanged() }} id={id} />}

      <h3 style={{ marginTop: 16 }}>Contact the customer</h3>
      <form noValidate onSubmit={(e: FormEvent) => { e.preventDefault(); if (!mail.subject.trim() || !mail.message.trim()) return toast('Enter a subject and a message.'); void run(async () => { await post('contact', mail); setMail({ subject: '', message: '' }) }, 'Email sent.') }}>
        <input className="input" placeholder="Subject" aria-label="Email subject" value={mail.subject} onChange={(e) => setMail({ ...mail, subject: e.target.value })} style={{ marginBottom: 6 }} />
        <textarea className="input" rows={3} placeholder="Message (sent by email and logged below)" aria-label="Email message" value={mail.message} onChange={(e) => setMail({ ...mail, message: e.target.value })} />
        <button className="btn sm" style={{ marginTop: 6 }} disabled={busy}>Send email</button>
      </form>

      <h3 style={{ marginTop: 16 }}>Internal notes (staff only)</h3>
      <form noValidate onSubmit={(e: FormEvent) => { e.preventDefault(); if (!note.trim()) return; void run(async () => { await post('notes', { text: note }); setNote('') }, 'Note added.') }} style={{ display: 'flex', gap: 6 }}>
        <input className="input" placeholder="Add a private note" aria-label="Internal note" value={note} onChange={(e) => setNote(e.target.value)} /><button className="btn sm" disabled={busy}>Add</button>
      </form>
      {r.notes.map((n) => <p key={n.id} style={{ margin: '8px 0' }}><span className="muted">{new Date(n.created_at).toLocaleString()} · {n.author ?? 'system'}{n.kind === 'email' ? ' · email' : ''}</span><br /><span style={{ whiteSpace: 'pre-line' }}>{n.text}</span></p>)}

      <h3 style={{ marginTop: 16 }}>History</h3>
      <ul style={{ paddingLeft: 18 }}>{r.history.map((h, i) => <li key={i}><b>{h.label}</b> <span className="muted">{new Date(h.created_at).toLocaleString()}{h.actor ? ` · ${h.actor}` : ''}{h.note ? ` · ${h.note}` : ''}</span></li>)}</ul>
    </Modal>
  )
}

function Quotations({ r, busy, run, post }: { r: Detail; busy: boolean; run: (fn: () => Promise<unknown>, ok: string) => Promise<void>; post: (path: string, body?: unknown) => Promise<unknown> }) {
  const prompt = usePrompt()
  const confirm = useConfirm()
  const { money } = useSite()
  const [building, setBuilding] = useState(false)
  const [items, setItems] = useState([{ description: '', quantity: '1', unit_price: '' }])
  const [discount, setDiscount] = useState('0')
  const [valid, setValid] = useState(new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10))
  const [terms, setTerms] = useState('')
  const [error, setError] = useState('')
  const canQuote = ['new', 'under_review', 'quotation_sent'].includes(r.status)

  function save(e: FormEvent) {
    e.preventDefault(); setError('')
    if (items.some((i) => !i.description.trim() || !/^\d+(\.\d{1,2})?$/.test(i.quantity) || Number(i.quantity) <= 0 || !money2.test(i.unit_price))) return setError('Each line needs a description, a quantity and a price (e.g. 25.00).')
    if (!money2.test(discount)) return setError('Enter the discount as a number, e.g. 0 or 100.00.')
    void run(async () => { await post('quotations', { items, discount, valid_until: valid, terms }); setBuilding(false); setItems([{ description: '', quantity: '1', unit_price: '' }]) }, 'Quotation saved as a draft.')
  }
  return (
    <>
      <h3 style={{ marginTop: 16 }}>Quotations</h3>
      {r.quotations.length === 0 && <p className="muted">No quotations yet.</p>}
      {r.quotations.map((q) => (
        <div key={q.id} className="card" style={{ marginBottom: 8, padding: 12 }}>
          <b>Version {q.version}</b> <span className={`badge ${q.status === 'accepted' ? 'active' : q.status === 'declined' ? 'suspended' : ''}`}>{q.status}</span> · <b>{money(q.total)}</b> · valid until {new Date(q.valid_until).toLocaleDateString()}
          {q.accepted_via && <span className="muted"> · accepted {q.accepted_via === 'customer_link' ? 'by the customer' : 'and recorded by staff'}</span>}
          {q.response_note && <div className="muted">“{q.response_note}”</div>}
          <div className="muted" style={{ fontSize: '.9rem' }}>{q.items.map((i) => `${i.quantity} × ${i.description}`).join(' · ')}</div>
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            {q.status === 'draft' && <button className="btn sm" disabled={busy} onClick={async () => (await confirm({ title: 'Email this quotation?', message: 'The customer will receive it now.', confirmLabel: 'Send' })) && run(() => post(`quotations/${q.id}/send`), 'Quotation emailed.')}>Send to customer</button>}
            {q.status === 'sent' && <button className="btn sm secondary" disabled={busy} onClick={async () => { const n = (await prompt({ title: 'Record acceptance', label: 'How and when did the customer accept?', required: true, multiline: true })) ?? ''; if (n) void run(() => post(`quotations/${q.id}/accept`, { note: n }), 'Acceptance recorded.') }}>Record acceptance</button>}
          </div>
        </div>))}
      {canQuote && !building && <button className="btn sm secondary" onClick={() => setBuilding(true)}>New quotation</button>}
      {building && (
        <form className="card" onSubmit={save} noValidate>
          {error && <div className="alert error" role="alert">{error}</div>}
          {items.map((it, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
              <input className="input" style={{ flex: 1, minWidth: 160 }} placeholder="Description, e.g. Buffet per guest" aria-label="Description" value={it.description} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} />
              <input className="input" style={{ width: 80 }} placeholder="Qty" aria-label="Quantity" value={it.quantity} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
              <input className="input" style={{ width: 110 }} placeholder="Unit price" aria-label="Unit price" value={it.unit_price} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, unit_price: e.target.value } : x)))} />
              {items.length > 1 && <button type="button" className="btn sm secondary" aria-label="Remove line" onClick={() => setItems(items.filter((_, j) => j !== i))}>✕</button>}
            </div>))}
          <button type="button" className="btn sm secondary" onClick={() => setItems([...items, { description: '', quantity: '1', unit_price: '' }])}>Add line</button>
          <div className="grid g2" style={{ marginTop: 10 }}>
            <Field label="Discount">{(p) => <input {...p} className="input" value={discount} onChange={(e) => setDiscount(e.target.value)} />}</Field>
            <Field label="Valid until">{(p) => <input {...p} className="input" type="date" value={valid} onChange={(e) => setValid(e.target.value)} />}</Field>
          </div>
          <Field label="Terms (optional)">{(p) => <textarea {...p} className="input" rows={3} placeholder="Deposit, cancellation terms, what is included" value={terms} onChange={(e) => setTerms(e.target.value)} />}</Field>
          <p className="hint">Totals and tax are calculated by the system when you save.</p>
          <div style={{ display: 'flex', gap: 6 }}><button className="btn sm" disabled={busy}>Save draft</button><button type="button" className="btn sm secondary" onClick={() => setBuilding(false)}>Cancel</button></div>
        </form>)}
    </>
  )
}

function Payments({ r, accepted, busy, onSaved, id }: { r: Detail; accepted: boolean; busy: boolean; onSaved: () => void; id: number }) {
  const { money } = useSite()
  const toast = useToast()
  const [f, setF] = useState({ kind: 'deposit', amount: '', method: 'bank_transfer', reference: '', received_on: new Date().toISOString().slice(0, 10), note: '' })
  const [b, setB] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!money2.test(f.amount) || Number(f.amount) <= 0) return toast('Enter the amount, e.g. 500.00.')
    setB(true)
    try { await api(`/catering/requests/${id}/payments/`, { body: f, headers: { 'Idempotency-Key': crypto.randomUUID() } }); toast('Payment recorded.'); setF({ ...f, amount: '', reference: '', note: '' }); onSaved() } catch (err) { toast(msg(err)) } finally { setB(false) }
  }
  return (
    <>
      <h3 style={{ marginTop: 16 }}>Payments</h3>
      <p>Agreed {money(r.balance.agreed_total)} · Paid {money(r.balance.paid)} · <b>Balance {money(r.balance.balance)}</b></p>
      {r.payments.map((p) => <p key={p.id} className="muted" style={{ margin: '2px 0' }}>{new Date(p.received_on).toLocaleDateString()} · {p.kind} · {p.kind === 'refund' ? '−' : ''}{money(p.amount)} · {p.method}{p.reference ? ` · ${p.reference}` : ''}{p.recorded_by ? ` · by ${p.recorded_by}` : ''}</p>)}
      {accepted && (
        <form noValidate onSubmit={submit} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          <select className="input" style={{ width: 120 }} aria-label="Payment type" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="deposit">Deposit</option><option value="payment">Payment</option><option value="refund">Refund</option></select>
          <input className="input" style={{ width: 110 }} placeholder="Amount" aria-label="Amount" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} />
          <select className="input" style={{ width: 150 }} aria-label="Method" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}><option value="bank_transfer">Bank transfer</option><option value="cash">Cash</option><option value="mobile_money">Mobile money</option><option value="other">Other</option></select>
          <input className="input" style={{ width: 150 }} type="date" aria-label="Date received" value={f.received_on} onChange={(e) => setF({ ...f, received_on: e.target.value })} />
          <input className="input" style={{ flex: 1, minWidth: 120 }} placeholder="Reference (optional)" aria-label="Reference" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} />
          <button className="btn sm" disabled={busy || b}>{b ? <Spinner /> : 'Record'}</button>
        </form>)}
    </>
  )
}

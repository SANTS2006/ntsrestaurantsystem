import { Download, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ApiError, api, downloadFile, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Drawer, Empty, ErrorState, Field, Modal, PageHeader, Pager, SearchInput, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'

type Cat = { id: number; name: string; is_active: boolean }
type Exp = { id: number; category: string; branch: string | null; description: string; amount: string; expense_date: string; method: string; reference: string; status: string; void_reason: string; supplier: string | null; purchase_order: string | null; created_by: string | null }
type Inv = { id: number; number: string; status: string; overdue: boolean; customer_name: string; customer_email: string; issue_date: string | null; due_date: string | null; subtotal: string; tax_rate_percent: string; tax_total: string; total: string; amount_paid: string; balance: string; void_reason: string
  customer_address?: string; notes?: string; lines?: { description: string; quantity: string; unit_price: string; line_total: string }[]; payments?: { amount: string; method: string; reference: string; received_on: string }[] }
type PO = { id: number; number: string; supplier: string }

const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const METHODS = [['cash', 'Cash'], ['bank_transfer', 'Bank transfer'], ['mobile_money', 'Mobile money'], ['other', 'Other']]
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const INV_BADGE: Record<string, string> = { draft: '', issued: 'info', paid: 'ok', void: 'bad' }

export default function Finance() {
  useDocumentTitle('Expenses and invoices')
  const [tab, setTab] = useState<'expenses' | 'invoices'>('expenses')
  return (
    <>
      <PageHeader title="Expenses and invoices" subtitle="Record what the business spends and bill customers. Recorded money is never edited or deleted: mistakes are voided with a reason.">
        <div className="seg" role="tablist" aria-label="Sections">{([['expenses', 'Expenses'], ['invoices', 'Invoices']] as const).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}</div>
      </PageHeader>
      {tab === 'expenses' ? <Expenses /> : <Invoices />}
    </>
  )
}

// ----------------------------------------------------------------------------------------------- expenses
function Expenses() {
  const { money } = useSite()
  const { me } = useAuth()
  const toast = useToast()
  const admin = me?.role === 'restaurant_admin' || me?.role === 'platform_admin'
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [add, setAdd] = useState(false)
  const list = useAsync(() => api<Page<Exp> & { total_recorded: string }>('/finance/expenses/', { params: { q, page } }), [q, page])
  async function voidIt(e: Exp) {
    const reason = (prompt(`Reason for voiding “${e.description}”:`) ?? '').trim()
    if (!reason) return
    try { await api(`/finance/expenses/${e.id}/void/`, { body: { reason } }); toast('Expense voided.'); list.reload() } catch (x) { toast(msg(x)) }
  }
  return (
    <>
      <div className="toolbar"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Search description" label="Search expenses" />
        <span style={{ flex: 1 }} />{list.data && <span className="muted">Recorded total: <b>{money(list.data.total_recorded)}</b></span>}<button className="btn" onClick={() => setAdd(true)}><Plus size={16} aria-hidden /> Record expense</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title="No expenses recorded">Record rent, utilities, supplies and other costs so reports show where the money goes.</Empty> : (
          <table className="tbl"><thead><tr><th>Date</th><th>Category</th><th>Description</th><th>Branch</th><th>Paid by</th><th>Amount</th><th /></tr></thead><tbody>
            {list.data.results.map((e) => <tr key={e.id} style={{ opacity: e.status === 'void' ? 0.55 : 1 }}><td>{e.expense_date}</td><td>{e.category}</td><td>{e.description}{e.purchase_order && <span className="badge" style={{ marginLeft: 6 }}>{e.purchase_order}</span>}{e.status === 'void' && <div className="err" style={{ fontSize: '.8rem' }}>Void: {e.void_reason}</div>}</td><td>{e.branch ?? 'Restaurant-wide'}</td><td>{e.method.replace('_', ' ')}{e.reference && <div className="muted" style={{ fontSize: '.8rem' }}>{e.reference}</div>}</td><td><b>{money(e.amount)}</b></td>
              <td>{admin && e.status === 'recorded' && <button className="btn sm secondary" onClick={() => voidIt(e)}>Void</button>}</td></tr>)}
          </tbody></table>)}
      </div>
      {list.data && <Pager page={page} hasPrev={!!list.data.previous} hasNext={!!list.data.next} onPage={setPage} total={list.data.count} />}
      {add && <ExpenseModal admin={admin} onClose={() => setAdd(false)} onSaved={() => { setAdd(false); toast('Expense recorded.'); list.reload() }} />}
    </>
  )
}

function ExpenseModal({ admin, onClose, onSaved }: { admin: boolean; onClose: () => void; onSaved: () => void }) {
  const { site } = useSite()
  const { me } = useAuth()
  const cats = useAsync(() => api<Cat[]>('/finance/categories/'), [])
  const pos = useAsync(() => api<PO[]>('/procurement/orders/'), [])
  const branches = site.branches.filter((b) => admin || me?.branch_ids.includes(b.id))
  const [f, setF] = useState({ category_id: '', branch_id: admin ? '' : String(branches[0]?.id ?? ''), description: '', amount: '', expense_date: today(), method: 'bank_transfer', reference: '', purchase_order_id: '' })
  const [newCat, setNewCat] = useState('')
  const [err, setErr] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!f.category_id || !f.description.trim() || !/^\d+(\.\d{1,2})?$/.test(f.amount) || Number(f.amount) <= 0) return setErr('Choose a category, describe the cost and enter an amount like 120.50.')
    if (!admin && !f.branch_id) return setErr('Choose the branch.')
    try { await api('/finance/expenses/', { body: { ...f, category_id: Number(f.category_id), branch_id: f.branch_id ? Number(f.branch_id) : null, purchase_order_id: f.purchase_order_id ? Number(f.purchase_order_id) : null } }); onSaved() } catch (x) { setErr(msg(x)) }
  }
  async function addCat() { try { const c = await api<Cat>('/finance/categories/', { body: { name: newCat } }); setNewCat(''); cats.reload(); setF({ ...f, category_id: String(c.id) }) } catch (x) { setErr(msg(x)) } }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  return (
    <Modal title="Record expense" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="grid g2">
          <Field label="Category">{(p) => <select {...p} className="input" value={f.category_id} onChange={set('category_id')}><option value="">Choose…</option>{(cats.data ?? []).filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>}</Field>
          <Field label="Branch">{(p) => <select {...p} className="input" value={f.branch_id} onChange={set('branch_id')}>{admin && <option value="">Restaurant-wide</option>}{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>
          <Field label="Amount">{(p) => <input {...p} className="input" inputMode="decimal" placeholder="e.g. 120.50" value={f.amount} onChange={set('amount')} />}</Field>
          <Field label="Date">{(p) => <input {...p} className="input" type="date" max={today()} value={f.expense_date} onChange={set('expense_date')} />}</Field>
          <Field label="Paid by">{(p) => <select {...p} className="input" value={f.method} onChange={set('method')}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
          <Field label="Reference (optional)">{(p) => <input {...p} className="input" maxLength={60} value={f.reference} onChange={set('reference')} />}</Field>
        </div>
        <Field label="Description">{(p) => <input {...p} className="input" maxLength={200} value={f.description} onChange={set('description')} />}</Field>
        {(pos.data ?? []).length > 0 && <Field label="Purchase order (optional)">{(p) => <select {...p} className="input" value={f.purchase_order_id} onChange={set('purchase_order_id')}><option value="">None</option>{(pos.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.number} · {o.supplier}</option>)}</select>}</Field>}
        {admin && <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}><input className="input" aria-label="New category" placeholder="Need a new category?" value={newCat} onChange={(e) => setNewCat(e.target.value)} /><button type="button" className="btn sm secondary" disabled={!newCat.trim()} onClick={addCat}>Add</button></div>}
        <button className="btn">Record expense</button>
      </form>
    </Modal>
  )
}

// ----------------------------------------------------------------------------------------------- invoices
function Invoices() {
  const { money } = useSite()
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number | 'new' | null>(null)
  const list = useAsync(() => api<Page<Inv> & { outstanding: string }>('/finance/invoices/', { params: { status, page } }), [status, page])
  return (
    <>
      <div className="toolbar"><div className="chips" role="group" aria-label="Status">{['', 'draft', 'issued', 'paid', 'void'].map((s) => <button key={s} className="chip" aria-pressed={status === s} onClick={() => { setStatus(s); setPage(1) }}>{s || 'All'}</button>)}</div>
        <span style={{ flex: 1 }} />{list.data && <span className="muted">Outstanding: <b>{money(list.data.outstanding)}</b></span>}<button className="btn" onClick={() => setOpen('new')}><Plus size={16} aria-hidden /> New invoice</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title="No invoices yet" /> : (
          <table className="tbl"><thead><tr><th>Number</th><th>Customer</th><th>Issued</th><th>Due</th><th>Total</th><th>Balance</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((i) => <tr key={i.id}><td><b>{i.number || 'Draft'}</b></td><td>{i.customer_name}</td><td>{i.issue_date ?? '–'}</td><td style={{ color: i.overdue ? 'var(--danger)' : undefined }}>{i.due_date ?? '–'}{i.overdue && ' · overdue'}</td><td>{money(i.total)}</td><td>{money(i.balance)}</td><td><span className={`badge ${INV_BADGE[i.status]}`}>{i.status}</span></td><td><button className="btn sm" onClick={() => setOpen(i.id)}>Open</button></td></tr>)}
          </tbody></table>)}
      </div>
      {list.data && <Pager page={page} hasPrev={!!list.data.previous} hasNext={!!list.data.next} onPage={setPage} total={list.data.count} />}
      {open === 'new' && <InvoiceEditor onClose={() => setOpen(null)} onSaved={(id) => { list.reload(); setOpen(id) }} />}
      {typeof open === 'number' && <InvoiceDrawer id={open} onClose={() => setOpen(null)} onChanged={list.reload} />}
    </>
  )
}

function InvoiceEditor({ id, initial, onClose, onSaved }: { id?: number; initial?: Inv; onClose: () => void; onSaved: (id: number) => void }) {
  const [f, setF] = useState({ customer_name: initial?.customer_name ?? '', customer_email: initial?.customer_email ?? '', customer_address: initial?.customer_address ?? '', notes: initial?.notes ?? '' })
  const [lines, setLines] = useState(initial?.lines?.length ? initial.lines.map((l) => ({ description: l.description, quantity: String(Number(l.quantity)), unit_price: l.unit_price })) : [{ description: '', quantity: '1', unit_price: '' }])
  const [err, setErr] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!f.customer_name.trim()) return setErr('Enter the customer name.')
    if (lines.some((l) => !l.description.trim() || !(Number(l.quantity) > 0) || l.unit_price === '' || Number(l.unit_price) < 0)) return setErr('Complete every line.')
    try { const r = await api<Inv>(id ? `/finance/invoices/${id}/` : '/finance/invoices/', { method: id ? 'PATCH' : 'POST', body: { ...f, lines } }); onSaved(r.id) } catch (x) { setErr(msg(x)) }
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  return (
    <Modal title={id ? 'Edit draft invoice' : 'New invoice'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="grid g2">
          <Field label="Customer">{(p) => <input {...p} className="input" value={f.customer_name} onChange={set('customer_name')} />}</Field>
          <Field label="Email (optional)">{(p) => <input {...p} className="input" type="email" value={f.customer_email} onChange={set('customer_email')} />}</Field>
        </div>
        <Field label="Address (optional)">{(p) => <input {...p} className="input" value={f.customer_address} onChange={set('customer_address')} />}</Field>
        <h3>Lines</h3>
        {lines.map((l, i) => (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '3fr 1fr 1fr auto', gap: 6, marginBottom: 6 }}>
            <input className="input" aria-label="Description" placeholder="Description" value={l.description} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} />
            <input className="input" aria-label="Quantity" inputMode="decimal" value={l.quantity} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
            <input className="input" aria-label="Unit price" inputMode="decimal" placeholder="Price" value={l.unit_price} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, unit_price: e.target.value } : x)))} />
            <button type="button" className="btn sm secondary" aria-label="Remove line" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button>
          </div>))}
        <button type="button" className="btn sm secondary" onClick={() => setLines([...lines, { description: '', quantity: '1', unit_price: '' }])}>+ Add line</button>
        <Field label="Notes (shown on the invoice)">{(p) => <input {...p} className="input" maxLength={500} value={f.notes} onChange={set('notes')} />}</Field>
        <p className="hint">Tax is added using the restaurant tax rate. Totals are calculated by the server.</p>
        <button className="btn">Save draft</button>
      </form>
    </Modal>
  )
}

function InvoiceDrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const { money } = useSite()
  const { me } = useAuth()
  const toast = useToast()
  const admin = me?.role === 'restaurant_admin' || me?.role === 'platform_admin'
  const d = useAsync(() => api<Inv>(`/finance/invoices/${id}/`), [id])
  const [due, setDue] = useState(() => new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10))
  const [pay, setPay] = useState({ amount: '', method: 'bank_transfer', reference: '', received_on: today() })
  const [key] = useState(() => crypto.randomUUID())
  const [editing, setEditing] = useState(false)
  const i = d.data
  const done = () => { d.reload(); onChanged() }
  async function issue() { try { await api(`/finance/invoices/${id}/issue/`, { body: { due_date: due } }); toast('Invoice issued.'); done() } catch (x) { toast(msg(x)) } }
  async function record(e: FormEvent) {
    e.preventDefault()
    if (!/^\d+(\.\d{1,2})?$/.test(pay.amount) || Number(pay.amount) <= 0) return toast('Enter the amount received.')
    try { await api(`/finance/invoices/${id}/payments/`, { body: pay, headers: { 'Idempotency-Key': `${key}-${pay.amount}-${pay.received_on}` } }); toast('Payment recorded.'); setPay({ ...pay, amount: '', reference: '' }); done() } catch (x) { toast(msg(x)) }
  }
  async function voidIt() { const reason = (prompt('Reason for voiding this invoice:') ?? '').trim(); if (!reason) return; try { await api(`/finance/invoices/${id}/void/`, { body: { reason } }); toast('Invoice voided.'); done() } catch (x) { toast(msg(x)) } }
  return (
    <Drawer title={i ? (i.number || 'Draft invoice') : 'Invoice'} onClose={onClose}>
      {d.error && <ErrorState message={d.error} />}
      {!i ? !d.error && <Skeleton h={180} /> : (
        <>
          <p><span className={`badge ${INV_BADGE[i.status]}`}>{i.status}</span> <b>{i.customer_name}</b>{i.customer_email && <span className="muted"> · {i.customer_email}</span>}</p>
          {i.void_reason && <div className="alert warn">Voided: {i.void_reason}</div>}
          <table className="tbl"><tbody>
            {i.lines?.map((l, k) => <tr key={k}><td>{l.description} <span className="muted">{Number(l.quantity)} × {money(l.unit_price)}</span></td><td style={{ textAlign: 'right' }}>{money(l.line_total)}</td></tr>)}
            <tr><td>Subtotal</td><td style={{ textAlign: 'right' }}>{money(i.subtotal)}</td></tr><tr><td>Tax ({Number(i.tax_rate_percent)}%)</td><td style={{ textAlign: 'right' }}>{money(i.tax_total)}</td></tr>
            <tr><td><b>Total</b></td><td style={{ textAlign: 'right' }}><b>{money(i.total)}</b></td></tr><tr><td>Paid</td><td style={{ textAlign: 'right' }}>{money(i.amount_paid)}</td></tr><tr><td><b>Balance</b></td><td style={{ textAlign: 'right' }}><b>{money(i.balance)}</b></td></tr>
          </tbody></table>
          {i.payments && i.payments.length > 0 && <><h3 style={{ marginTop: 14 }}>Payments</h3>{i.payments.map((p, k) => <div className="list-row" key={k}><span>{p.received_on} · {p.method.replace('_', ' ')} {p.reference}</span><b>{money(p.amount)}</b></div>)}</>}
          {i.status === 'draft' && (
            <div style={{ marginTop: 14 }}>
              <div className="grid g2"><Field label="Payment due by">{(p) => <input {...p} className="input" type="date" min={today()} value={due} onChange={(e) => setDue(e.target.value)} />}</Field></div>
              <div style={{ display: 'flex', gap: 8 }}><button className="btn" onClick={issue}>Issue invoice</button><button className="btn secondary" onClick={() => setEditing(true)}>Edit draft</button></div>
              <p className="hint">Once issued, the invoice gets its number and can no longer be edited.</p>
            </div>)}
          {i.status === 'issued' && (
            <form onSubmit={record} style={{ marginTop: 14 }}>
              <h3>Record a payment</h3>
              <div className="grid g2">
                <Field label="Amount">{(p) => <input {...p} className="input" inputMode="decimal" placeholder={i.balance} value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} />}</Field>
                <Field label="Received on">{(p) => <input {...p} className="input" type="date" max={today()} value={pay.received_on} onChange={(e) => setPay({ ...pay, received_on: e.target.value })} />}</Field>
                <Field label="Method">{(p) => <select {...p} className="input" value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
                <Field label="Reference">{(p) => <input {...p} className="input" maxLength={60} value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} />}</Field>
              </div>
              <button className="btn">Record payment</button>
            </form>)}
          <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
            {i.status !== 'draft' && <button className="btn secondary" onClick={() => downloadFile(`/finance/invoices/${id}/pdf/`, `${i.number}.pdf`).catch(() => toast('Could not download.'))}><Download size={16} aria-hidden /> PDF</button>}
            {admin && i.status !== 'void' && Number(i.amount_paid) === 0 && <button className="btn danger" onClick={voidIt}>Void invoice</button>}
          </div>
        </>
      )}
      {editing && i && <InvoiceEditor id={id} initial={i} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); done() }} />}
    </Drawer>
  )
}

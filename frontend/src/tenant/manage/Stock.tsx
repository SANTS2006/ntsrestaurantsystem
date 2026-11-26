import { AlertTriangle, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Drawer, Empty, ErrorState, Field, Modal, PageHeader, Pager, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'
import { usePrompt } from '../../ui/dialogs'

type Ing = { id: number; name: string; unit: string; low_stock_threshold: string; last_unit_cost: string; is_active: boolean; total: string; low: boolean; branches: { branch_id: number; branch: string; quantity: string; low: boolean }[] }
type Sup = { id: number; name: string; contact_name: string; phone: string; email: string; address: string; notes: string; is_active: boolean }
type PO = { id: number; number: string; status: string; supplier: string; supplier_id: number; branch: string; branch_id: number; expected_date: string | null; total: string; notes: string; cancel_reason: string; lines?: { id: number; ingredient_id: number; ingredient: string; unit: string; quantity: string; unit_cost: string; received: string }[] }
type Mv = { id: number; ingredient: string; unit: string; branch: string; delta: string; quantity_after: string; reason: string; note: string; actor: string | null; created_at: string }
type Prod = { id: number; name: string }

const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'Something went wrong.')
const UNITS = [['kg', 'kg'], ['g', 'g'], ['l', 'litre'], ['ml', 'ml'], ['pcs', 'pieces'], ['pack', 'packs'], ['box', 'boxes']]
const PO_BADGE: Record<string, string> = { draft: '', ordered: 'info', partially_received: 'warn', received: 'ok', cancelled: 'bad' }

export default function Stock() {
  useDocumentTitle('Stock and purchasing')
  const [tab, setTab] = useState<'ingredients' | 'orders' | 'suppliers' | 'recipes' | 'movements'>('ingredients')
  return (
    <>
      <PageHeader title="Stock and purchasing" subtitle="Ingredients, recipes, suppliers and purchase orders. Selling a dish with a recipe uses up its ingredients automatically.">
        <div className="seg" role="tablist" aria-label="Sections">
          {([['ingredients', 'Ingredients'], ['orders', 'Purchase orders'], ['suppliers', 'Suppliers'], ['recipes', 'Recipes'], ['movements', 'History']] as const).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}
        </div>
      </PageHeader>
      {tab === 'ingredients' && <Ingredients />}
      {tab === 'orders' && <Orders />}
      {tab === 'suppliers' && <Suppliers />}
      {tab === 'recipes' && <Recipes />}
      {tab === 'movements' && <Movements />}
    </>
  )
}

function Ingredients() {
  const toast = useToast()
  const { site } = useSite()
  const { me } = useAuth()
  const [low, setLow] = useState(false)
  const [add, setAdd] = useState(false)
  const [adj, setAdj] = useState<Ing | null>(null)
  const list = useAsync(() => api<Ing[]>('/procurement/ingredients/', { params: { active: 1, low: low ? 1 : undefined } }), [low])
  const branches = site.branches.filter((b) => me?.role === 'restaurant_admin' || me?.role === 'platform_admin' || me?.branch_ids.includes(b.id))
  return (
    <>
      <div className="toolbar"><div className="chips"><button className="chip" aria-pressed={!low} onClick={() => setLow(false)}>All</button><button className="chip" aria-pressed={low} onClick={() => setLow(true)}>Low stock</button></div>
        <span style={{ flex: 1 }} /><button className="btn" onClick={() => setAdd(true)}><Plus size={16} aria-hidden /> New ingredient</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.length ? <Empty title={low ? 'Nothing is running low' : 'No ingredients yet'}>Add ingredients, then give each dish a recipe.</Empty> : (
          <table className="tbl"><thead><tr><th>Ingredient</th><th>In stock</th><th>Alert at</th><th>By branch</th><th>Last cost</th><th /></tr></thead><tbody>
            {list.data.map((i) => <tr key={i.id}><td><b>{i.name}</b></td><td>{i.low && <AlertTriangle size={14} color="var(--warn)" aria-label="Low stock" />} <b className="num">{Number(i.total)}</b> {i.unit}</td><td>{Number(i.low_stock_threshold)} {i.unit}</td>
              <td className="muted">{i.branches.map((b) => `${b.branch}: ${Number(b.quantity)}`).join(' · ') || '–'}</td><td>{Number(i.last_unit_cost) ? Number(i.last_unit_cost) : '–'}</td><td><button className="btn sm" onClick={() => setAdj(i)}>Adjust</button></td></tr>)}
          </tbody></table>)}
      </div>
      {add && <IngredientModal onClose={() => setAdd(false)} onSaved={() => { setAdd(false); list.reload() }} />}
      {adj && <AdjustModal ing={adj} branches={branches} onClose={() => setAdj(null)} onSaved={() => { setAdj(null); toast('Stock updated.'); list.reload() }} />}
    </>
  )
}

function IngredientModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: '', unit: 'kg', low_stock_threshold: '0' })
  const [err, setErr] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!f.name.trim()) return setErr('Enter a name.')
    try { await api('/procurement/ingredients/', { body: f }); onSaved() } catch (x) { setErr(msg(x)) }
  }
  return (
    <Modal title="New ingredient" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {err && <div className="alert error" role="alert">{err}</div>}
        <Field label="Name">{(p) => <input {...p} className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
        <div className="grid g2">
          <Field label="Unit">{(p) => <select {...p} className="input" value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })}>{UNITS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
          <Field label="Alert when below" hint="Shown as low stock at or under this amount.">{(p) => <input {...p} className="input" inputMode="decimal" value={f.low_stock_threshold} onChange={(e) => setF({ ...f, low_stock_threshold: e.target.value })} />}</Field>
        </div>
        <button className="btn">Add ingredient</button>
      </form>
    </Modal>
  )
}

function AdjustModal({ ing, branches, onClose, onSaved }: { ing: Ing; branches: { id: number; name: string }[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ branch_id: String(branches[0]?.id ?? ''), mode: 'delta', quantity: '', reason: 'adjustment', note: '' })
  const [err, setErr] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!f.quantity.trim() || Number.isNaN(Number(f.quantity))) return setErr('Enter a quantity.')
    if (f.note.trim().length < 3) return setErr('Explain the change.')
    try { await api('/procurement/stock/adjust/', { body: { ingredient_id: ing.id, ...f, branch_id: Number(f.branch_id) } }); onSaved() } catch (x) { setErr(msg(x)) }
  }
  return (
    <Modal title={`Adjust ${ing.name}`} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="grid g2">
          <Field label="Branch">{(p) => <select {...p} className="input" value={f.branch_id} onChange={(e) => setF({ ...f, branch_id: e.target.value })}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>
          <Field label="Why">{(p) => <select {...p} className="input" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value, mode: e.target.value === 'waste' ? 'delta' : f.mode })}><option value="adjustment">Stock count correction</option><option value="waste">Waste or spoilage</option><option value="opening">Opening stock</option></select>}</Field>
          <Field label="Change">{(p) => <select {...p} className="input" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option value="delta">Add or remove an amount</option><option value="set">Set to the counted amount</option></select>}</Field>
          <Field label={`Quantity (${ing.unit})`} hint={f.mode === 'delta' ? 'Use a minus sign to remove, e.g. -2.5' : 'The total you counted'}>{(p) => <input {...p} className="input" inputMode="decimal" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} />}</Field>
        </div>
        <Field label="Note (recorded)">{(p) => <input {...p} className="input" maxLength={200} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />}</Field>
        <button className="btn">Save</button>
      </form>
    </Modal>
  )
}

function Suppliers() {
  const list = useAsync(() => api<Sup[]>('/procurement/suppliers/'), [])
  const toast = useToast()
  const [edit, setEdit] = useState<Partial<Sup> | null>(null)
  async function toggle(s: Sup) { try { await api(`/procurement/suppliers/${s.id}/`, { method: 'PATCH', body: { is_active: !s.is_active } }); list.reload() } catch (e) { toast(msg(e)) } }
  return (
    <>
      <div className="toolbar"><span style={{ flex: 1 }} /><button className="btn" onClick={() => setEdit({})}><Plus size={16} aria-hidden /> New supplier</button></div>
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={100} /> : !list.data?.length ? <Empty title="No suppliers yet" /> : (
          <table className="tbl"><thead><tr><th>Supplier</th><th>Contact</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.map((s) => <tr key={s.id}><td><b>{s.name}</b></td><td>{s.contact_name}<div className="muted" style={{ fontSize: '.8rem' }}>{s.phone} {s.email}</div></td><td><span className={`badge ${s.is_active ? 'active' : ''}`}>{s.is_active ? 'active' : 'archived'}</span></td>
              <td style={{ whiteSpace: 'nowrap' }}><button className="btn sm secondary" onClick={() => setEdit(s)}>Edit</button> <button className="btn sm ghost" onClick={() => toggle(s)}>{s.is_active ? 'Archive' : 'Restore'}</button></td></tr>)}
          </tbody></table>)}
      </div>
      {edit && <SupplierModal s={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
    </>
  )
}

function SupplierModal({ s, onClose, onSaved }: { s: Partial<Sup>; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: s.name ?? '', contact_name: s.contact_name ?? '', phone: s.phone ?? '', email: s.email ?? '', address: s.address ?? '', notes: s.notes ?? '' })
  const [err, setErr] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!f.name.trim()) return setErr('Enter the supplier name.')
    try { await api(s.id ? `/procurement/suppliers/${s.id}/` : '/procurement/suppliers/', { method: s.id ? 'PATCH' : 'POST', body: f }); onSaved() } catch (x) { setErr(msg(x)) }
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  return (
    <Modal title={s.id ? 'Edit supplier' : 'New supplier'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="grid g2">
          <Field label="Name">{(p) => <input {...p} className="input" value={f.name} onChange={set('name')} />}</Field>
          <Field label="Contact person">{(p) => <input {...p} className="input" value={f.contact_name} onChange={set('contact_name')} />}</Field>
          <Field label="Phone">{(p) => <input {...p} className="input" type="tel" value={f.phone} onChange={set('phone')} />}</Field>
          <Field label="Email">{(p) => <input {...p} className="input" type="email" value={f.email} onChange={set('email')} />}</Field>
        </div>
        <Field label="Address">{(p) => <input {...p} className="input" value={f.address} onChange={set('address')} />}</Field>
        <Field label="Notes">{(p) => <input {...p} className="input" value={f.notes} onChange={set('notes')} />}</Field>
        <button className="btn">Save</button>
      </form>
    </Modal>
  )
}

function Orders() {
  const { money } = useSite()
  const [open, setOpen] = useState<number | 'new' | null>(null)
  const list = useAsync(() => api<PO[]>('/procurement/orders/'), [])
  return (
    <>
      <div className="toolbar"><span style={{ flex: 1 }} /><button className="btn" onClick={() => setOpen('new')}><Plus size={16} aria-hidden /> New purchase order</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={100} /> : !list.data?.length ? <Empty title="No purchase orders yet" /> : (
          <table className="tbl"><thead><tr><th>Number</th><th>Supplier</th><th>Branch</th><th>Expected</th><th>Total</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.map((p) => <tr key={p.id}><td><b>{p.number}</b></td><td>{p.supplier}</td><td>{p.branch}</td><td>{p.expected_date ?? '–'}</td><td>{money(p.total)}</td><td><span className={`badge ${PO_BADGE[p.status]}`}>{p.status.replace('_', ' ')}</span></td><td><button className="btn sm" onClick={() => setOpen(p.id)}>Open</button></td></tr>)}
          </tbody></table>)}
      </div>
      {open === 'new' && <NewPO onClose={() => setOpen(null)} onSaved={(id) => { list.reload(); setOpen(id) }} />}
      {typeof open === 'number' && <PODrawer id={open} onClose={() => setOpen(null)} onChanged={list.reload} />}
    </>
  )
}

function NewPO({ onClose, onSaved }: { onClose: () => void; onSaved: (id: number) => void }) {
  const { site } = useSite()
  const { me } = useAuth()
  const sups = useAsync(() => api<Sup[]>('/procurement/suppliers/', { params: { active: 1 } }), [])
  const ings = useAsync(() => api<Ing[]>('/procurement/ingredients/', { params: { active: 1 } }), [])
  const branches = site.branches.filter((b) => me?.role === 'restaurant_admin' || me?.role === 'platform_admin' || me?.branch_ids.includes(b.id))
  const [f, setF] = useState({ branch_id: String(branches[0]?.id ?? ''), supplier_id: '', expected_date: '' })
  const [lines, setLines] = useState([{ ingredient_id: '', quantity: '', unit_cost: '' }])
  const [err, setErr] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!f.supplier_id) return setErr('Choose a supplier.')
    if (lines.some((l) => !l.ingredient_id || !(Number(l.quantity) > 0) || l.unit_cost === '' || Number(l.unit_cost) < 0)) return setErr('Complete every line: ingredient, quantity and unit cost.')
    try {
      const po = await api<PO>('/procurement/orders/', { body: { branch_id: Number(f.branch_id), supplier_id: Number(f.supplier_id), expected_date: f.expected_date || null, lines: lines.map((l) => ({ ingredient_id: Number(l.ingredient_id), quantity: l.quantity, unit_cost: l.unit_cost })) } })
      onSaved(po.id)
    } catch (x) { setErr(msg(x)) }
  }
  return (
    <Modal title="New purchase order" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {err && <div className="alert error" role="alert">{err}</div>}
        <div className="grid g2">
          <Field label="Deliver to">{(p) => <select {...p} className="input" value={f.branch_id} onChange={(e) => setF({ ...f, branch_id: e.target.value })}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}</Field>
          <Field label="Supplier">{(p) => <select {...p} className="input" value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: e.target.value })}><option value="">Choose…</option>{(sups.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}</Field>
          <Field label="Expected on">{(p) => <input {...p} className="input" type="date" value={f.expected_date} onChange={(e) => setF({ ...f, expected_date: e.target.value })} />}</Field>
        </div>
        <h3>Lines</h3>
        {lines.map((l, i) => (
          <div key={i} className="line-row" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto', gap: 6, marginBottom: 6 }}>
            <select className="input" aria-label="Ingredient" value={l.ingredient_id} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, ingredient_id: e.target.value } : x)))}><option value="">Ingredient…</option>{(ings.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name} ({g.unit})</option>)}</select>
            <input className="input" aria-label="Quantity" inputMode="decimal" placeholder="Qty" value={l.quantity} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
            <input className="input" aria-label="Unit cost" inputMode="decimal" placeholder="Unit cost" value={l.unit_cost} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, unit_cost: e.target.value } : x)))} />
            <button type="button" className="btn sm secondary" aria-label="Remove line" onClick={() => setLines(lines.filter((_, j) => j !== i))} disabled={lines.length === 1}>✕</button>
          </div>))}
        <button type="button" className="btn sm secondary" onClick={() => setLines([...lines, { ingredient_id: '', quantity: '', unit_cost: '' }])}>+ Add line</button>
        <p><button className="btn" style={{ marginTop: 12 }}>Save as draft</button></p>
      </form>
    </Modal>
  )
}

function PODrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const prompt = usePrompt()
  const { money } = useSite()
  const toast = useToast()
  const d = useAsync(() => api<PO>(`/procurement/orders/${id}/`), [id])
  const [recv, setRecv] = useState<Record<number, string>>({})
  const po = d.data
  async function act(a: string, body: unknown = {}) {
    try { await api(`/procurement/orders/${id}/${a}/`, { body }); d.reload(); onChanged(); setRecv({}) } catch (e) { toast(msg(e)) }
  }
  async function cancel() { const reason = (await prompt({ title: 'Cancel this purchase order?', label: 'Reason', required: true, danger: true, confirmLabel: 'Cancel order' })) ?? ''; if (reason) void act('cancel', { reason }) }
  return (
    <Drawer title={po ? `Purchase order ${po.number}` : 'Purchase order'} onClose={onClose}>
      {d.error && <ErrorState message={d.error} />}
      {!po ? !d.error && <Skeleton h={160} /> : (
        <>
          <p><span className={`badge ${PO_BADGE[po.status]}`}>{po.status.replace('_', ' ')}</span> {po.supplier} → {po.branch}{po.expected_date && <> · expected {po.expected_date}</>}</p>
          {po.cancel_reason && <div className="alert warn">Cancelled: {po.cancel_reason}</div>}
          <table className="tbl"><thead><tr><th>Ingredient</th><th>Ordered</th><th>Received</th><th>Cost</th>{po.status === 'ordered' || po.status === 'partially_received' ? <th>Receive now</th> : null}</tr></thead><tbody>
            {po.lines?.map((l) => <tr key={l.id}><td>{l.ingredient}</td><td>{Number(l.quantity)} {l.unit}</td><td>{Number(l.received)}</td><td>{Number(l.unit_cost)}</td>
              {po.status === 'ordered' || po.status === 'partially_received' ? <td><input className="input" style={{ width: 90 }} inputMode="decimal" aria-label={`Receive ${l.ingredient}`} placeholder={String(Number(l.quantity) - Number(l.received))} value={recv[l.id] ?? ''} onChange={(e) => setRecv({ ...recv, [l.id]: e.target.value })} /></td> : null}</tr>)}
          </tbody></table>
          <p style={{ textAlign: 'right' }}><b>Total {money(po.total)}</b></p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {po.status === 'draft' && <button className="btn" onClick={() => act('order')}>Place order</button>}
            {(po.status === 'ordered' || po.status === 'partially_received') && <button className="btn" onClick={() => act('receive', { lines: Object.entries(recv).filter(([, v]) => Number(v) > 0).map(([k, v]) => ({ line_id: Number(k), quantity: v })) })}>Record delivery</button>}
            {(po.status === 'draft' || po.status === 'ordered') && <button className="btn danger" onClick={cancel}>Cancel order</button>}
          </div>
          <p className="hint" style={{ marginTop: 10 }}>Record what you pay for it under Finance → Expenses and link this order.</p>
        </>
      )}
    </Drawer>
  )
}

function Recipes() {
  const toast = useToast()
  const products = useAsync(() => api<Page<Prod>>('/catalog/products/', { params: { page_size: 100 } }), [])
  const ings = useAsync(() => api<Ing[]>('/procurement/ingredients/', { params: { active: 1 } }), [])
  const [pid, setPid] = useState('')
  const [lines, setLines] = useState<{ ingredient_id: string; quantity: string }[]>([])
  const [loadedFor, setLoadedFor] = useState('')
  if (pid && loadedFor !== pid) {
    setLoadedFor(pid)
    void api<{ ingredient_id: number; quantity: string }[]>(`/procurement/products/${pid}/recipe/`).then((r) => setLines(r.map((x) => ({ ingredient_id: String(x.ingredient_id), quantity: String(Number(x.quantity)) }))))
  }
  async function save() {
    if (lines.some((l) => !l.ingredient_id || !(Number(l.quantity) > 0))) return toast('Complete every line.')
    try { await api(`/procurement/products/${pid}/recipe/`, { method: 'PUT', body: { lines: lines.map((l) => ({ ingredient_id: Number(l.ingredient_id), quantity: l.quantity })) } }); toast('Recipe saved.') } catch (e) { toast(msg(e)) }
  }
  return (
    <div className="card" style={{ maxWidth: 720 }}>
      <p className="muted">List what ONE portion of a dish uses. Each sale takes these amounts from the stock of the branch that made it (and cancelling gives them back). Dishes without a recipe are not tracked.</p>
      <Field label="Dish">{(p) => <select {...p} className="input" value={pid} onChange={(e) => { setPid(e.target.value); setLoadedFor('') }}><option value="">Choose a dish…</option>{(products.data?.results ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>}</Field>
      {pid && (
        <>
          {lines.map((l, i) => (
            <div key={i} className="line-row" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr auto', gap: 6, marginBottom: 6 }}>
              <select className="input" aria-label="Ingredient" value={l.ingredient_id} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, ingredient_id: e.target.value } : x)))}><option value="">Ingredient…</option>{(ings.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name} ({g.unit})</option>)}</select>
              <input className="input" aria-label="Quantity per portion" inputMode="decimal" placeholder="Per portion" value={l.quantity} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
              <button type="button" className="btn sm secondary" aria-label="Remove ingredient" onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button>
            </div>))}
          <div style={{ display: 'flex', gap: 8 }}><button className="btn sm secondary" onClick={() => setLines([...lines, { ingredient_id: '', quantity: '' }])}>+ Add ingredient</button><button className="btn" onClick={save}>Save recipe</button></div>
        </>
      )}
    </div>
  )
}

function Movements() {
  const [page, setPage] = useState(1)
  const list = useAsync(() => api<Page<Mv>>('/procurement/stock/movements/', { params: { page } }), [page])
  return (
    <>
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={100} /> : !list.data?.results.length ? <Empty title="No stock movements yet" /> : (
          <table className="tbl"><thead><tr><th>When</th><th>Ingredient</th><th>Branch</th><th>Change</th><th>After</th><th>Reason</th><th>By</th></tr></thead><tbody>
            {list.data.results.map((m) => <tr key={m.id}><td>{new Date(m.created_at).toLocaleString()}</td><td>{m.ingredient}</td><td>{m.branch}</td><td style={{ color: Number(m.delta) < 0 ? 'var(--danger)' : 'var(--ok)' }}><b>{Number(m.delta) > 0 ? '+' : ''}{Number(m.delta)}</b> {m.unit}</td><td>{Number(m.quantity_after)}</td><td>{m.reason.replace('_', ' ')}<div className="muted" style={{ fontSize: '.8rem' }}>{m.note}</div></td><td>{m.actor ?? '–'}</td></tr>)}
          </tbody></table>)}
      </div>
      {list.data && <Pager page={page} hasPrev={!!list.data.previous} hasNext={!!list.data.next} onPage={setPage} total={list.data.count} />}
    </>
  )
}

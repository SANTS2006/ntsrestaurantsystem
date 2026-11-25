import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'

const price = (v: string) => /^\d+(\.\d{1,2})?$/.test(v.trim())
const msg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')
const H = ({ children }: { children: string }) => <h1 className="page-title">{children}</h1>

function Pager<T>({ list, page, setPage }: { list: { data: Page<T> | null }; page: number; setPage: (n: number) => void }) {
  if (!list.data || (!list.data.next && !list.data.previous)) return null
  return (
    <div className="toolbar" style={{ marginTop: 12 }}>
      <button className="btn sm secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button>
      <span className="muted">Page {page}</span>
      <button className="btn sm secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button>
    </div>
  )
}

/* ------------------------------------------------------------------ categories */
type Cat = { id: number; name: string; slug: string; description: string; sort_order: number; is_active: boolean }

export function Categories() {
  useDocumentTitle('Categories')
  const toast = useToast()
  const list = useAsync(() => api<Page<Cat>>('/catalog/categories/', { params: { page_size: 100 } }), [])
  const [edit, setEdit] = useState<Cat | 'new' | null>(null)
  const toggle = async (c: Cat) => {
    try { await api(`/catalog/categories/${c.id}/`, { method: 'PATCH', body: { is_active: !c.is_active } }); list.reload() } catch (e) { toast(msg(e)) }
  }
  return (
    <>
      <div className="toolbar"><div style={{ flex: 1 }}><H>Categories</H></div><button className="btn" onClick={() => setEdit('new')}><Plus size={18} aria-hidden /> Add category</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading ? <Skeleton h={80} /> : !list.data?.results.length ? <Empty title="No categories yet">Create categories such as Breakfast, Main Dishes or Drinks.</Empty> : (
          <table className="tbl"><thead><tr><th>Name</th><th>Order</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((c) => (
              <tr key={c.id}><td>{c.name}</td><td>{c.sort_order}</td><td><span className={`badge ${c.is_active ? 'active' : 'suspended'}`}>{c.is_active ? 'visible' : 'hidden'}</span></td>
                <td style={{ display: 'flex', gap: 6 }}><button className="btn sm secondary" onClick={() => setEdit(c)}>Edit</button><button className="btn sm secondary" onClick={() => toggle(c)}>{c.is_active ? 'Hide' : 'Show'}</button></td></tr>
            ))}
          </tbody></table>
        )}
      </div>
      {edit && <CategoryForm initial={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
    </>
  )
}

function CategoryForm({ initial, onClose, onSaved }: { initial: Cat | null; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ name: initial?.name ?? '', description: initial?.description ?? '', sort_order: String(initial?.sort_order ?? 0) })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!v.name.trim()) return setErrors({ name: 'Enter the category name.' })
    setBusy(true)
    try {
      await api(initial ? `/catalog/categories/${initial.id}/` : '/catalog/categories/', { method: initial ? 'PATCH' : 'POST', body: { ...v, sort_order: Number(v.sort_order) || 0 } })
      onSaved()
    } catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Error' }) } finally { setBusy(false) }
  }
  return (
    <Modal title={initial ? 'Edit category' : 'Add category'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && !errors.name && <div className="alert error">{errors.form}</div>}
        <Field label="Name" error={errors.name}>{(p) => <input {...p} className="input" placeholder="e.g. Rice dishes" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <Field label="Description" error={errors.description}>{(p) => <input {...p} className="input" placeholder="Short description (optional)" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />}</Field>
        <Field label="Display order" error={errors.sort_order}>{(p) => <input {...p} className="input" inputMode="numeric" placeholder="0" value={v.sort_order} onChange={(e) => setV({ ...v, sort_order: e.target.value })} />}</Field>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save'}</button>
      </form>
    </Modal>
  )
}

/* ------------------------------------------------------------------ products */
type Var = { id?: number; kind: string; name: string; price_delta: string; is_default: boolean; is_available: boolean }
type Add = { id?: number; name: string; price: string; max_quantity: number; is_available: boolean }
type Prod = {
  id: number; category: number; name: string; slug: string; description: string; image: string | null; base_price: string; offer_price: string | null
  offer_label: string; offer_ends_at: string | null; effective_price: string; is_available: boolean; is_featured: boolean; is_popular: boolean
  is_archived: boolean; prep_time_minutes: number | null; ingredients: string[]; allow_instructions: boolean; track_inventory: boolean
  stock_quantity: number; low_stock_threshold: number; sold_out: boolean; variations: Var[]; addons: Add[]
}

export function Products() {
  useDocumentTitle('Products')
  const toast = useToast()
  const { money } = useSite()
  const [q, setQ] = useState('')
  const [archived, setArchived] = useState(false)
  const [page, setPage] = useState(1)
  const [edit, setEdit] = useState<Prod | 'new' | null>(null)
  const [stock, setStock] = useState<Prod | null>(null)
  const cats = useAsync(() => api<Page<Cat>>('/catalog/categories/', { params: { page_size: 100 } }), [])
  const list = useAsync(() => api<Page<Prod>>('/catalog/products/', { params: { q, page, archived: archived ? 1 : undefined } }), [q, page, archived])

  async function act(p: Prod, path: string, body: unknown = {}, ok = 'Saved.') {
    try { await api(`/catalog/products/${p.id}/${path}`, { method: path ? 'POST' : 'PATCH', body }); toast(ok); list.reload() } catch (e) { toast(msg(e)) }
  }
  return (
    <>
      <div className="toolbar"><div style={{ flex: 1 }}><H>Products</H></div>
        <button className="btn" disabled={!cats.data?.results.length} onClick={() => setEdit('new')}><Plus size={18} aria-hidden /> Add product</button></div>
      {cats.data && !cats.data.results.length && <div className="alert">Create a category first, then add products to it.</div>}
      <div className="toolbar">
        <input className="input" style={{ maxWidth: 260 }} type="search" placeholder="Search products" aria-label="Search products" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="checkbox" checked={archived} onChange={(e) => { setArchived(e.target.checked); setPage(1) }} /> Show archived</label>
      </div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title={archived ? 'No archived products' : 'No products yet'} /> : (
          <table className="tbl"><thead><tr><th /><th>Name</th><th>Price</th><th>Available</th><th>Stock</th><th /></tr></thead><tbody>
            {list.data.results.map((p) => (
              <tr key={p.id}>
                <td>{p.image ? <img src={p.image} alt="" width={40} height={40} style={{ objectFit: 'cover', borderRadius: 6 }} /> : <span className="swatch" aria-hidden />}</td>
                <td><strong>{p.name}</strong>{p.is_featured && <span className="badge" style={{ marginLeft: 6 }}>featured</span>}</td>
                <td>{money(p.effective_price)}{p.offer_price && <s className="muted" style={{ marginLeft: 6 }}>{money(p.base_price)}</s>}</td>
                <td><label><input type="checkbox" checked={p.is_available} disabled={p.is_archived} onChange={() => act(p, '', { is_available: !p.is_available }, p.is_available ? 'Hidden from menu.' : 'Now on the menu.')} aria-label={`${p.name} available`} /></label></td>
                <td>{p.track_inventory ? <button className="btn sm secondary" onClick={() => setStock(p)}>{p.stock_quantity} · adjust</button> : <span className="muted">not tracked</span>}</td>
                <td style={{ display: 'flex', gap: 6 }}>
                  <button className="btn sm secondary" onClick={() => setEdit(p)}>Edit</button>
                  {p.is_archived ? <button className="btn sm" onClick={() => act(p, 'restore/', {}, 'Restored.')}>Restore</button>
                    : <button className="btn sm danger" onClick={() => confirm(`Archive ${p.name}? It will disappear from the menu but past orders keep it.`) && act(p, 'archive/', {}, 'Archived.')}>Archive</button>}
                </td>
              </tr>
            ))}
          </tbody></table>
        )}
      </div>
      <Pager list={list} page={page} setPage={setPage} />
      {edit && <ProductForm initial={edit === 'new' ? null : edit} cats={cats.data?.results ?? []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
      {stock && <StockModal product={stock} onClose={() => setStock(null)} onSaved={() => { setStock(null); list.reload() }} />}
    </>
  )
}

const blankVar = (): Var => ({ kind: 'size', name: '', price_delta: '0.00', is_default: false, is_available: true })
const blankAdd = (): Add => ({ name: '', price: '0.00', max_quantity: 1, is_available: true })

function ProductForm({ initial, cats, onClose, onSaved }: { initial: Prod | null; cats: Cat[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [v, setV] = useState({
    name: initial?.name ?? '', category: String(initial?.category ?? cats[0]?.id ?? ''), description: initial?.description ?? '',
    base_price: initial?.base_price ?? '', offer_price: initial?.offer_price ?? '', offer_label: initial?.offer_label ?? '',
    prep_time_minutes: initial?.prep_time_minutes ? String(initial.prep_time_minutes) : '', ingredients: (initial?.ingredients ?? []).join(', '),
    is_available: initial?.is_available ?? true, is_featured: initial?.is_featured ?? false, is_popular: initial?.is_popular ?? false,
    allow_instructions: initial?.allow_instructions ?? true, track_inventory: initial?.track_inventory ?? false,
    low_stock_threshold: String(initial?.low_stock_threshold ?? 5),
  })
  const [vars, setVars] = useState<Var[]>(initial?.variations ?? [])
  const [adds, setAdds] = useState<Add[]>(initial?.addons ?? [])
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })
  const chk = (k: keyof typeof v) => (e: { target: { checked: boolean } }) => setV({ ...v, [k]: e.target.checked })

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!v.name.trim()) local.name = 'Enter the product name.'
    if (!v.category) local.category = 'Choose a category.'
    if (!price(v.base_price)) local.base_price = 'Enter a price like 12.50.'
    if (v.offer_price && !price(v.offer_price)) local.offer_price = 'Enter a price like 9.99.'
    else if (v.offer_price && Number(v.offer_price) >= Number(v.base_price)) local.offer_price = 'Offer price must be lower than the regular price.'
    if (vars.some((x) => !x.name.trim() || !price(x.price_delta))) local.variations = 'Each option needs a name and a price difference like 0.00.'
    if (adds.some((x) => !x.name.trim() || !price(x.price))) local.addons = 'Each extra needs a name and a price like 1.50.'
    setErrors(local)
    if (Object.keys(local).length) return
    const body = {
      name: v.name.trim(), category: Number(v.category), description: v.description, base_price: v.base_price.trim(),
      offer_price: v.offer_price.trim() || null, offer_label: v.offer_label, prep_time_minutes: v.prep_time_minutes ? Number(v.prep_time_minutes) : null,
      ingredients: v.ingredients.split(',').map((s) => s.trim()).filter(Boolean), is_available: v.is_available, is_featured: v.is_featured,
      is_popular: v.is_popular, allow_instructions: v.allow_instructions, track_inventory: v.track_inventory,
      low_stock_threshold: Number(v.low_stock_threshold) || 0, variations: vars, addons: adds,
    }
    setBusy(true)
    try {
      const saved = await api<Prod>(initial ? `/catalog/products/${initial.id}/` : '/catalog/products/', { method: initial ? 'PATCH' : 'POST', body })
      if (file) {
        const fd = new FormData()
        fd.append('image', file)
        try { await api(`/catalog/products/${saved.id}/image/`, { body: fd }) } catch (err) { toast(`Saved, but the image was rejected: ${msg(err)}`) }
      }
      toast('Product saved.')
      onSaved()
    } catch (err) {
      setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Unexpected error.' })
    } finally { setBusy(false) }
  }
  const text = (k: 'name' | 'base_price' | 'offer_price' | 'offer_label' | 'prep_time_minutes' | 'ingredients' | 'low_stock_threshold', label: string, ph: string, hint?: string) => (
    <Field label={label} error={errors[k]} hint={hint}>{(p) => <input {...p} className="input" placeholder={ph} value={v[k]} onChange={set(k)} />}</Field>
  )
  return (
    <Modal title={initial ? `Edit ${initial.name}` : 'Add product'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
        {text('name', 'Name', 'e.g. Jollof rice')}
        <Field label="Category" error={errors.category}>{(p) => <select {...p} className="input" value={v.category} onChange={set('category')}>{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>}</Field>
        <Field label="Description" error={errors.description}>{(p) => <textarea {...p} className="input" rows={3} placeholder="Describe the dish" value={v.description} onChange={set('description')} />}</Field>
        <div className="grid g2">{text('base_price', 'Price', 'e.g. 45.00')}{text('prep_time_minutes', 'Preparation time (minutes)', 'e.g. 15')}</div>
        <div className="grid g2">{text('offer_price', 'Offer price (optional)', 'Lower than the price')}{text('offer_label', 'Offer label', 'e.g. Lunch special')}</div>
        {text('ingredients', 'Ingredients', 'Comma separated, e.g. rice, tomato, pepper')}
        <Field label="Image (PNG, JPEG or WebP, max 3 MB)" error={errors.image}>{(p) => <input {...p} className="input" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}</Field>

        <fieldset style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14 }}><legend>Sizes and options</legend>
          {vars.map((x, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
              <select className="input" style={{ width: 110 }} aria-label="Kind" value={x.kind} onChange={(e) => setVars(vars.map((y, j) => (j === i ? { ...y, kind: e.target.value } : y)))}><option value="size">Size</option><option value="variation">Option</option></select>
              <input className="input" style={{ flex: 1, minWidth: 110 }} placeholder="Name, e.g. Large" aria-label="Option name" value={x.name} onChange={(e) => setVars(vars.map((y, j) => (j === i ? { ...y, name: e.target.value } : y)))} />
              <input className="input" style={{ width: 90 }} placeholder="+0.00" aria-label="Price difference" value={x.price_delta} onChange={(e) => setVars(vars.map((y, j) => (j === i ? { ...y, price_delta: e.target.value } : y)))} />
              <label><input type="checkbox" checked={x.is_default} onChange={(e) => setVars(vars.map((y, j) => ({ ...y, is_default: j === i ? e.target.checked : false })))} /> default</label>
              <button type="button" className="btn sm secondary" aria-label="Remove option" onClick={() => setVars(vars.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
            </div>
          ))}
          {errors.variations && <p className="err">{errors.variations}</p>}
          <button type="button" className="btn sm secondary" onClick={() => setVars([...vars, blankVar()])}>Add option</button>
        </fieldset>
        <fieldset style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14 }}><legend>Extras and add-ons</legend>
          {adds.map((x, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
              <input className="input" style={{ flex: 1, minWidth: 110 }} placeholder="Name, e.g. Extra egg" aria-label="Extra name" value={x.name} onChange={(e) => setAdds(adds.map((y, j) => (j === i ? { ...y, name: e.target.value } : y)))} />
              <input className="input" style={{ width: 90 }} placeholder="1.50" aria-label="Extra price" value={x.price} onChange={(e) => setAdds(adds.map((y, j) => (j === i ? { ...y, price: e.target.value } : y)))} />
              <button type="button" className="btn sm secondary" aria-label="Remove extra" onClick={() => setAdds(adds.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
            </div>
          ))}
          {errors.addons && <p className="err">{errors.addons}</p>}
          <button type="button" className="btn sm secondary" onClick={() => setAdds([...adds, blankAdd()])}>Add extra</button>
        </fieldset>

        <div style={{ display: 'grid', gap: 6, marginBottom: 14 }}>
          <label><input type="checkbox" checked={v.is_available} onChange={chk('is_available')} /> Available on the menu</label>
          <label><input type="checkbox" checked={v.is_featured} onChange={chk('is_featured')} /> Featured dish</label>
          <label><input type="checkbox" checked={v.is_popular} onChange={chk('is_popular')} /> Popular dish</label>
          <label><input type="checkbox" checked={v.allow_instructions} onChange={chk('allow_instructions')} /> Let customers add special instructions</label>
          <label><input type="checkbox" checked={v.track_inventory} onChange={chk('track_inventory')} /> Track stock for this product</label>
        </div>
        {v.track_inventory && text('low_stock_threshold', 'Low-stock alert at', '5', 'Use the Inventory page or "adjust" in the list to change quantities.')}
        <button className="btn" style={{ width: '100%' }} disabled={busy}>{busy ? <Spinner /> : 'Save product'}</button>
      </form>
    </Modal>
  )
}

function StockModal({ product, onClose, onSaved }: { product: Prod; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [delta, setDelta] = useState('')
  const [reason, setReason] = useState('restock')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    const n = Number(delta)
    if (!Number.isInteger(n) || n === 0) return setError('Enter a whole number, e.g. 20 to add or -3 to remove.')
    setBusy(true)
    try { await api(`/catalog/products/${product.id}/stock/`, { body: { delta: n, reason, note } }); toast('Stock updated.'); onSaved() } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Adjust stock: ${product.name}`} onClose={onClose}>
      <p>Current stock: <b>{product.stock_quantity}</b></p>
      <form onSubmit={submit} noValidate>
        {error && <div className="alert error" role="alert">{error}</div>}
        <Field label="Change (+ add, − remove)">{(p) => <input {...p} className="input" inputMode="numeric" placeholder="e.g. 20 or -3" value={delta} onChange={(e) => setDelta(e.target.value)} />}</Field>
        <Field label="Reason">{(p) => <select {...p} className="input" value={reason} onChange={(e) => setReason(e.target.value)}><option value="restock">Restock</option><option value="adjustment">Count adjustment</option><option value="waste">Waste or spoilage</option><option value="return">Customer return</option></select>}</Field>
        <Field label="Note">{(p) => <input {...p} className="input" placeholder="Optional note" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Update stock'}</button>
      </form>
    </Modal>
  )
}

/* ------------------------------------------------------------------ inventory */
type Move = { id: number; product_name: string; delta: number; quantity_after: number; reason: string; note: string; actor_email: string | null; created_at: string }
export function Inventory() {
  useDocumentTitle('Inventory')
  const low = useAsync(() => api<Prod[]>('/catalog/products/low-stock/'), [])
  const moves = useAsync(() => api<Page<Move>>('/catalog/stock-movements/'), [])
  const [stock, setStock] = useState<Prod | null>(null)
  return (
    <>
      <H>Inventory</H>
      <h2 style={{ fontSize: '1.2rem' }}>Low stock</h2>
      {low.error && <ErrorState message={low.error} onRetry={low.reload} />}
      <div className="card table-wrap" style={{ marginBottom: 24 }}>
        {low.loading ? <Skeleton h={60} /> : !low.data?.length ? <Empty title="Nothing is running low" /> : (
          <table className="tbl"><thead><tr><th>Product</th><th>In stock</th><th>Alert at</th><th /></tr></thead><tbody>
            {low.data.map((p) => <tr key={p.id}><td>{p.name}</td><td><span className={`badge ${p.stock_quantity === 0 ? 'suspended' : ''}`}>{p.stock_quantity}</span></td><td>{p.low_stock_threshold}</td><td><button className="btn sm" onClick={() => setStock(p)}>Adjust</button></td></tr>)}
          </tbody></table>
        )}
      </div>
      <h2 style={{ fontSize: '1.2rem' }}>Recent stock movements</h2>
      <div className="card table-wrap">
        {moves.loading ? <Skeleton h={60} /> : !moves.data?.results.length ? <Empty title="No stock movements yet" /> : (
          <table className="tbl"><thead><tr><th>When</th><th>Product</th><th>Change</th><th>After</th><th>Reason</th><th>By</th></tr></thead><tbody>
            {moves.data.results.map((m) => <tr key={m.id}><td>{new Date(m.created_at).toLocaleString()}</td><td>{m.product_name}</td><td>{m.delta > 0 ? `+${m.delta}` : m.delta}</td><td>{m.quantity_after}</td><td>{m.reason}</td><td>{m.actor_email ?? '–'}</td></tr>)}
          </tbody></table>
        )}
      </div>
      {stock && <StockModal product={stock} onClose={() => setStock(null)} onSaved={() => { setStock(null); low.reload(); moves.reload() }} />}
    </>
  )
}

/* ------------------------------------------------------------------ services */
type Svc = { id: number; name: string; description: string; image: string | null; is_active: boolean }
export function ServicesAdmin() {
  useDocumentTitle('Services')
  const toast = useToast()
  const list = useAsync(() => api<Page<Svc>>('/catalog/services/'), [])
  const [edit, setEdit] = useState<Svc | 'new' | null>(null)
  const toggle = async (s: Svc) => { try { await api(`/catalog/services/${s.id}/`, { method: 'PATCH', body: { is_active: !s.is_active } }); list.reload() } catch (e) { toast(msg(e)) } }
  return (
    <>
      <div className="toolbar"><div style={{ flex: 1 }}><H>Services</H></div><button className="btn" onClick={() => setEdit('new')}><Plus size={18} aria-hidden /> Add service</button></div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading ? <Skeleton h={80} /> : !list.data?.results.length ? <Empty title="No services yet">Examples: event catering, private dining, delivery.</Empty> : (
          <table className="tbl"><thead><tr><th>Name</th><th>Status</th><th /></tr></thead><tbody>
            {list.data.results.map((s) => <tr key={s.id}><td>{s.name}</td><td><span className={`badge ${s.is_active ? 'active' : 'suspended'}`}>{s.is_active ? 'shown' : 'hidden'}</span></td>
              <td style={{ display: 'flex', gap: 6 }}><button className="btn sm secondary" onClick={() => setEdit(s)}>Edit</button><button className="btn sm secondary" onClick={() => toggle(s)}>{s.is_active ? 'Hide' : 'Show'}</button></td></tr>)}
          </tbody></table>
        )}
      </div>
      {edit && <ServiceForm initial={edit === 'new' ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload() }} />}
    </>
  )
}

function ServiceForm({ initial, onClose, onSaved }: { initial: Svc | null; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ name: initial?.name ?? '', description: initial?.description ?? '' })
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!v.name.trim()) return setErrors({ name: 'Enter the service name.' })
    setBusy(true)
    try {
      const s = await api<Svc>(initial ? `/catalog/services/${initial.id}/` : '/catalog/services/', { method: initial ? 'PATCH' : 'POST', body: v })
      if (file) { const fd = new FormData(); fd.append('image', file); await api(`/catalog/services/${s.id}/image/`, { body: fd }) }
      onSaved()
    } catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Error' }) } finally { setBusy(false) }
  }
  return (
    <Modal title={initial ? 'Edit service' : 'Add service'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && !errors.name && <div className="alert error">{errors.form}</div>}
        <Field label="Name" error={errors.name}>{(p) => <input {...p} className="input" placeholder="e.g. Wedding catering" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <Field label="Description">{(p) => <textarea {...p} className="input" rows={4} placeholder="What does this service include?" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />}</Field>
        <Field label="Image (optional)" error={errors.image}>{(p) => <input {...p} className="input" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}</Field>
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save'}</button>
      </form>
    </Modal>
  )
}

/* ------------------------------------------------------------------ gallery */
export function Gallery() {
  useDocumentTitle('Gallery')
  const toast = useToast()
  const list = useAsync(() => api<Page<{ id: number; image: string; caption: string }>>('/catalog/gallery/'), [])
  const [file, setFile] = useState<File | null>(null)
  const [caption, setCaption] = useState('')
  const [busy, setBusy] = useState(false)
  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!file) return toast('Choose an image first.')
    const fd = new FormData()
    fd.append('image', file)
    fd.append('caption', caption)
    setBusy(true)
    try { await api('/catalog/gallery/', { body: fd }); setFile(null); setCaption(''); (e.target as HTMLFormElement).reset(); list.reload() } catch (err) { toast(err instanceof ApiError ? (err.fieldErrors().image ?? err.message) : 'Upload failed.') } finally { setBusy(false) }
  }
  const remove = async (id: number) => { if (!confirm('Delete this photo?')) return; try { await api(`/catalog/gallery/${id}/`, { method: 'DELETE' }); list.reload() } catch (e) { toast(msg(e)) } }
  return (
    <>
      <H>Gallery</H>
      <form className="card toolbar" onSubmit={upload}>
        <input className="input" style={{ maxWidth: 300 }} type="file" aria-label="Photo" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <input className="input" style={{ maxWidth: 260 }} placeholder="Caption (optional)" aria-label="Caption" value={caption} onChange={(e) => setCaption(e.target.value)} />
        <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Upload photo'}</button>
      </form>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      {list.loading ? <Skeleton h={120} /> : !list.data?.results.length ? <Empty title="No photos yet" /> : (
        <div className="grid g3" style={{ marginTop: 16 }}>{list.data.results.map((g) => <figure key={g.id} className="card" style={{ margin: 0, padding: 10 }}><img src={g.image} alt={g.caption || 'Gallery photo'} loading="lazy" style={{ width: '100%', borderRadius: 8 }} /><figcaption style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 6 }}><span className="muted">{g.caption}</span><button className="btn sm danger" onClick={() => remove(g.id)}>Delete</button></figcaption></figure>)}</div>
      )}
    </>
  )
}

/* ------------------------------------------------------------------ website content */
type Content = Record<string, unknown> & { faqs: { q: string; a: string }[]; policies: Record<string, string>; policy_titles: Record<string, string> }
export function SiteContent() {
  useDocumentTitle('Website content')
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api<Content>('/catalog/site/'), [])
  const [v, setV] = useState<Record<string, string>>({})
  const [faqs, setFaqs] = useState<{ q: string; a: string }[]>([])
  const [policies, setPolicies] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!data) return
    const text = Object.fromEntries(Object.entries(data).filter(([, x]) => typeof x === 'string' || typeof x === 'number').map(([k, x]) => [k, String(x)])) as Record<string, string>
    setV(text); setFaqs(data.faqs); setPolicies(data.policies)
    setFlags({ delivery_enabled: Boolean(data.delivery_enabled), pickup_enabled: Boolean(data.pickup_enabled), online_payments_enabled: Boolean(data.online_payments_enabled), qr_guest_orders_allowed: Boolean(data.qr_guest_orders_allowed), reservations_enabled: Boolean(data.reservations_enabled), reservation_auto_confirm: Boolean(data.reservation_auto_confirm) })
  }, [data])
  const [flags, setFlags] = useState({ delivery_enabled: true, pickup_enabled: true, online_payments_enabled: false, qr_guest_orders_allowed: true, reservations_enabled: true, reservation_auto_confirm: true })
  const keys = ['email_footer', 'timezone', 'cashier_max_discount_percent', 'reservation_duration_minutes', 'reservation_max_party', 'qr_identification', 'delivery_fee', 'tax_rate_percent', 'hero_title', 'hero_subtitle', 'about_text', 'delivery_info', 'description', 'contact_email', 'contact_phone', 'address', 'city', 'country', 'primary_color', 'secondary_color', 'seo_title', 'seo_description']

  async function save(e: FormEvent) {
    e.preventDefault()
    if (faqs.some((f) => !f.q.trim() || !f.a.trim())) return setErrors({ faqs: 'Each FAQ needs a question and an answer.' })
    setBusy(true); setErrors({})
    try {
      await api('/catalog/site/', { method: 'PATCH', body: { ...Object.fromEntries(keys.map((k) => [k, v[k] ?? ''])), faqs, policies, ...flags } })
      toast('Website updated.'); reload()
    } catch (err) { setErrors(err instanceof ApiError ? { ...err.fieldErrors(), form: err.message } : { form: 'Error' }) } finally { setBusy(false) }
  }
  const f = (k: string, label: string, ph: string, area = false) => (
    <Field label={label} error={errors[k]}>{(p) => area
      ? <textarea {...p} className="input" rows={4} placeholder={ph} value={v[k] ?? ''} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
      : <input {...p} className="input" placeholder={ph} value={v[k] ?? ''} onChange={(e) => setV({ ...v, [k]: e.target.value })} />}</Field>
  )
  return (
    <>
      <H>Website content</H>
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading ? <Skeleton h={200} /> : data && (
        <form onSubmit={save} noValidate style={{ maxWidth: 720 }}>
          {errors.form && <div className="alert error" role="alert">{errors.form}</div>}
          <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.2rem' }}>Operations</h2>
            <div className="grid g2">
              {f('timezone', 'Time zone', 'e.g. Africa/Freetown')}
              {f('cashier_max_discount_percent', 'Largest discount a cashier may give (%)', 'e.g. 10')}
            </div>
            <p className="hint">Reports, “today” and reservation times follow the time zone. Discounts above the limit need a manager.</p>
            {f('email_footer', 'Line added to the bottom of every email we send for you', 'e.g. Open daily 9am to 10pm. Thank you for choosing us!')}
            <h3 style={{ marginTop: 14 }}>Reservations</h3>
            <label style={{ display: 'block' }}><input type="checkbox" checked={flags.reservations_enabled} onChange={(e) => setFlags({ ...flags, reservations_enabled: e.target.checked })} /> Accept online reservations</label>
            <label style={{ display: 'block', marginBottom: 10 }}><input type="checkbox" checked={flags.reservation_auto_confirm} onChange={(e) => setFlags({ ...flags, reservation_auto_confirm: e.target.checked })} /> Confirm bookings automatically (otherwise staff confirm each one)</label>
            <div className="grid g2">
              {f('reservation_duration_minutes', 'Length of a sitting (minutes)', '90')}
              {f('reservation_max_party', 'Largest party bookable online', '12')}
            </div>
          </div>
          <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.2rem' }}>Ordering</h2>
            <label style={{ display: 'block' }}><input type="checkbox" checked={flags.pickup_enabled} onChange={(e) => setFlags({ ...flags, pickup_enabled: e.target.checked })} /> Offer pickup</label>
            <label style={{ display: 'block', marginBottom: 12 }}><input type="checkbox" checked={flags.delivery_enabled} onChange={(e) => setFlags({ ...flags, delivery_enabled: e.target.checked })} /> Offer delivery</label>
            <label style={{ display: 'block', marginBottom: 12 }}><input type="checkbox" checked={flags.online_payments_enabled} onChange={(e) => setFlags({ ...flags, online_payments_enabled: e.target.checked })} /> Accept online mobile-money payments (needs the payment provider configured by the platform)</label>
            <label style={{ display: 'block', marginBottom: 8 }}><input type="checkbox" checked={flags.qr_guest_orders_allowed} onChange={(e) => setFlags({ ...flags, qr_guest_orders_allowed: e.target.checked })} /> Let diners send requests from table QR codes</label>
            <Field label="Ask QR diners for">{(p) => <select {...p} className="input" style={{ maxWidth: 260 }} value={v.qr_identification ?? 'none'} onChange={(e) => setV({ ...v, qr_identification: e.target.value })}><option value="none">Nothing (anonymous)</option><option value="name">Their name</option><option value="phone">Name and phone number</option></select>}</Field>
            <div className="grid g2">{f('delivery_fee', 'Delivery fee', 'e.g. 2.00')}{f('tax_rate_percent', 'Tax rate (%)', 'e.g. 8.25')}</div>
            <p className="hint">Prices on the menu are tax-exclusive; tax is added at checkout using this rate.</p></div>
          <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.2rem' }}>Home page</h2>{f('hero_title', 'Headline', 'e.g. Fresh seafood by the bay')}{f('hero_subtitle', 'Sub-headline', 'One sentence about your restaurant')}{f('about_text', 'About us', 'Tell your story', true)}{f('delivery_info', 'Delivery information', 'Areas, fees, times', true)}</div>
          <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.2rem' }}>Contact and brand</h2>{f('description', 'Short description', 'Shown in the footer and search results')}{f('contact_email', 'Contact email', 'name@example.com')}{f('contact_phone', 'Contact phone', 'Phone number')}{f('address', 'Address', 'Street address')}
            <div className="grid g2">{f('city', 'City', 'City')}{f('country', 'Country', 'Country')}</div>
            <div className="grid g2">{(['primary_color', 'secondary_color'] as const).map((k) => <Field key={k} label={k === 'primary_color' ? 'Primary color' : 'Secondary color'} error={errors[k]}>{(p) => <span style={{ display: 'flex', gap: 8 }}><input {...p} type="color" value={v[k] ?? '#000000'} onChange={(e) => setV({ ...v, [k]: e.target.value })} style={{ width: 52, height: 44 }} /><input className="input" aria-label={`${k} hex`} value={v[k] ?? ''} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></span>}</Field>)}</div></div>
          <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.2rem' }}>Search engines</h2>{f('seo_title', 'Page title', 'Up to 70 characters')}{f('seo_description', 'Description', 'Up to 160 characters')}</div>
          <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.2rem' }}>Frequently asked questions</h2>
            {faqs.map((x, i) => <div key={i} style={{ display: 'grid', gap: 6, marginBottom: 10 }}>
              <input className="input" placeholder="Question" aria-label="Question" value={x.q} onChange={(e) => setFaqs(faqs.map((y, j) => (j === i ? { ...y, q: e.target.value } : y)))} />
              <textarea className="input" rows={2} placeholder="Answer" aria-label="Answer" value={x.a} onChange={(e) => setFaqs(faqs.map((y, j) => (j === i ? { ...y, a: e.target.value } : y)))} />
              <button type="button" className="btn sm secondary" onClick={() => setFaqs(faqs.filter((_, j) => j !== i))}>Remove</button></div>)}
            {errors.faqs && <p className="err">{errors.faqs}</p>}
            <button type="button" className="btn sm secondary" onClick={() => setFaqs([...faqs, { q: '', a: '' }])}>Add question</button></div>
          <div className="card" style={{ marginBottom: 16 }}><h2 style={{ fontSize: '1.2rem' }}>Policies</h2>
            <p className="muted">Leave a box empty to show a generic default. Review the text with a legal adviser before relying on it.</p>
            {Object.entries(data.policy_titles).map(([slug, title]) => <Field key={slug} label={title} error={errors.policies}>{(p) => <textarea {...p} className="input" rows={4} placeholder="Using the generic default" value={policies[slug] ?? ''} onChange={(e) => setPolicies({ ...policies, [slug]: e.target.value })} />}</Field>)}</div>
          <button className="btn" disabled={busy}>{busy ? <Spinner /> : 'Save website content'}</button>
        </form>
      )}
    </>
  )
}

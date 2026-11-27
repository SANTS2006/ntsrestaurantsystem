import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ApiError, api, type Page } from '../../lib/api'
import { Empty, ErrorState, Field, Modal, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useConfirm } from '../../ui/dialogs'
import { LocationPicker } from '../../ui/Maps'
import { fullAddress } from '../../ui/geo'

export type Restaurant = {
  id: number; name: string; slug: string; status: 'active' | 'suspended'; logo: string | null
  primary_color: string; secondary_color: string; description: string; contact_email: string; contact_phone: string
  address: string; city: string; country: string; latitude: string | null; longitude: string | null; public_url: string
  branches_count: number; staff_count: number; customers_count: number
}

export default function Restaurants() {
  const confirm = useConfirm()
  useDocumentTitle('Restaurants')
  const toast = useToast()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<Restaurant | 'new' | null>(null)
  const list = useAsync(() => api<Page<Restaurant>>('/platform/restaurants/', { params: { q, status, page } }), [q, status, page])

  async function toggle(r: Restaurant) {
    const suspend = r.status === 'active'
    if (suspend && !(await confirm({ title: `Suspend ${r.name}?`, message: 'Its website and staff sign-in will stop working immediately.', confirmLabel: 'Suspend', danger: true }))) return
    try {
      await api(`/platform/restaurants/${r.id}/${suspend ? 'suspend' : 'activate'}/`, { body: {} })
      toast(`${r.name} ${suspend ? 'suspended' : 'activated'}.`)
      list.reload()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Action failed.')
    }
  }

  return (
    <>
      <div className="toolbar">
        <h1 style={{ fontSize: '1.7rem', margin: 0, flex: 1 }}>Restaurants</h1>
        <button className="btn" onClick={() => setEditing('new')}><Plus size={18} aria-hidden /> Register restaurant</button>
      </div>
      <div className="toolbar">
        <input className="input" style={{ maxWidth: 280 }} type="search" placeholder="Search name, slug or email" aria-label="Search restaurants" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        <select className="input" style={{ maxWidth: 180 }} aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="">All statuses</option><option value="active">Active</option><option value="suspended">Suspended</option>
        </select>
      </div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={120} /> : !list.data?.results.length ? (
          <Empty title="No restaurants found">Register your first restaurant to get started.</Empty>
        ) : (
          <table className="tbl">
            <thead><tr><th>Restaurant</th><th>Address</th><th>Status</th><th>Branches</th><th>Staff</th><th>Customers</th><th /></tr></thead>
            <tbody>
              {list.data.results.map((r) => (
                <tr key={r.id}>
                  <td><span className="swatch" style={{ background: r.primary_color, width: 14, height: 14 }} /> <strong>{r.name}</strong></td>
                  <td><a href={r.public_url} target="_blank" rel="noopener noreferrer">{r.slug}</a></td>
                  <td><span className={`badge ${r.status}`}>{r.status}</span></td>
                  <td>{r.branches_count}</td><td>{r.staff_count}</td><td>{r.customers_count}</td>
                  <td style={{ display: 'flex', gap: 6 }}>
                    <button className="btn sm secondary" onClick={() => setEditing(r)}>Edit</button>
                    <button className={`btn sm ${r.status === 'active' ? 'danger' : ''}`} onClick={() => toggle(r)}>{r.status === 'active' ? 'Suspend' : 'Activate'}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {list.data && (list.data.next || list.data.previous) && (
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button className="btn sm secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="muted">Page {page}</span>
          <button className="btn sm secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
      {editing && <RestaurantForm initial={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload() }} />}
    </>
  )
}

const empty = { name: '', slug: '', admin_full_name: '', admin_email: '', primary_color: '#0a72e0', secondary_color: '#0b3f93', description: '', contact_email: '', contact_phone: '', address: '', city: '', country: '', latitude: '', longitude: '' }

function RestaurantForm({ initial, onClose, onSaved }: { initial: Restaurant | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [v, setV] = useState<Record<string, string>>(initial ? { ...empty, ...Object.fromEntries(Object.entries(initial).map(([k, x]) => [k, x == null ? '' : String(x)])) } : empty)
  const [logo, setLogo] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local: Record<string, string> = {}
    if (!v.name.trim()) local.name = 'Enter the restaurant name.'
    if (!/^[a-z0-9]([a-z0-9-]{0,48}[a-z0-9])?$/.test(v.slug)) local.slug = 'Use lowercase letters, digits and hyphens only.'
    if (!initial) {
      if (!v.admin_full_name.trim()) local.admin_full_name = "Enter the administrator's full name."
      if (!/^\S+@\S+\.\S+$/.test(v.admin_email)) local.admin_email = 'Enter a valid email address.'
    }
    setErrors(local)
    if (Object.keys(local).length) return
    const keys = ['name', 'slug', 'primary_color', 'secondary_color', 'description', 'contact_email', 'contact_phone', 'address', 'city', 'country', 'latitude', 'longitude', ...(initial ? [] : ['admin_full_name', 'admin_email'])]
    const fd = new FormData()
    keys.forEach((k) => fd.append(k, v[k] ?? ''))
    if (logo) fd.append('logo', logo)
    setBusy(true)
    try {
      await api(initial ? `/platform/restaurants/${initial.id}/` : '/platform/restaurants/', { method: initial ? 'PATCH' : 'POST', body: fd })
      toast(initial ? 'Restaurant updated.' : 'Restaurant registered. An onboarding email was queued for the administrator.')
      onSaved()
    } catch (err) {
      if (err instanceof ApiError) setErrors({ ...err.fieldErrors(), form: err.message })
      else setErrors({ form: 'Unexpected error.' })
    } finally {
      setBusy(false)
    }
  }

  const text = (k: string, label: string, ph: string, extra: { type?: string; hint?: string } = {}) => (
    <Field label={label} error={errors[k]} hint={extra.hint}>
      {(p) => <input {...p} className="input" type={extra.type ?? 'text'} placeholder={ph} value={v[k]} onChange={set(k)} />}
    </Field>
  )

  return (
    <Modal title={initial ? `Edit ${initial.name}` : 'Register restaurant'} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {errors.form && !Object.keys(errors).some((k) => k !== 'form') && <div className="alert error" role="alert">{errors.form}</div>}
        {text('name', 'Restaurant name', 'Enter the restaurant name')}
        {text('slug', 'Website address (slug)', 'e.g. ocean-view', { hint: 'The restaurant’s website is at your platform address followed by /slug. Must be unique.' })}
        {!initial && <>
          {text('admin_full_name', 'Administrator full name', 'Enter the administrator’s full name')}
          {text('admin_email', 'Administrator email', 'Enter the administrator’s email address', { type: 'email', hint: 'A secure password-setup link is sent here.' })}
        </>}
        <div className="grid g2">
          {(['primary_color', 'secondary_color'] as const).map((k) => (
            <Field key={k} label={k === 'primary_color' ? 'Primary color' : 'Secondary color'} error={errors[k]}>
              {(p) => <span style={{ display: 'flex', gap: 8 }}><input {...p} type="color" value={v[k]} onChange={set(k)} style={{ width: 52, height: 44 }} /><input className="input" aria-label={`${k} hex`} value={v[k]} onChange={set(k)} /></span>}
            </Field>
          ))}
        </div>
        <div className="card" aria-label="Brand preview" style={{ marginBottom: 14, padding: 0, overflow: 'hidden' }}>
          <div style={{ background: v.primary_color, color: '#fff', padding: '10px 16px', fontWeight: 700 }}>{v.name || 'Your restaurant'}</div>
          <div style={{ padding: 16 }}><span className="btn sm" style={{ background: v.secondary_color }}>Order now</span> <span className="muted">Live preview</span></div>
        </div>
        <Field label="Logo (PNG, JPEG or WebP, max 2 MB)" error={errors.logo}>
          {(p) => <input {...p} className="input" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setLogo(e.target.files?.[0] ?? null)} />}
        </Field>
        <Field label="Description" error={errors.description}>
          {(p) => <textarea {...p} className="input" rows={3} placeholder="Tell customers about the restaurant" value={v.description} onChange={set('description')} />}
        </Field>
        {text('contact_email', 'Contact email', 'Enter the contact email', { type: 'email' })}
        {text('contact_phone', 'Contact phone', 'Enter the contact phone number')}
        {text('address', 'Address (optional)', 'Enter the street address')}
        <div className="grid g2">{text('city', 'City', 'City')}{text('country', 'Country', 'Country')}</div>
        <LocationPicker address={v.address ? fullAddress(v.address, v.city, v.country) : ''} value={{ latitude: v.latitude, longitude: v.longitude }} onChange={(pin) => setV((now) => ({ ...now, ...pin }))} error={errors.latitude} />
        <button className="btn" disabled={busy} style={{ width: '100%' }}>{busy ? <Spinner /> : initial ? 'Save changes' : 'Register restaurant'}</button>
      </form>
    </Modal>
  )
}

import { ArrowDown, ArrowUp, ExternalLink, ImagePlus, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, api } from '../../lib/api'
import { ErrorState, Field, PageHeader, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useConfirm } from '../../ui/dialogs'
import { LocationPicker } from '../../ui/Maps'
import { RichField } from '../../ui/RichText'
import type { SiteTexts } from '../site/content'
import { legal as legalPages } from '../site/SiteLayout'

type Loaded = { content: SiteTexts; changed: Record<string, string[]>; images: Record<string, string>; slots: string[]; updated_at: string; updated_by: string | null }
type Row = Record<string, string>
type Spec =
  | { key: string; label: string; area?: number; plain?: boolean; hint?: string }
  | { key: string; label: string; list: { key: string; label: string; area?: number }[]; add: string; pins?: boolean; hint?: string }
type Section = keyof SiteTexts

const titled = (area = 3) => [{ key: 'title', label: 'Title' }, { key: 'text', label: 'Text', area }]
const heading: Spec[] = [{ key: 'eyebrow', label: 'Small label above the title' }, { key: 'title', label: 'Page title' }, { key: 'lead', label: 'Introduction under the title', area: 3 }]

const PAGES: { id: Section; label: string; path?: string; fields: Spec[] }[] = [
  { id: 'home', label: 'Home page', path: '/', fields: [
    { key: 'pill', label: 'Small label above the headline' }, { key: 'title', label: 'Headline' }, { key: 'title_highlight', label: 'Highlighted end of the headline' },
    { key: 'lead', label: 'Introduction', area: 3 }, { key: 'primary_button', label: 'Main button' }, { key: 'secondary_button', label: 'Second button' },
    { key: 'perks', label: 'Short points under the buttons', add: 'Add point', list: [{ key: 'text', label: 'Point' }] },
    { key: 'features_eyebrow', label: 'Features: small label' }, { key: 'features_title', label: 'Features: title' }, { key: 'features_text', label: 'Features: text', area: 2 },
    { key: 'steps_eyebrow', label: 'Steps: small label' }, { key: 'steps_title', label: 'Steps: title' },
    { key: 'steps', label: 'Steps', add: 'Add step', list: titled() },
    { key: 'security_title', label: 'Security: title' }, { key: 'security_text', label: 'Security: text', area: 3 },
    { key: 'pricing_title', label: 'Pricing block title' }, { key: 'cta_title', label: 'Closing banner: title' }, { key: 'cta_text', label: 'Closing banner: text', area: 2 },
  ] },
  { id: 'features', label: 'Features', path: '/features', fields: [...heading, { key: 'items', label: 'Features (also shown on the home page)', add: 'Add feature', list: titled() }] },
  { id: 'pricing', label: 'Pricing', path: '/pricing', fields: [...heading, { key: 'note', label: 'Note under the plans', area: 2, hint: 'The plans themselves are managed under Plans.' }] },
  { id: 'about', label: 'About', path: '/about', fields: [...heading, { key: 'sections', label: 'Sections of the page', add: 'Add section', list: titled(6) }] },
  { id: 'faq', label: 'FAQ', path: '/faq', fields: [...heading, { key: 'items', label: 'Questions and answers', add: 'Add question', list: [{ key: 'q', label: 'Question' }, { key: 'a', label: 'Answer', area: 4 }] }] },
  { id: 'contact', label: 'Contact and locations', path: '/contact', fields: [...heading, { key: 'form_title', label: 'Title of the contact form' },
    { key: 'phone', label: 'Phone number shown on the website', plain: true, hint: 'The support email and WhatsApp number are under Settings.' },
    { key: 'hours', label: 'Opening hours', area: 2 },
    { key: 'locations', label: 'Office locations (shown with a map and directions)', add: 'Add location', pins: true,
      list: [{ key: 'name', label: 'Name' }, { key: 'address', label: 'Address' }, { key: 'phone', label: 'Phone' }, { key: 'hours', label: 'Hours' }] }] },
  { id: 'footer', label: 'Footer', fields: [{ key: 'about', label: 'Short description under the logo', area: 3 }, { key: 'cta_title', label: 'Banner title' }, { key: 'cta_text', label: 'Banner text', area: 2 }, { key: 'cta_button', label: 'Banner button' }] },
]
const SLOT_LABEL: Record<string, string> = { home: 'Home page', features: 'Features', pricing: 'Pricing', about: 'About', faq: 'FAQ', contact: 'Contact', legal: 'Legal pages' }
const TABS = [...PAGES.map((p) => [p.id as string, p.label]), ['legal', 'Legal pages'], ['seo', 'Search engines'], ['images', 'Page pictures']]

const explain = (e: unknown) => (e instanceof ApiError ? Object.entries(e.fieldErrors()).map(([k, v]) => `${k.split('.').pop()?.replace(/_/g, ' ')}: ${v}`)[0] ?? e.message : 'Could not save. Please try again.')

/** Platform owner's editor for every page of the main website. */
export default function WebsiteContent() {
  useDocumentTitle('Website content')
  const loaded = useAsync(() => api<Loaded>('/website/content/'), [])
  const [data, setData] = useState<Loaded | null>(null)
  const [tab, setTab] = useState('home')
  const [drafts, setDrafts] = useState<Partial<SiteTexts>>({})
  // the screen refreshes itself every few seconds: take the first copy only, so typing is never overwritten
  useEffect(() => { if (loaded.data) setData((now) => now ?? loaded.data) }, [loaded.data])

  const saved = (next: Loaded, section: string) => { setData(next); setDrafts((d) => { const rest = { ...d }; delete rest[section as Section]; return rest }) }
  const page = PAGES.find((p) => p.id === tab)

  return (
    <>
      <PageHeader title="Website content" subtitle="Everything on the main website. Select words and press Bold (Ctrl+B) to show them in bold.">
        <a className="btn sm secondary" href={page?.path ?? '/'} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} aria-hidden /> View page</a>
      </PageHeader>
      {loaded.error && !data && <ErrorState message={loaded.error} onRetry={loaded.reload} />}
      <div className="chips" role="tablist" aria-label="Part of the website" style={{ marginBottom: 14 }}>
        {TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} aria-pressed={tab === id} className="chip" onClick={() => setTab(id)}>{label}{drafts[id as Section] ? ' •' : ''}</button>)}
      </div>
      {!data ? !loaded.error && <Skeleton h={320} /> : (
        <>
          {data.updated_by && <p className="hint">Last saved by {data.updated_by} on {new Date(data.updated_at).toLocaleString()}.</p>}
          {tab === 'images' ? <Pictures data={data} onChange={(images) => setData({ ...data, images })} />
            : (
              <SectionEditor key={tab} section={tab as Section} spec={page?.fields}
                value={(drafts[tab as Section] ?? data.content[tab as Section]) as unknown as Record<string, unknown>}
                dirty={!!drafts[tab as Section]} edited={!!data.changed[tab]}
                onChange={(v) => setDrafts((d) => ({ ...d, [tab]: v }))} onSaved={(next) => saved(next, tab)} />
            )}
        </>
      )}
    </>
  )
}

function SectionEditor({ section, spec, value, dirty, edited, onChange, onSaved }: {
  section: Section; spec?: Spec[]; value: Record<string, unknown>; dirty: boolean; edited: boolean; onChange: (v: Record<string, unknown>) => void; onSaved: (d: Loaded) => void
}) {
  const toast = useToast()
  const confirm = useConfirm()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v })

  async function send(body: unknown, done: string) {
    setBusy(true); setError('')
    try { onSaved(await api<Loaded>('/website/content/', { method: 'PATCH', body: { [section]: body } })); toast(done) }
    catch (e) { setError(explain(e)) } finally { setBusy(false) }
  }
  function save(e: FormEvent) { e.preventDefault(); void send(value, 'Saved. The website shows your changes now.') }
  async function restore() {
    if (await confirm({ title: 'Restore the built-in texts?', message: 'Your changes to this part of the website are removed.', confirmLabel: 'Restore', danger: true })) await send(null, 'Built-in texts restored.')
  }

  return (
    <form onSubmit={save} noValidate>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="card content-editor">
        {section === 'legal' ? <LegalEditor value={value as SiteTexts['legal']} onChange={onChange} />
          : section === 'seo' ? <SeoEditor value={value as unknown as SiteTexts['seo']} onChange={onChange} />
          : spec?.map((f) => 'list' in f ? (
            <ListEditor key={f.key} spec={f} rows={(value[f.key] as Row[]) ?? []} onChange={(rows) => set(f.key, rows)} />
          ) : f.plain ? (
            <Field key={f.key} label={f.label} hint={f.hint}>{(p) => <input {...p} className="input" placeholder={`Enter ${f.label.toLowerCase()}`} value={String(value[f.key] ?? '')} onChange={(e) => set(f.key, e.target.value)} />}</Field>
          ) : (
            <RichField key={f.key} label={f.label} hint={f.hint} rows={f.area} value={String(value[f.key] ?? '')} onChange={(v) => set(f.key, v)} />
          ))}
      </div>
      <div className="save-bar">
        <button className="btn" disabled={busy || !dirty}>{busy ? <Spinner /> : 'Save changes'}</button>
        {edited && <button type="button" className="btn secondary" disabled={busy} onClick={() => void restore()}><RotateCcw size={15} aria-hidden /> Restore built-in texts</button>}
        <span className="muted">{dirty ? 'You have unsaved changes.' : 'Everything here is saved.'}</span>
      </div>
    </form>
  )
}

function ListEditor({ spec, rows, onChange }: { spec: Extract<Spec, { list: unknown }>; rows: Row[]; onChange: (rows: Row[]) => void }) {
  const blank = () => ({ ...Object.fromEntries(spec.list.map((f) => [f.key, ''])), ...(spec.pins ? { latitude: '', longitude: '' } : {}) })
  const update = (i: number, patch: Row) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const move = (i: number, by: number) => { const next = [...rows]; const [row] = next.splice(i, 1); next.splice(i + by, 0, row); onChange(next) }
  return (
    <fieldset className="list-editor">
      <legend>{spec.label}</legend>
      {rows.map((r, i) => (
        <div className="list-item" key={i}>
          <div className="list-item-bar">
            <b>#{i + 1}</b>
            <button type="button" className="icon-btn" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move entry ${i + 1} up`}><ArrowUp size={15} aria-hidden /></button>
            <button type="button" className="icon-btn" disabled={i === rows.length - 1} onClick={() => move(i, 1)} aria-label={`Move entry ${i + 1} down`}><ArrowDown size={15} aria-hidden /></button>
            <button type="button" className="icon-btn" onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label={`Remove entry ${i + 1}`}><Trash2 size={15} aria-hidden /></button>
          </div>
          {spec.list.map((f) => spec.pins
            ? <Field key={f.key} label={f.label}>{(p) => <input {...p} className="input" placeholder={`Enter the ${f.label.toLowerCase()}`} value={r[f.key] ?? ''} onChange={(e) => update(i, { [f.key]: e.target.value })} />}</Field>
            : <RichField key={f.key} label={f.label} rows={f.area} value={r[f.key] ?? ''} onChange={(v) => update(i, { [f.key]: v })} />)}
          {spec.pins && <LocationPicker address={r.address ?? ''} value={{ latitude: r.latitude ?? '', longitude: r.longitude ?? '' }} onChange={(pin) => update(i, pin)} />}
        </div>
      ))}
      {!rows.length && <p className="muted">Nothing here yet.</p>}
      <button type="button" className="btn sm secondary" onClick={() => onChange([...rows, blank()])}><Plus size={15} aria-hidden /> {spec.add}</button>
    </fieldset>
  )
}

function LegalEditor({ value, onChange }: { value: SiteTexts['legal']; onChange: (v: Record<string, unknown>) => void }) {
  const [slug, setSlug] = useState<string>(legalPages[0][0])
  return (
    <>
      <div className="alert warn">The built-in legal texts are drafts with placeholders in [square brackets]. Replace them and have them reviewed by qualified legal counsel.</div>
      <Field label="Legal page">{(p) => <select {...p} className="input" value={slug} onChange={(e) => setSlug(e.target.value)}>{legalPages.map(([s, l]) => <option key={s} value={s}>{l}</option>)}</select>}</Field>
      <ListEditor key={slug} spec={{ key: slug, label: 'Sections of this page', add: 'Add section', list: titled(5) }} rows={(value[slug] ?? []) as unknown as Row[]} onChange={(rows) => onChange({ ...value, [slug]: rows })} />
      <p className="hint">Removing every section brings back the built-in draft.</p>
    </>
  )
}

function SeoEditor({ value, onChange }: { value: SiteTexts['seo']; onChange: (v: Record<string, unknown>) => void }) {
  return (
    <>
      <p className="muted">The title and description search engines and link previews show for each page.</p>
      {Object.entries(value).map(([page, entry]) => (
        <fieldset className="list-editor" key={page}>
          <legend>{SLOT_LABEL[page] ?? page}</legend>
          <Field label="Search title" hint="Up to 70 characters.">{(p) => <input {...p} className="input" maxLength={70} placeholder="Enter the search title" value={entry.title} onChange={(e) => onChange({ ...value, [page]: { ...entry, title: e.target.value } })} />}</Field>
          <Field label="Search description" hint="Up to 200 characters.">{(p) => <textarea {...p} className="input" rows={2} maxLength={200} placeholder="Enter the search description" value={entry.text} onChange={(e) => onChange({ ...value, [page]: { ...entry, text: e.target.value } })} />}</Field>
        </fieldset>
      ))}
    </>
  )
}

function Pictures({ data, onChange }: { data: Loaded; onChange: (images: Record<string, string>) => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState('')
  async function send(slot: string, file: File | null) {
    setBusy(slot)
    try {
      const body = file ? new FormData() : undefined
      if (file) body!.append('image', file)
      const r = await api<{ images: Record<string, string> }>(`/website/content/images/${slot}/`, file ? { method: 'POST', body } : { method: 'DELETE' })
      onChange(r.images)
      toast(file ? 'Picture saved.' : 'Picture removed.')
    } catch (e) { toast(explain(e)) } finally { setBusy('') }
  }
  return (
    <>
      <p className="muted">The picture behind each page’s heading. PNG, JPEG or WebP, up to 4 MB. A wide photo (about 1600 × 700) works best.</p>
      <div className="grid g3">
        {data.slots.map((slot) => (
          <div className="card picture-slot" key={slot}>
            <h3>{SLOT_LABEL[slot] ?? slot}</h3>
            {data.images[slot] ? <img src={data.images[slot]} alt={`Current picture for ${SLOT_LABEL[slot]}`} /> : <div className="picture-empty"><ImagePlus aria-hidden /> No picture</div>}
            <label className="btn sm secondary">{busy === slot ? <Spinner /> : data.images[slot] ? 'Change picture' : 'Upload picture'}
              <input type="file" className="visually-hidden" accept="image/png,image/jpeg,image/webp" disabled={!!busy} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void send(slot, f) }} />
            </label>
            {data.images[slot] && <button className="btn sm ghost" disabled={!!busy} onClick={() => void send(slot, null)}>Remove</button>}
          </div>
        ))}
      </div>
    </>
  )
}

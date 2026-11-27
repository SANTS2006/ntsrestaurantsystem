// The page builder, used by the platform administrator (main website) and by restaurant administrators (their website).
import { ArrowDown, ArrowUp, Copy, ExternalLink, Eye, EyeOff, ImagePlus, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError, api } from '../../lib/api'
import { TENANT_BASE } from '../../lib/config'
import { ErrorState, Field, PageHeader, Skeleton, Spinner, useAsync, useDocumentTitle, useToast } from '../kit'
import { useConfirm } from '../dialogs'
import { RichField } from '../RichText'
import { BlockView } from './PageDesign'
import { LAYOUTS, MODEL_NAMES, emptyHero, emptyItem, newBlock, type Block, type Design, type Item, type Layout, type Pictured } from './types'

type Loaded = { pages: { id: string; label: string }[]; designs: Record<string, Design> }
const msg = (e: unknown) => (e instanceof ApiError ? (Object.values(e.fieldErrors())[0] ?? e.message) : 'That did not work. Please try again.')

function Picture({ value, onChange, label = 'Picture' }: { value: Pictured; onChange: (p: Pictured) => void; label?: string }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  async function upload(file: File) {
    setBusy(true)
    try {
      const body = new FormData()
      body.append('image', file)
      const r = await api<{ id: number; url: string }>('/website/builder/images/', { method: 'POST', body })
      onChange({ image: r.id, image_url: r.url })
    } catch (e) { toast(msg(e)) } finally { setBusy(false) }
  }
  return (
    <div className="pbe-picture">
      {value.image_url && <img src={value.image_url} alt="" />}
      <label className="btn sm secondary">{busy ? <Spinner /> : <><ImagePlus size={15} aria-hidden /> {value.image ? 'Change' : 'Add'} {label.toLowerCase()}</>}
        <input type="file" className="visually-hidden" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void upload(f) }} />
      </label>
      {value.image && <button type="button" className="btn sm ghost" onClick={() => onChange({ image: null, image_url: null })}><X size={14} aria-hidden /> Remove</button>}
    </div>
  )
}

function Select<T extends string | number>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return <Field label={label}>{(p) => <select {...p} className="input" value={value} onChange={(e) => onChange(options.find(([v]) => String(v) === e.target.value)![0])}>{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
}

function Button({ value, onChange }: { value: { button_label: string; button_link: string }; onChange: (p: { button_label?: string; button_link?: string }) => void }) {
  return (
    <div className="form-2">
      <Field label="Button text (optional)">{(p) => <input {...p} className="input" maxLength={40} placeholder="Enter the button text" value={value.button_label} onChange={(e) => onChange({ button_label: e.target.value })} />}</Field>
      <Field label="Button goes to" hint="A page such as /menu or /contact, or an https, tel: or mailto: link.">{(p) => <input {...p} className="input" maxLength={300} placeholder="Enter the link" value={value.button_link} onChange={(e) => onChange({ button_link: e.target.value })} />}</Field>
    </div>
  )
}

function BlockEditor({ block, onChange }: { block: Block; onChange: (patch: Partial<Block>) => void }) {
  const info = LAYOUTS.find((l) => l.id === block.layout)!
  const visual = block.layout === 'split' || block.layout === 'banner'
  const item = (i: number, patch: Partial<Item>) => onChange({ items: block.items.map((x, j) => (j === i ? { ...x, ...patch } : x)) })
  const moveItem = (i: number, by: number) => { const next = [...block.items]; const [row] = next.splice(i, 1); next.splice(i + by, 0, row); onChange({ items: next }) }
  return (
    <>
      <div className="form-2">
        <Select<Layout> label="Show as" value={block.layout} options={LAYOUTS.map((l) => [l.id, l.label])} onChange={(layout) => onChange({ layout, items: !block.items.length && LAYOUTS.find((l) => l.id === layout)!.items ? [emptyItem()] : block.items })} />
        <Select label="Where on the page" value={block.placement} options={[['top', 'Under the heading'], ['bottom', 'Above the footer']]} onChange={(placement) => onChange({ placement })} />
        <Select label="Background" value={block.background} options={[['plain', 'Plain'], ['soft', 'Soft tint'], ['brand', 'Brand colour'], ['dark', 'Dark']]} onChange={(background) => onChange({ background })} />
        <Select label="Entrance animation" value={block.animation} options={[['rise', 'Rise up'], ['zoom', 'Zoom in'], ['left', 'From the left'], ['right', block.layout === 'split' ? 'From the right (picture first)' : 'From the right'], ['flip', '3D flip'], ['none', 'None']]} onChange={(animation) => onChange({ animation })} />
        {block.layout === 'cards' && <Select<2 | 3 | 4> label="Cards per row" value={block.columns} options={[[2, '2'], [3, '3'], [4, '4']]} onChange={(columns) => onChange({ columns })} />}
        {visual && <Select<Block['model']> label="3D model" value={block.model} options={MODEL_NAMES.filter(([v]) => v !== 'auto') as [Block['model'], string][]} onChange={(model) => onChange({ model })} />}
      </div>
      <p className="hint">{info.hint}</p>
      {block.layout === 'carousel' && <label className="consent"><input type="checkbox" checked={block.autoplay} onChange={(e) => onChange({ autoplay: e.target.checked })} /> <span>Move to the next slide every 5 seconds</span></label>}
      <RichField label="Small label above the title" value={block.eyebrow} maxLength={80} onChange={(eyebrow) => onChange({ eyebrow })} />
      <RichField label="Section title" value={block.title} maxLength={150} onChange={(title) => onChange({ title })} />
      <RichField label="Section text" rows={3} value={block.text} maxLength={4000} onChange={(text) => onChange({ text })} />
      {visual && block.model === 'none' && <Picture value={block} onChange={(p) => onChange(p)} />}
      {!info.items && <Button value={block} onChange={(p) => onChange(p)} />}
      {info.items && (
        <fieldset className="list-editor">
          <legend>{block.layout === 'gallery' ? 'Pictures' : block.layout === 'carousel' ? 'Slides' : block.layout === 'accordion' ? 'Accordion entries' : 'Cards'}</legend>
          {block.items.map((x, i) => (
            <div className="list-item" key={i}>
              <div className="list-item-bar">
                <b>#{i + 1}</b>
                <button type="button" className="icon-btn" disabled={i === 0} onClick={() => moveItem(i, -1)} aria-label={`Move entry ${i + 1} up`}><ArrowUp size={15} aria-hidden /></button>
                <button type="button" className="icon-btn" disabled={i === block.items.length - 1} onClick={() => moveItem(i, 1)} aria-label={`Move entry ${i + 1} down`}><ArrowDown size={15} aria-hidden /></button>
                <button type="button" className="icon-btn" onClick={() => onChange({ items: block.items.filter((_, j) => j !== i) })} aria-label={`Remove entry ${i + 1}`}><Trash2 size={15} aria-hidden /></button>
              </div>
              <Picture value={x} onChange={(p) => item(i, p)} />
              <RichField label={block.layout === 'gallery' ? 'Caption' : 'Title'} value={x.title} maxLength={150} onChange={(title) => item(i, { title })} />
              {block.layout !== 'gallery' && <><RichField label="Text" rows={3} value={x.text} maxLength={3000} onChange={(text) => item(i, { text })} /><Button value={x} onChange={(p) => item(i, p)} /></>}
            </div>
          ))}
          <button type="button" className="btn sm secondary" disabled={block.items.length >= 24} onClick={() => onChange({ items: [...block.items, emptyItem()] })}><Plus size={15} aria-hidden /> Add {block.layout === 'gallery' ? 'picture' : 'entry'}</button>
        </fieldset>
      )}
    </>
  )
}

export default function PageBuilder() {
  useDocumentTitle('Page builder')
  const toast = useToast()
  const confirm = useConfirm()
  const loaded = useAsync(() => api<Loaded>('/website/builder/'), [])
  const [data, setData] = useState<Loaded | null>(null)
  useEffect(() => { if (loaded.data) setData((now) => now ?? loaded.data) }, [loaded.data]) // the screen refreshes itself: never overwrite typing
  const [page, setPage] = useState('home')
  const [drafts, setDrafts] = useState<Record<string, Design>>({})
  const [open, setOpen] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const saved = data?.designs[page]
  const design: Design = drafts[page] ?? { hero: { ...emptyHero(), ...saved?.hero }, blocks: saved?.blocks ?? [] }
  const change = (next: Design) => setDrafts((d) => ({ ...d, [page]: next }))
  const setBlocks = (blocks: Block[]) => change({ ...design, blocks })
  const move = (i: number, by: number) => { const next = [...design.blocks]; const [row] = next.splice(i, 1); next.splice(i + by, 0, row); setBlocks(next); setOpen(open === i ? i + by : null) }
  const add = (layout: Layout) => { setBlocks([...design.blocks, newBlock(layout)]); setOpen(design.blocks.length); setAdding(false) }
  const path = page === 'home' ? '/' : page === 'legal' ? '/legal/privacy-policy' : `/${page}`

  async function save() {
    setBusy(true); setError('')
    try {
      const next = await api<Design>(`/website/builder/pages/${page}/`, { method: 'PUT', body: design })
      setData((d) => (d ? { ...d, designs: { ...d.designs, [page]: next } } : d))
      setDrafts((d) => { const rest = { ...d }; delete rest[page]; return rest })
      toast('Saved. The website shows your changes now.')
    } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }
  async function remove(i: number) {
    if (await confirm({ title: 'Delete this section?', message: 'It disappears from the website when you save.', confirmLabel: 'Delete', danger: true })) { setBlocks(design.blocks.filter((_, j) => j !== i)); setOpen(null) }
  }

  return (
    <>
      <PageHeader title="Page builder" subtitle="Design each page: its heading, 3D model and sections shown as cards, carousels, accordions, galleries and more.">
        <a className="btn sm secondary" href={`${TENANT_BASE}${path}`} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} aria-hidden /> View page</a>
      </PageHeader>
      {loaded.error && !data && <ErrorState message={loaded.error} onRetry={loaded.reload} />}
      {!data ? !loaded.error && <Skeleton h={320} /> : (
        <>
          <div className="chips" role="tablist" aria-label="Page" style={{ marginBottom: 14 }}>
            {data.pages.map((p) => <button key={p.id} role="tab" aria-selected={page === p.id} aria-pressed={page === p.id} className="chip" onClick={() => { setPage(p.id); setOpen(null); setAdding(false); setError('') }}>{p.label}{drafts[p.id] ? ' •' : ''}</button>)}
          </div>
          {error && <div className="alert error" role="alert">{error}</div>}

          <details className="card pbe-hero">
            <summary><b>Page heading (hero)</b> <span className="muted">Leave a box empty to keep the built-in words.</span></summary>
            <div className="form-2">
              <Select label="3D model" value={design.hero.model} options={MODEL_NAMES} onChange={(model) => change({ ...design, hero: { ...design.hero, model } })} />
              <Picture label="Background picture" value={design.hero} onChange={(p) => change({ ...design, hero: { ...design.hero, ...p } })} />
            </div>
            <RichField label="Small label" value={design.hero.eyebrow} maxLength={80} onChange={(eyebrow) => change({ ...design, hero: { ...design.hero, eyebrow } })} />
            <RichField label="Heading" value={design.hero.title} maxLength={120} onChange={(title) => change({ ...design, hero: { ...design.hero, title } })} />
            <RichField label="Introduction" rows={2} value={design.hero.lead} maxLength={400} onChange={(lead) => change({ ...design, hero: { ...design.hero, lead } })} />
            {page !== 'home' && <Button value={design.hero} onChange={(p) => change({ ...design, hero: { ...design.hero, ...p } })} />}
          </details>

          <h2 className="pbe-title">Sections on this page</h2>
          {!design.blocks.length && <p className="muted">No sections yet. The built-in page is shown as it is; add sections to build on it.</p>}
          {design.blocks.map((b, i) => (
            <article className={`card pbe-block ${b.visible ? '' : 'hidden-block'}`} key={i}>
              <header>
                <button type="button" className="pbe-name" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
                  <b>{i + 1}. {LAYOUTS.find((l) => l.id === b.layout)?.label}</b><span className="muted">{b.title || 'Untitled'} · {b.placement === 'top' ? 'under the heading' : 'above the footer'}{b.visible ? '' : ' · hidden'}</span>
                </button>
                <span className="pbe-tools">
                  <button type="button" className="icon-btn" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move section ${i + 1} up`}><ArrowUp size={15} aria-hidden /></button>
                  <button type="button" className="icon-btn" disabled={i === design.blocks.length - 1} onClick={() => move(i, 1)} aria-label={`Move section ${i + 1} down`}><ArrowDown size={15} aria-hidden /></button>
                  <button type="button" className="icon-btn" onClick={() => setBlocks(design.blocks.map((x, j) => (j === i ? { ...x, visible: !x.visible } : x)))} aria-label={b.visible ? `Hide section ${i + 1}` : `Show section ${i + 1}`}>{b.visible ? <Eye size={15} aria-hidden /> : <EyeOff size={15} aria-hidden />}</button>
                  <button type="button" className="icon-btn" disabled={design.blocks.length >= 20} onClick={() => { setBlocks([...design.blocks.slice(0, i + 1), structuredClone(b), ...design.blocks.slice(i + 1)]); setOpen(i + 1) }} aria-label={`Copy section ${i + 1}`}><Copy size={15} aria-hidden /></button>
                  <button type="button" className="icon-btn" onClick={() => void remove(i)} aria-label={`Delete section ${i + 1}`}><Trash2 size={15} aria-hidden /></button>
                </span>
              </header>
              {open === i && (
                <div className="pbe-body">
                  <BlockEditor block={b} onChange={(patch) => setBlocks(design.blocks.map((x, j) => (j === i ? { ...x, ...patch } : x)))} />
                  <p className="pbe-preview-label">Preview</p>
                  {/* links in the preview are switched off so editing is not lost by a click */}
                  <div className="pbe-preview" onClickCapture={(e) => { if ((e.target as HTMLElement).closest('a')) e.preventDefault() }}><BlockView block={{ ...b, animation: 'none', autoplay: false }} /></div>
                </div>
              )}
            </article>
          ))}
          {adding ? (
            <div className="pbe-choices">
              {LAYOUTS.map((l) => <button type="button" key={l.id} onClick={() => add(l.id)}><b>{l.label}</b><small>{l.hint}</small></button>)}
              <button type="button" className="cancel" onClick={() => setAdding(false)}>Cancel</button>
            </div>
          ) : <button type="button" className="btn secondary" disabled={design.blocks.length >= 20} onClick={() => setAdding(true)}><Plus size={16} aria-hidden /> Add a section</button>}
          <div className="save-bar">
            <button className="btn" disabled={busy || !drafts[page]} onClick={() => void save()}>{busy ? <Spinner /> : 'Save this page'}</button>
            <span className="muted">{drafts[page] ? 'You have unsaved changes.' : 'This page is saved.'}</span>
          </div>
        </>
      )}
    </>
  )
}

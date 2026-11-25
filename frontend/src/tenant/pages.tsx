import { Clock, Mail, MapPin, Phone, Search, Truck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { Empty, ErrorState, Reveal, Skeleton, useAsync } from '../ui/kit'
import { useSeo } from './seo'
import { ProductBuy } from './shop'
import { useSite, type MenuCategory, type PublicProduct } from './SiteContext'

const A = { auth: false } as const

function useMenu(params: Record<string, string> = {}) {
  const key = JSON.stringify(params)
  return useAsync(() => api<MenuCategory[]>('/catalog/public/menu/', { params, ...A }), [key])
}

export function ProductCard({ p }: { p: PublicProduct }) {
  const { money } = useSite()
  return (
    <Link to={`/menu/${p.slug}`} className="card lift product-card" style={{ textDecoration: 'none', color: 'inherit', padding: 0, overflow: 'hidden', display: 'block' }}>
      {p.image ? <img src={p.image} alt={`${p.name}`} loading="lazy" width={400} height={240} style={{ width: '100%', height: 170, objectFit: 'cover', display: 'block' }} />
        : <div style={{ height: 170, background: 'var(--bg-soft)', display: 'grid', placeItems: 'center' }} aria-hidden>🍽️</div>}
      <div style={{ padding: 16 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
          {p.on_offer && <span className="badge" style={{ color: 'var(--brand)' }}>{p.offer_label || 'Special offer'}</span>}
          {p.is_featured && <span className="badge">Featured</span>}
          {p.is_popular && <span className="badge">Popular</span>}
          {p.sold_out && <span className="badge suspended">Sold out</span>}
        </div>
        <h3 style={{ marginBottom: 4 }}>{p.name}</h3>
        <p className="muted" style={{ fontSize: '.9rem', marginBottom: 8, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{p.description}</p>
        <strong>{money(p.price)}</strong>{p.on_offer && <s className="muted" style={{ marginLeft: 8 }}>{money(p.regular_price)}</s>}
      </div>
    </Link>
  )
}

function Grid({ items }: { items: PublicProduct[] }) {
  return <div className="grid g3">{items.map((p) => <Reveal key={p.id}><ProductCard p={p} /></Reveal>)}</div>
}

function Hours({ hours }: { hours: Record<string, string> }) {
  const e = Object.entries(hours ?? {})
  return e.length ? <ul style={{ listStyle: 'none', padding: 0, margin: '6px 0' }}>{e.map(([d, t]) => <li key={d}><b style={{ textTransform: 'capitalize' }}>{d}</b>: {t}</li>)}</ul> : null
}

export function Home() {
  const { site } = useSite()
  const r = site.restaurant
  const menu = useMenu()
  const all = useMemo(() => (menu.data ?? []).flatMap((c) => c.products), [menu.data])
  const featured = all.filter((p) => p.is_featured).slice(0, 6)
  const popular = all.filter((p) => p.is_popular && !p.is_featured).slice(0, 6)
  const offers = all.filter((p) => p.on_offer).slice(0, 6)
  const services = useAsync(() => api<{ slug: string; name: string; description: string }[]>('/catalog/public/services/', A), [])
  useSeo({
    title: site.seo_title, description: site.seo_description, image: r.logo, path: '/',
    jsonLd: {
      '@context': 'https://schema.org', '@type': 'Restaurant', name: r.name, description: r.description, url: site.url, image: r.logo ?? undefined,
      telephone: r.contact_phone || undefined, email: r.contact_email || undefined, hasMenu: `${site.url}/menu`,
      address: r.address || r.city ? { '@type': 'PostalAddress', streetAddress: r.address, addressLocality: r.city, addressCountry: r.country } : undefined,
    },
  })
  return (
    <>
      <section className="hero" style={{ background: `linear-gradient(135deg, color-mix(in srgb, var(--brand) 18%, var(--bg)), var(--bg))` }}>
        <div className="container">
          <p className="eyebrow">{r.city || 'Welcome'}</p>
          <h1>{site.hero_title}</h1>
          <p className="muted" style={{ fontSize: '1.15rem', maxWidth: 640 }}>{site.hero_subtitle}</p>
          <Link className="btn" to="/menu">View the menu</Link>
        </div>
      </section>
      {menu.loading ? <div className="container section"><Skeleton h={200} /></div> : menu.error ? <div className="container section"><ErrorState message={menu.error} onRetry={menu.reload} /></div> : (
        <>
          {offers.length > 0 && <section className="section"><div className="container"><h2>Special offers</h2><Grid items={offers} /></div></section>}
          {featured.length > 0 && <section className="section soft"><div className="container"><h2>Featured dishes</h2><Grid items={featured} /></div></section>}
          {popular.length > 0 && <section className="section"><div className="container"><h2>Popular dishes</h2><Grid items={popular} /></div></section>}
          {(menu.data ?? []).length > 0 && (
            <section className="section soft"><div className="container"><h2>Browse by category</h2>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>{menu.data!.map((c) => <Link key={c.slug} className="btn secondary" to={`/menu?category=${c.slug}`}>{c.name}</Link>)}</div>
            </div></section>
          )}
        </>
      )}
      {(services.data ?? []).length > 0 && (
        <section className="section"><div className="container"><h2>Our services</h2>
          <div className="grid g3">{services.data!.map((s) => <div className="card" key={s.slug}><h3>{s.name}</h3><p className="muted">{s.description}</p></div>)}</div>
          <p style={{ marginTop: 16 }}><Link to="/services">All services</Link></p>
        </div></section>
      )}
      <section className="section soft"><div className="container grid g2">
        <div><h2><MapPin aria-hidden size={22} /> Find us</h2>{site.branches.map((b) => <div key={b.name} style={{ marginBottom: 12 }}><b>{b.name}</b><br />{b.address}<Hours hours={b.operating_hours} /></div>)}</div>
        {(site.delivery_info || site.delivery_enabled) && <div><h2><Truck aria-hidden size={22} /> Delivery</h2><p>{site.delivery_info || 'Delivery is available. Details are shown at checkout.'}</p></div>}
      </div></section>
    </>
  )
}

export function Menu() {
  const { site } = useSite()
  const [q, setQ] = useState('')
  const [params, setParams] = useState(() => new URLSearchParams(window.location.search).get('category') ?? '')
  const all = useMenu()
  const shown = useMenu({ q: q.trim(), category: params })
  useSeo({ title: `Menu | ${site.restaurant.name}`, description: `Browse the full menu of ${site.restaurant.name}.`, path: '/menu' })
  return (
    <section className="section"><div className="container">
      <h1>Menu</h1>
      <div style={{ position: 'relative', maxWidth: 420, marginBottom: 16 }}>
        <Search size={18} aria-hidden style={{ position: 'absolute', left: 12, top: 13 }} />
        <input className="input" style={{ paddingLeft: 38 }} type="search" placeholder="Search dishes" aria-label="Search dishes" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }} role="group" aria-label="Categories">
        <button className={`btn sm ${params ? 'secondary' : ''}`} onClick={() => setParams('')}>All</button>
        {(all.data ?? []).map((c) => <button key={c.slug} className={`btn sm ${params === c.slug ? '' : 'secondary'}`} onClick={() => setParams(c.slug)}>{c.name}</button>)}
      </div>
      {shown.loading && !shown.data ? <div className="grid g3">{[0, 1, 2].map((i) => <Skeleton key={i} h={260} />)}</div>
        : shown.error ? <ErrorState message={shown.error} onRetry={shown.reload} />
        : !shown.data?.length ? <Empty title={q ? 'No dishes match your search' : 'The menu is being prepared'}>{q ? 'Try a different word.' : 'Please check back soon.'}</Empty>
        : shown.data.map((c) => <div key={c.slug} style={{ marginBottom: 36 }}><h2>{c.name}</h2>{c.description && <p className="muted">{c.description}</p>}<Grid items={c.products} /></div>)}
    </div></section>
  )
}

export function ProductPage() {
  const { slug = '' } = useParams()
  const { site, money } = useSite()
  const { data: p, loading, error } = useAsync(() => api<PublicProduct>(`/catalog/public/products/${slug}/`, A), [slug])
  useSeo({
    title: p ? `${p.name} | ${site.restaurant.name}` : site.restaurant.name, description: p?.description.slice(0, 160), image: p?.image, path: `/menu/${slug}`, type: 'product',
    jsonLd: p ? { '@context': 'https://schema.org', '@type': 'Product', name: p.name, description: p.description, image: p.image ?? undefined,
      offers: { '@type': 'Offer', price: p.price, priceCurrency: site.currency, availability: p.sold_out ? 'https://schema.org/OutOfStock' : 'https://schema.org/InStock' } } : undefined,
  })
  if (loading) return <div className="container section"><Skeleton h={300} /></div>
  if (error || !p) return <div className="container section"><Empty title="Dish not found"><Link to="/menu">Back to the menu</Link></Empty></div>
  return (
    <section className="section"><div className="container grid g2" style={{ alignItems: 'start' }}>
      {p.image ? <img src={p.image} alt={p.name} style={{ width: '100%', borderRadius: 12 }} /> : <div className="card empty" aria-hidden>🍽️</div>}
      <div>
        <p className="muted"><Link to={`/menu?category=${p.category_slug}`}>{p.category_name}</Link></p>
        <h1>{p.name}</h1>
        <p style={{ fontSize: '1.5rem' }}><strong>{money(p.price)}</strong>{p.on_offer && <s className="muted" style={{ marginLeft: 10 }}>{money(p.regular_price)}</s>}</p>
        {p.on_offer && <span className="badge">{p.offer_label || 'Special offer'}</span>} {p.sold_out && <span className="badge suspended">Sold out</span>}
        <p style={{ marginTop: 12 }}>{p.description}</p>
        {p.prep_time_minutes && <p className="muted"><Clock size={16} aria-hidden /> About {p.prep_time_minutes} minutes</p>}
        {p.ingredients.length > 0 && <p><b>Ingredients:</b> {p.ingredients.join(', ')}</p>}
        {p.variations.length > 0 && <><h3>Options</h3><ul>{p.variations.map((v) => <li key={v.id}>{v.name} {Number(v.price_delta) > 0 && <span className="muted">(+{money(v.price_delta)})</span>}</li>)}</ul></>}
        {p.addons.length > 0 && <><h3>Extras</h3><ul>{p.addons.map((a) => <li key={a.id}>{a.name} <span className="muted">(+{money(a.price)})</span></li>)}</ul></>}
        <ProductBuy p={p} />
      </div>
    </div></section>
  )
}

export function Services() {
  const { site } = useSite()
  const { data, loading, error, reload } = useAsync(() => api<{ slug: string; name: string; description: string; image: string | null }[]>('/catalog/public/services/', A), [])
  useSeo({ title: `Services | ${site.restaurant.name}`, description: `Services offered by ${site.restaurant.name}.`, path: '/services' })
  return (
    <section className="section"><div className="container"><h1>Our services</h1>
      {loading ? <Skeleton h={160} /> : error ? <ErrorState message={error} onRetry={reload} /> : !data?.length ? <Empty title="No services listed yet" /> : (
        <div className="grid g3">{data.map((s) => <div className="card" key={s.slug}>{s.image && <img src={s.image} alt={s.name} loading="lazy" style={{ width: '100%', borderRadius: 8, marginBottom: 10 }} />}<h3>{s.name}</h3><p className="muted">{s.description}</p></div>)}</div>
      )}
    </div></section>
  )
}

export function Gallery() {
  const { site } = useSite()
  const { data, loading, error, reload } = useAsync(() => api<{ id: number; image: string; caption: string }[]>('/catalog/public/gallery/', A), [])
  useSeo({ title: `Gallery | ${site.restaurant.name}`, description: `Photos of ${site.restaurant.name}.`, path: '/gallery' })
  return (
    <section className="section"><div className="container"><h1>Gallery</h1>
      {loading ? <Skeleton h={200} /> : error ? <ErrorState message={error} onRetry={reload} /> : !data?.length ? <Empty title="No photos yet" /> : (
        <div className="grid g3">{data.map((g) => <figure key={g.id} style={{ margin: 0 }}><img src={g.image} alt={g.caption || `${site.restaurant.name} photo`} loading="lazy" style={{ width: '100%', borderRadius: 10 }} />{g.caption && <figcaption className="muted">{g.caption}</figcaption>}</figure>)}</div>
      )}
    </div></section>
  )
}

export function About() {
  const { site } = useSite()
  useSeo({ title: `About | ${site.restaurant.name}`, description: site.seo_description, path: '/about' })
  return (
    <section className="section"><div className="container prose"><h1>About {site.restaurant.name}</h1>
      <p style={{ whiteSpace: 'pre-line' }}>{site.about_text}</p>
      {site.delivery_info && <><h2>Delivery</h2><p style={{ whiteSpace: 'pre-line' }}>{site.delivery_info}</p></>}
    </div></section>
  )
}

export function Contact() {
  const { site } = useSite()
  const r = site.restaurant
  useSeo({ title: `Contact | ${r.name}`, description: `Contact ${r.name}, find our locations and opening hours.`, path: '/contact' })
  return (
    <section className="section"><div className="container prose"><h1>Contact us</h1>
      {r.contact_phone && <p><Phone size={16} aria-hidden /> <a href={`tel:${r.contact_phone}`}>{r.contact_phone}</a></p>}
      {r.contact_email && <p><Mail size={16} aria-hidden /> <a href={`mailto:${r.contact_email}`}>{r.contact_email}</a></p>}
      <h2>Locations and hours</h2>
      {site.branches.map((b) => <div key={b.name} className="card" style={{ marginBottom: 12 }}><h3>{b.name}</h3><p><MapPin size={16} aria-hidden /> {b.address || 'Address not listed'}</p>{b.phone && <p><Phone size={16} aria-hidden /> {b.phone}</p>}<Hours hours={b.operating_hours} /></div>)}
    </div></section>
  )
}

export function Faq() {
  const { site } = useSite()
  useSeo({
    title: `FAQ | ${site.restaurant.name}`, path: '/faq',
    jsonLd: site.faqs.length ? { '@context': 'https://schema.org', '@type': 'FAQPage', mainEntity: site.faqs.map((f) => ({ '@type': 'Question', name: f.q, acceptedAnswer: { '@type': 'Answer', text: f.a } })) } : undefined,
  })
  return (
    <section className="section"><div className="container prose faq"><h1>Frequently asked questions</h1>
      {site.faqs.length ? site.faqs.map((f) => <details key={f.q}><summary>{f.q}</summary><p style={{ marginTop: 8 }}>{f.a}</p></details>) : <Empty title="No questions yet" />}
    </div></section>
  )
}

export function Policy() {
  const { slug = '' } = useParams()
  const { site } = useSite()
  const { data, loading, error } = useAsync(() => api<{ title: string; text: string }>(`/catalog/public/policies/${slug}/`, A), [slug])
  useSeo({ title: `${data?.title ?? 'Policy'} | ${site.restaurant.name}`, path: `/policies/${slug}` })
  if (loading) return <div className="container section"><Skeleton h={200} /></div>
  if (error || !data) return <div className="container section"><Empty title="Page not found" /></div>
  return <section className="section"><div className="container prose"><h1>{data.title}</h1><p style={{ whiteSpace: 'pre-line' }}>{data.text}</p></div></section>
}

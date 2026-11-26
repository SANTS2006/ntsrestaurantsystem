import { ArrowRight, CalendarCheck, Clock, Mail, MapPin, Phone, Search, ShoppingBag, Smartphone, Sparkles, Truck, UtensilsCrossed } from 'lucide-react'
import { Suspense, lazy, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { Empty, ErrorState, Skeleton, useAsync } from '../ui/kit'
import { Rise, SectionHead, Tilt } from '../ui/fx'
import { useSeo } from './seo'
import { ProductBuy } from './shop'
import { useSite, type MenuCategory, type PublicProduct } from './SiteContext'
import { BackButton } from '../ui/BackButton'

const A = { auth: false } as const
const Scene3D = lazy(() => import('../ui/Scene3D'))

function useMenu(params: Record<string, string> = {}) {
  const key = JSON.stringify(params)
  return useAsync(() => api<MenuCategory[]>('/catalog/public/menu/', { params, ...A }), [key])
}

export function ProductCard({ p }: { p: PublicProduct }) {
  const { money } = useSite()
  return (
    <Link to={`/menu/${p.slug}`} className="card lift product-card" style={{ textDecoration: 'none', color: 'inherit', padding: 0, overflow: 'hidden', display: 'block' }}>
      {p.image ? <img src={p.image} alt={`${p.name}`} loading="lazy" width={400} height={240} style={{ width: '100%', height: 170, objectFit: 'cover', display: 'block' }} />
        : <div className="dish-ph" aria-hidden>{p.name.charAt(0)}</div>}
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
  return <div className="cards">{items.map((p, i) => <Rise key={p.id} index={i % 4}><Tilt><ProductCard p={p} /></Tilt></Rise>)}</div>
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
  const featured = all.filter((p) => p.is_featured).slice(0, 8)
  const popular = all.filter((p) => p.is_popular && !p.is_featured).slice(0, 8)
  const offers = all.filter((p) => p.on_offer).slice(0, 8)
  const services = useAsync(() => api<{ slug: string; name: string; description: string }[]>('/catalog/public/services/', A), [])
  const gallery = useAsync(() => api<{ id: number; image: string; caption: string }[]>('/catalog/public/gallery/', A), [])
  useSeo({
    title: site.seo_title, description: site.seo_description, image: r.logo, path: '/',
    jsonLd: {
      '@context': 'https://schema.org', '@type': 'Restaurant', name: r.name, description: r.description, url: site.url, image: r.logo ?? undefined,
      telephone: r.contact_phone || undefined, email: r.contact_email || undefined, hasMenu: `${site.url}/menu`,
      address: r.address || r.city ? { '@type': 'PostalAddress', streetAddress: r.address, addressLocality: r.city, addressCountry: r.country } : undefined,
    },
  })
  const photos = (gallery.data ?? []).slice(0, 8)
  const where = [r.city, r.country].filter(Boolean).join(', ')
  return (
    <>
      <section className="hero-x">
        <span className="blob a" aria-hidden /><span className="blob b" aria-hidden />
        <div className="container cols">
          <div>
            <p className="pill"><UtensilsCrossed size={14} aria-hidden /> {where || 'Welcome'}</p>
            <h1><span className="grad">{site.hero_title}</span></h1>
            {site.hero_subtitle && <p className="lead">{site.hero_subtitle}</p>}
            <div className="cta">
              <Link className="btn lg" to="/menu">View the menu <ArrowRight size={18} aria-hidden /></Link>
              <Link className="btn lg secondary" to="/reserve"><CalendarCheck size={18} aria-hidden /> Reserve a table</Link>
            </div>
            <div className="perks">
              {site.pickup_enabled && <span><ShoppingBag size={17} aria-hidden /> Order for pickup</span>}
              {site.delivery_enabled && <span><Truck size={17} aria-hidden /> Delivery available</span>}
              {site.online_payments && <span><Smartphone size={17} aria-hidden /> Pay with mobile money</span>}
            </div>
          </div>
          <div className="stage">
            <Suspense fallback={null}><Scene3D /></Suspense>
            <span className="float one" aria-hidden><UtensilsCrossed size={18} /> Freshly prepared</span>
            <span className="float two" aria-hidden><ShoppingBag size={18} /> Order online</span>
          </div>
        </div>
      </section>

      <section className="section-x">
        <div className="container">
          <SectionHead eyebrow="How it works" title="Good food in three steps" />
          <div className="steps">
            {[['Choose your dishes', 'Browse the menu, pick sizes and extras, and add them to your cart.'],
              ['Place your order', `Choose ${[site.pickup_enabled && 'pickup', site.delivery_enabled && 'delivery'].filter(Boolean).join(' or ') || 'how you want it'} and how you will pay.`],
              ['Enjoy', 'Follow your order as it is prepared. We tell you when it is ready.']].map(([t, d], i) => <Rise key={t} index={i} from="zoom"><div className="step"><h3>{t}</h3><p>{d}</p></div></Rise>)}
          </div>
        </div>
      </section>

      {menu.loading ? <div className="container section-x"><Skeleton h={240} /></div> : menu.error ? <div className="container section-x"><ErrorState message={menu.error} onRetry={menu.reload} /></div> : (
        <>
          {offers.length > 0 && <section className="section-x alt"><div className="container"><SectionHead eyebrow="Limited time" title="Special offers" /><Grid items={offers} /></div></section>}
          {featured.length > 0 && <section className="section-x"><div className="container"><SectionHead eyebrow="From our kitchen" title="Featured dishes" /><Grid items={featured} /></div></section>}
          {popular.length > 0 && <section className="section-x alt"><div className="container"><SectionHead eyebrow="Guests love these" title="Popular dishes" /><Grid items={popular} /></div></section>}
          {(menu.data ?? []).length > 0 && (
            <section className="section-x"><div className="container"><SectionHead eyebrow="Explore" title="Browse by category" />
              <div className="cards">{menu.data!.map((c, i) => <Rise key={c.slug} index={i % 4}><Link className="cat-card" to={`/menu?category=${c.slug}`}><span>{c.name}<small>{c.products.length} dish{c.products.length === 1 ? '' : 'es'}</small></span><ArrowRight size={20} aria-hidden /></Link></Rise>)}</div>
            </div></section>
          )}
        </>
      )}

      {photos.length > 0 && (
        <section className="section-x alt"><div className="container"><SectionHead eyebrow="Gallery" title={`A taste of ${r.name}`} />
          <div className="gallery-strip">{photos.map((g, i) => <Rise key={g.id} index={i % 4} from="zoom"><figure><img src={g.image} alt={g.caption || `Photo from ${r.name}`} loading="lazy" decoding="async" width={440} height={330} /></figure></Rise>)}</div>
          <p className="center" style={{ marginTop: 22 }}><Link className="btn secondary" to="/gallery">See the gallery</Link></p>
        </div></section>
      )}

      {(services.data ?? []).length > 0 && (
        <section className="section-x"><div className="container"><SectionHead eyebrow="What we offer" title="Our services" />
          <div className="cards">{services.data!.map((v, i) => <Rise key={v.slug} index={i % 4}><Tilt><div className="feature"><div className="icon-box"><Sparkles aria-hidden /></div><h3>{v.name}</h3><p>{v.description}</p></div></Tilt></Rise>)}</div>
          <p className="center" style={{ marginTop: 22 }}><Link className="btn secondary" to="/services">All services</Link></p>
        </div></section>
      )}

      <section className="section-x alt"><div className="container"><SectionHead eyebrow="Visit" title="Find us" />
        <div className="visit">
          {site.branches.map((b, i) => <Rise key={b.name} index={i} from="left"><div className="card"><h3><MapPin aria-hidden size={20} /> {b.name}</h3>{b.address && <p>{b.address}</p>}{b.phone && <p><Phone size={15} aria-hidden /> <a href={`tel:${b.phone}`}>{b.phone}</a></p>}<Hours hours={b.operating_hours} /></div></Rise>)}
          {(site.delivery_info || site.delivery_enabled) && <Rise from="right"><div className="card"><h3><Truck aria-hidden size={20} /> Delivery</h3><p>{site.delivery_info || 'Delivery is available. Details are shown at checkout.'}</p></div></Rise>}
        </div>
      </div></section>

      <section className="section-x"><div className="container"><Rise from="zoom"><div className="cta-band">
        <h2>Hungry? Order from {r.name}</h2>
        <p>Choose your favourites online, or book a table and let us look after you.</p>
        <div className="cta"><Link className="btn lg" to="/menu">Start your order</Link><Link className="btn lg outline" to="/catering">Plan an event</Link></div>
      </div></Rise></div></section>
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
  if (error || !p) return <div className="container section"><Empty title="Dish not found"><BackButton to="/menu">Back to the menu</BackButton></Empty></div>
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

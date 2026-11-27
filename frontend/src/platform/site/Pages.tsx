import { ArrowRight, Banknote, Building2, Check, ChefHat, ClipboardList, Clock, HelpCircle, Lock, Mail, MessageCircle, Phone, QrCode, ShieldCheck, ShoppingCart, Users, Wallet } from 'lucide-react'
import { Suspense, lazy } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { Empty, ErrorState, Skeleton, useAsync, useDocumentTitle } from '../../ui/kit'
import { Rise, SectionHead, Tilt } from '../../ui/fx'
import { ContactForm } from '../../ui/ContactForm'
import { LocationCard } from '../../ui/Maps'
import { PageHero } from '../../ui/PageHero'
import { NotFound } from '../../ui/NotFound'
import { Paragraphs, RichText } from '../../ui/RichText'
import { plain } from '../../ui/boldText'
import { formatMoney } from '../../tenant/SiteContext'
import { legal, usePublicSettings } from './SiteLayout'
import { useSiteTexts, type SiteTexts, type Titled } from './content'

const Scene3D = lazy(() => import('../../ui/Scene3D'))

// pictures that go with the features and the short points, by position
const FEATURE_ICONS = [ShoppingCart, Building2, Banknote, Users, QrCode, Wallet, ClipboardList, Lock]
const PERK_ICONS = [ShoppingCart, Banknote, Lock]

function useSeoTexts(page: keyof SiteTexts['seo']) {
  const { seo } = useSiteTexts().content
  useDocumentTitle(seo[page].title, seo[page].text)
}

function FeatureCards({ items }: { items: Titled[] }) {
  return (
    <div className="cards">
      {items.map((f, i) => {
        const Icon = FEATURE_ICONS[i % FEATURE_ICONS.length]
        return <Rise key={i} index={i % 4}><Tilt><div className="feature"><div className="icon-box"><Icon aria-hidden /></div><h3><RichText text={f.title} /></h3><p className="pre"><RichText text={f.text} /></p></div></Tilt></Rise>
      })}
    </div>
  )
}

function ClosingBanner({ title, text }: { title: string; text: string }) {
  if (!title) return null
  return (
    <section className="section-x"><div className="container"><Rise from="zoom"><div className="cta-band">
      <h2><RichText text={title} /></h2>
      <p><RichText text={text} /></p>
      <div className="cta"><Link className="btn lg" to="/contact">Contact us</Link><Link className="btn lg outline" to="/pricing">See pricing</Link></div>
    </div></Rise></div></section>
  )
}

export function Home() {
  useSeoTexts('home')
  const { content, images } = useSiteTexts()
  const h = content.home
  const plans = useAsync(() => api<{ results?: unknown[] } | Plan[]>('/platform/public/plans/', { auth: false }), [])
  return (
    <>
      <section className={`hero-x ${images.home ? 'has-photo' : ''}`}>
        {images.home && <img className="hero-photo" src={images.home} alt="" />}
        <span className="blob a" aria-hidden /><span className="blob b" aria-hidden />
        <div className="container cols">
          <div>
            {h.pill && <p className="pill"><ChefHat size={14} aria-hidden /> <RichText text={h.pill} /></p>}
            <h1><RichText text={h.title} /> <span className="grad"><RichText text={h.title_highlight} /></span></h1>
            {h.lead && <p className="lead"><RichText text={h.lead} /></p>}
            <div className="cta">
              {h.primary_button && <Link className="btn lg" to="/contact">{plain(h.primary_button)} <ArrowRight size={18} aria-hidden /></Link>}
              {h.secondary_button && <Link className="btn lg secondary" to="/features">{plain(h.secondary_button)}</Link>}
            </div>
            <div className="perks">{h.perks.map((p, i) => { const Icon = PERK_ICONS[i % PERK_ICONS.length]; return <span key={i}><Icon size={17} aria-hidden /> <RichText text={p.text} /></span> })}</div>
          </div>
          <div className="stage">
            <Suspense fallback={null}><Scene3D /></Suspense>
            <span className="float one" aria-hidden><ShoppingCart size={18} /> Online orders</span>
            <span className="float two" aria-hidden><QrCode size={18} /> QR table ordering</span>
            <span className="float three" aria-hidden><ChefHat size={18} /> Kitchen display</span>
          </div>
        </div>
      </section>

      <section className="section-x" id="features">
        <div className="container">
          <SectionHead eyebrow={plain(h.features_eyebrow)} title={plain(h.features_title)} text={plain(h.features_text)} />
          <FeatureCards items={content.features.items} />
        </div>
      </section>

      {h.steps.length > 0 && (
        <section className="section-x alt">
          <div className="container">
            <SectionHead eyebrow={plain(h.steps_eyebrow)} title={plain(h.steps_title)} />
            <div className="steps">
              {h.steps.map((st, i) => <Rise key={i} index={i} from="zoom"><div className="step"><h3><RichText text={st.title} /></h3><p className="pre"><RichText text={st.text} /></p></div></Rise>)}
            </div>
          </div>
        </section>
      )}

      {h.security_title && (
        <section className="section-x">
          <div className="container">
            <Rise from="zoom">
              <div className="spotlight">
                <ShieldCheck size={46} aria-hidden />
                <div><h2><RichText text={h.security_title} /></h2><p><RichText text={h.security_text} /></p></div>
                <Link className="btn secondary" to="/legal/security-policy">Read our security policy</Link>
              </div>
            </Rise>
          </div>
        </section>
      )}

      <section className="section-x alt">
        <div className="container center">
          <SectionHead eyebrow="Plans" title={plain(h.pricing_title) || 'Pricing'} />
          {plans.loading ? <Skeleton h={120} /> : <PlanList data={plans.data} compact />}
          <p style={{ marginTop: 20 }}><Link to="/pricing">View all plans</Link></p>
        </div>
      </section>

      <ClosingBanner title={h.cta_title} text={h.cta_text} />
    </>
  )
}

export type Plan = { id: number; name: string; slug: string; description: string; price: string; currency: string; interval: string; features: string[]; is_featured: boolean }

function PlanList({ data, compact }: { data: unknown; compact?: boolean }) {
  const list: Plan[] = Array.isArray(data) ? (data as Plan[]) : ((data as { results?: Plan[] } | null)?.results ?? [])
  if (!list.length) return <Empty title="Pricing on request">Contact us for a plan that fits your restaurant.</Empty>
  return (
    <div className="plans">
      {list.map((p) => (
        <div key={p.id} className={`plan ${p.is_featured ? 'featured' : ''}`}>
          {p.is_featured && <span className="plan-flag">Recommended</span>}
          <h3>{p.name}</h3>
          <div className="price">{formatMoney(p.price, p.currency)}<small className="muted"> / {p.interval}</small></div>
          <p className="muted">{p.description}</p>
          {!compact && <ul className="feat-list">{p.features.map((f) => <li key={f}><Check size={18} color="var(--ok)" aria-hidden /> {f}</li>)}</ul>}
          {!compact && <Link className="btn" to="/contact">Choose {p.name}</Link>}
        </div>
      ))}
    </div>
  )
}

export function Features() {
  useSeoTexts('features')
  const { content, images } = useSiteTexts()
  const f = content.features
  return (
    <>
      <PageHero crumb="Features" eyebrow={f.eyebrow} title={f.title} lead={f.lead} image={images.features}>
        <Link className="btn lg" to="/contact">Talk to us <ArrowRight size={18} aria-hidden /></Link>
        <Link className="btn lg secondary" to="/pricing">See pricing</Link>
      </PageHero>
      <section className="section-x"><div className="container"><FeatureCards items={f.items} /></div></section>
      <ClosingBanner title={content.home.cta_title} text={content.home.cta_text} />
    </>
  )
}

export function Pricing() {
  useSeoTexts('pricing')
  const { content, images } = useSiteTexts()
  const p = content.pricing
  const plans = useAsync(() => api<unknown>('/platform/public/plans/', { auth: false }), [])
  return (
    <>
      <PageHero crumb="Pricing" eyebrow={p.eyebrow} title={p.title} lead={p.lead} image={images.pricing} />
      <section className="section-x"><div className="container center">
        {plans.loading ? <Skeleton h={160} /> : plans.error ? <ErrorState message={plans.error} onRetry={plans.reload} /> : <PlanList data={plans.data} />}
        {p.note && <p className="muted" style={{ marginTop: 24 }}><RichText text={p.note} /> <Link to="/contact">Contact us</Link></p>}
      </div></section>
    </>
  )
}

export function About() {
  useSeoTexts('about')
  const { content, images } = useSiteTexts()
  const a = content.about
  return (
    <>
      <PageHero crumb="About" eyebrow={a.eyebrow} title={a.title} lead={a.lead} image={images.about} />
      <section className="section-x"><div className="container">
        <div className="story">
          {a.sections.map((s, i) => (
            <Rise key={i} index={i % 3}><article className="story-card"><span className="story-num" aria-hidden>{String(i + 1).padStart(2, '0')}</span><h2><RichText text={s.title} /></h2><Paragraphs text={s.text} /></article></Rise>
          ))}
        </div>
      </div></section>
      <ClosingBanner title={content.home.cta_title} text={content.home.cta_text} />
    </>
  )
}

export function Faq() {
  useSeoTexts('faq')
  const { content, images } = useSiteTexts()
  const f = content.faq
  return (
    <>
      <PageHero crumb="FAQ" eyebrow={f.eyebrow} title={f.title} lead={f.lead} image={images.faq} icon={<HelpCircle size={15} aria-hidden />} />
      <section className="section-x"><div className="container faq-layout">
        <div className="faq-list">
          {f.items.length ? f.items.map((x, i) => <details key={i}><summary><RichText text={x.q} /></summary><Paragraphs text={x.a} /></details>) : <Empty title="No questions yet" />}
        </div>
        <aside className="side-card">
          <MessageCircle size={30} aria-hidden />
          <h3>Still have a question?</h3>
          <p>Send us a message and we will get back to you.</p>
          <Link className="btn" to="/contact">Contact us</Link>
        </aside>
      </div></section>
    </>
  )
}

export function Contact() {
  useSeoTexts('contact')
  const { content, images } = useSiteTexts()
  const c = content.contact
  const { data: s } = usePublicSettings()
  return (
    <>
      <PageHero crumb="Contact" eyebrow={c.eyebrow} title={c.title} lead={c.lead} image={images.contact} />
      <section className="section-x"><div className="container contact-layout">
        <aside className="contact-info">
          {s?.support_email && <a className="info-tile" href={`mailto:${s.support_email}`}><Mail aria-hidden /><span><b>Email us</b><small>{s.support_email}</small></span></a>}
          {c.phone && <a className="info-tile" href={`tel:${c.phone.replace(/[^+\d]/g, '')}`}><Phone aria-hidden /><span><b>Call us</b><small>{c.phone}</small></span></a>}
          {s?.whatsapp_number && <a className="info-tile" href={`https://wa.me/${s.whatsapp_number}`} target="_blank" rel="noopener noreferrer"><MessageCircle aria-hidden /><span><b>WhatsApp</b><small>Message us</small></span></a>}
          {c.hours && <div className="info-tile"><Clock aria-hidden /><span><b>Opening hours</b><small className="pre"><RichText text={c.hours} /></small></span></div>}
          <div className="info-tile"><HelpCircle aria-hidden /><span><b>Quick answers</b><small><Link to="/faq">Read the frequently asked questions</Link></small></span></div>
        </aside>
        <ContactForm platform title={plain(c.form_title) || 'Send us a message'} privacyTo="/legal/privacy-policy" />
      </div></section>
      {c.locations.length > 0 && (
        <section className="section-x alt"><div className="container">
          <SectionHead eyebrow="Visit us" title="Where to find us" />
          <div className="locations">
            {c.locations.map((l, i) => <LocationCard key={i} name={l.name} place={l}>{l.phone && <p><a href={`tel:${l.phone.replace(/[^+\d]/g, '')}`}>{l.phone}</a></p>}{l.hours && <p className="muted pre">{l.hours}</p>}</LocationCard>)}
          </div>
        </div></section>
      )}
    </>
  )
}

export function Legal() {
  const { slug = '' } = useParams()
  const { content, images, draft_legal } = useSiteTexts()
  const doc = content.legal[slug]
  const title = legal.find(([s]) => s === slug)?.[1] ?? 'Page not found (404)'
  const { data: s } = usePublicSettings()
  useDocumentTitle(doc ? title : 'Page not found (404)')
  if (!doc) return <NotFound />
  const draft = draft_legal.includes(slug)
  const name = s?.platform_name ?? 'NTS Restaurant Platform'
  const fill = (text: string) => text.replace(/\[Company Name\]/g, name)
  return (
    <>
      <PageHero crumb={title} eyebrow="Legal" title={title} image={images.legal} />
      <section className="section-x"><div className="container legal-layout">
        <aside className="legal-nav"><h4>Policies</h4><ul>{legal.map(([to, l]) => <li key={to}><Link to={`/legal/${to}`} aria-current={to === slug ? 'page' : undefined}>{l}</Link></li>)}</ul></aside>
        <article className="legal-doc">
          {draft && <div className="alert warn">Draft template. Have it reviewed and customised by qualified legal counsel before publishing. It does not claim compliance with any law or standard.</div>}
          {doc.map((x, i) => <section key={i}><h2><RichText text={x.title} /></h2><Paragraphs text={fill(x.text)} /></section>)}
        </article>
      </div></section>
    </>
  )
}

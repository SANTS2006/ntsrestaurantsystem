import { Banknote, Building2, Check, ChefHat, ClipboardList, Lock, QrCode, ShoppingCart, Users, Wallet } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { Empty, ErrorState, Reveal, Skeleton, useAsync, useDocumentTitle } from '../../ui/kit'
import { legal, usePublicSettings } from './SiteLayout'
import { legalDocs } from './legalContent'

const features = [
  [ShoppingCart, 'Online ordering', 'A branded website for every restaurant with menu, cart and checkout.'],
  [Building2, 'Multi-branch management', 'Run many branches with isolated records and branch-level managers.'],
  [Banknote, 'Payments', 'Cash, mobile money and online payments with receipts and reconciliation.'],
  [Users, 'Staff management', 'Invite staff securely and give each role only the access it needs.'],
  [QrCode, 'QR table ordering', 'Diners scan a table code; cashiers review and confirm requests.'],
  [Wallet, 'Salary and payroll', 'Salary structures, payroll runs and receipts with approval controls.'],
  [ClipboardList, 'Financial reporting', 'Sales, refunds and payment breakdowns per branch and restaurant.'],
  [Lock, 'Tenant isolation', 'Each restaurant’s data is separated and enforced on the server.'],
] as const

const faqs = [
  ['How do restaurants get started?', 'The platform team registers your restaurant. Your administrator receives an email with a secure one-time link to set a password.'],
  ['Does every restaurant get its own website?', 'Yes. Each restaurant has its own address, branding, menu and customer accounts.'],
  ['Which payment methods are supported?', 'Cash, mobile money and online payments. Provider availability depends on your plan and configuration.'],
  ['Can one restaurant have several branches?', 'Yes. Branch managers only see the branch they are assigned to.'],
  ['How is my data protected?', 'Access is checked on the server for every request, passwords are hashed, sign-in attempts are rate limited, and sensitive actions are audit logged.'],
]

export function Home() {
  useDocumentTitle('Restaurant management and online ordering platform', 'Websites, ordering, payments, staff and reporting for restaurants, in one platform.')
  const plans = useAsync(() => api<{ results?: unknown[] } | Plan[]>('/platform/public/plans/', { auth: false }), [])
  return (
    <>
      <section className="hero">
        <div className="container cols">
          <div>
            <p className="eyebrow">For restaurants and restaurant groups</p>
            <h1>Run every branch, till and order from one place.</h1>
            <p className="muted" style={{ fontSize: '1.15rem' }}>
              Give each restaurant its own branded website with online ordering, payments, staff and payroll tools, and clear financial reports.
            </p>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <Link className="btn" to="/contact">Talk to us</Link>
              <Link className="btn secondary" to="/features">See features</Link>
            </div>
          </div>
          <div className="mock" aria-hidden>
            <div className="card panel">
              <small className="muted">Illustrative preview</small>
              <h3>Today at Ocean View</h3>
              {['Order #1042 · Preparing', 'Order #1043 · Ready for pickup', 'Order #1044 · Awaiting payment'].map((t) => (
                <div key={t} className="alert" style={{ margin: '8px 0' }}>{t}</div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="section" id="features">
        <div className="container">
          <Reveal><p className="eyebrow">Capabilities</p><h2>Everything a restaurant needs to operate</h2></Reveal>
          <div className="grid g3" style={{ marginTop: 24 }}>
            {features.map(([Icon, t, d]) => (
              <Reveal key={t}><div className="card lift"><div className="icon-box"><Icon aria-hidden /></div><h3>{t}</h3><p className="muted">{d}</p></div></Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section soft">
        <div className="container center">
          <ChefHat size={36} aria-hidden color="var(--brand)" />
          <h2>Built for security from the start</h2>
          <p className="muted" style={{ maxWidth: 640, margin: '0 auto' }}>
            Permissions are enforced on the server, each restaurant’s records are isolated, and every sensitive action leaves an audit trail.
          </p>
          <Link to="/legal/security-policy">Read our security policy</Link>
        </div>
      </section>

      <section className="section">
        <div className="container center">
          <h2>Pricing</h2>
          {plans.loading ? <Skeleton h={120} /> : <PlanList data={plans.data} compact />}
          <p style={{ marginTop: 20 }}><Link to="/pricing">View all plans</Link></p>
        </div>
      </section>

      <section className="section soft">
        <div className="container center">
          <h2>Ready to bring your restaurant online?</h2>
          <Link className="btn" to="/contact">Contact us</Link>
        </div>
      </section>
    </>
  )
}

export type Plan = { id: number; name: string; slug: string; description: string; price: string; currency: string; interval: string; features: string[]; is_featured: boolean }

function PlanList({ data, compact }: { data: unknown; compact?: boolean }) {
  const list: Plan[] = Array.isArray(data) ? (data as Plan[]) : ((data as { results?: Plan[] } | null)?.results ?? [])
  if (!list.length) return <Empty title="Pricing on request">Contact us for a plan that fits your restaurant.</Empty>
  return (
    <div className="grid g3" style={{ marginTop: 24, textAlign: 'left' }}>
      {list.map((p) => (
        <div key={p.id} className="card" style={p.is_featured ? { borderColor: 'var(--brand)' } : undefined}>
          <h3>{p.name}</h3>
          <div className="price">{Number(p.price).toLocaleString(undefined, { style: 'currency', currency: p.currency })}<small className="muted"> / {p.interval}</small></div>
          <p className="muted">{p.description}</p>
          {!compact && <ul className="feat-list">{p.features.map((f) => <li key={f}><Check size={18} color="var(--ok)" aria-hidden /> {f}</li>)}</ul>}
          {!compact && <Link className="btn" to="/contact">Choose {p.name}</Link>}
        </div>
      ))}
    </div>
  )
}

export function Features() {
  useDocumentTitle('Features')
  return (
    <section className="section"><div className="container">
      <h1>Features</h1>
      <div className="grid g3" style={{ marginTop: 24 }}>
        {features.map(([Icon, t, d]) => <div className="card" key={t}><div className="icon-box"><Icon aria-hidden /></div><h3>{t}</h3><p className="muted">{d}</p></div>)}
      </div>
    </div></section>
  )
}

export function Pricing() {
  useDocumentTitle('Pricing')
  const plans = useAsync(() => api<unknown>('/platform/public/plans/', { auth: false }), [])
  return (
    <section className="section"><div className="container center">
      <h1>Pricing</h1>
      {plans.loading ? <Skeleton h={160} /> : plans.error ? <ErrorState message={plans.error} onRetry={plans.reload} /> : <PlanList data={plans.data} />}
    </div></section>
  )
}

export function About() {
  useDocumentTitle('About us')
  return (
    <section className="section"><div className="container prose">
      <h1>About us</h1>
      <p>We build software that helps restaurants take orders, accept payments and manage their teams without juggling separate tools.</p>
      <p className="muted">Replace this text with your company’s own story before launch.</p>
    </div></section>
  )
}

export function Faq() {
  useDocumentTitle('Frequently asked questions')
  return (
    <section className="section"><div className="container prose faq">
      <h1>Frequently asked questions</h1>
      {faqs.map(([q, a]) => <details key={q}><summary>{q}</summary><p style={{ marginTop: 8 }}>{a}</p></details>)}
    </div></section>
  )
}

export function Contact() {
  useDocumentTitle('Contact us')
  const { data: s } = usePublicSettings()
  return (
    <section className="section"><div className="container prose">
      <h1>Contact us</h1>
      {s?.support_email ? <p>Email: <a href={`mailto:${s.support_email}`}>{s.support_email}</a></p> : <p className="muted">Contact details have not been configured yet.</p>}
      {s?.whatsapp_number && <p>WhatsApp: <a href={`https://wa.me/${s.whatsapp_number}`} target="_blank" rel="noopener noreferrer">Message us</a></p>}
    </div></section>
  )
}

export function Legal() {
  const { slug = '' } = useParams()
  const doc = legalDocs[slug]
  const title = legal.find(([s]) => s === slug)?.[1] ?? 'Not found'
  useDocumentTitle(title)
  if (!doc) return <section className="section"><div className="container"><Empty title="Page not found" /></div></section>
  return (
    <section className="section"><div className="container prose">
      <h1>{title}</h1>
      <div className="alert warn">Draft template. Have it reviewed and customised by qualified legal counsel before publishing. It does not claim compliance with any law or standard.</div>
      {doc.map(([h, p]) => <div key={h}><h2>{h}</h2><p>{p}</p></div>)}
    </div></section>
  )
}

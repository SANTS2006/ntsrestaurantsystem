import { AlertTriangle, Banknote, ChefHat, Download, FileBarChart, Package, Receipt, ShoppingBag, TrendingUp, Wallet } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api, downloadFile, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { AreaChart, BarList, Donut, Sparkline } from '../../ui/charts'
import { Empty, ErrorState, Kpi, PageHeader, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { StatusBadge, type OrderRow } from '../account/pages'
import { useSite } from '../SiteContext'

type Report = {
  range: { from: string; to: string; group: string }
  orders: { total: number; completed: number; pending: number; cancelled: number }
  sales: { booked: string; collected: string; refunds: string; net_collected: string; outstanding: string; payments: number; refund_count: number }
  payment_breakdown: { cash: string; mobile_money: string; online: string; in_person: string }
  series: { period: string; collected: string; refunds: string; net: string }[]
  top_products: { name: string; quantity: number; revenue: string }[]
  cashiers: { user_id: number; name: string; cash: string; mobile_money: string; orders_entered: number; shifts_closed: number; variance: string }[]
  staff_activity: { name: string; role: string; actions: number }[]
  inventory: { low_stock_count: number; low_stock: { name: string; stock: number; alert_at: number }[] }
  customers: { ordering: number; repeat: number }
  by_branch: { branch_id: number; name: string; orders: number; booked: string; collected: string; refunds: string; net_collected: string }[]
}
type AuditRow = { id: number; created_at: string; action: string; actor: string | null; object_type: string; object_id: string }

const iso = (d: Date) => d.toISOString().slice(0, 10)
const RANGES = [[7, '7 days'], [30, '30 days'], [90, '90 days']] as const
const greeting = () => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' }
const nice = (a: string) => a.replace(/[._]/g, ' ')

export default function Dashboard() {
  useDocumentTitle('Dashboard')
  const { money, site } = useSite()
  const { me } = useAuth()
  const toast = useToast()
  const [days, setDays] = useState(30)
  const [branch, setBranch] = useState('')
  const isAdmin = me?.role === 'restaurant_admin' || me?.role === 'platform_admin'
  const { from, to } = useMemo(() => { const t = new Date(); return { to: iso(t), from: iso(new Date(t.getTime() - (days - 1) * 86400000)) } }, [days])
  const group = days > 60 ? 'week' : 'day'
  const r = useAsync(() => api<Report>('/reports/branch/', { params: { from, to, branch, group } }), [from, to, branch, group])
  const recent = useAsync(() => api<Page<OrderRow>>('/orders/manage/', { params: { page_size: 7 } }), [])
  const audit = useAsync(() => (isAdmin ? api<Page<AuditRow>>('/reports/audit/', { params: { page_size: 8 } }) : Promise.resolve(null)), [isAdmin])
  const d = r.data
  const query = `from=${from}&to=${to}${branch ? `&branch=${branch}` : ''}`
  const exportCsv = (type: 'orders' | 'payments') => downloadFile(`/reports/export/?type=${type}&${query}`, `${type}-${from}-to-${to}.csv`).catch((e) => toast(e instanceof ApiError ? e.message : 'Export failed.'))
  const points = d?.series.map((s) => ({ label: s.period.slice(5), value: Number(s.collected), tip: `${s.period}: ${money(s.collected)} collected, ${money(s.refunds)} refunded` })) ?? []
  const spark = points.map((p) => p.value)
  const nonCancelled = d ? d.orders.total - d.orders.cancelled : 0
  const aov = d && nonCancelled > 0 ? (Number(d.sales.booked) / nonCancelled).toFixed(2) : '0.00'

  return (
    <>
      <PageHeader title={`${greeting()}, ${(me?.full_name || '').split(' ')[0] || 'there'}`} subtitle={`${site.restaurant.name} · ${from} to ${to}`}>
        <div className="seg" role="group" aria-label="Period">{RANGES.map(([n, l]) => <button key={n} aria-pressed={days === n} onClick={() => setDays(n)}>{l}</button>)}</div>
        {site.branches.length > 1 && <select className="input" style={{ width: 180 }} aria-label="Branch" value={branch} onChange={(e) => setBranch(e.target.value)}><option value="">All branches</option>{site.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
        <button className="btn sm secondary" onClick={() => exportCsv('orders')}><Download size={14} aria-hidden /> Orders</button>
        <button className="btn sm secondary" onClick={() => exportCsv('payments')}><Download size={14} aria-hidden /> Payments</button>
      </PageHeader>

      <div className="grid g4" style={{ marginBottom: 20 }}>
        <Link to="/manage/cashier" className="quick"><Banknote size={20} aria-hidden /> New sale</Link>
        <Link to="/manage/kitchen" className="quick"><ChefHat size={20} aria-hidden /> Kitchen display</Link>
        <Link to="/manage/products" className="quick"><Package size={20} aria-hidden /> Add a product</Link>
        <Link to="/manage/reports" className="quick"><FileBarChart size={20} aria-hidden /> Financial reports</Link>
      </div>

      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {r.loading && !d ? <div className="grid g4"><Skeleton h={120} /><Skeleton h={120} /><Skeleton h={120} /><Skeleton h={120} /></div> : d && (
        <>
          <div className="grid g4" style={{ marginBottom: 20 }}>
            <Kpi label="Collected" value={money(d.sales.collected)} icon={<Wallet size={18} />} sub={<>Net of refunds {money(d.sales.net_collected)}</>} spark={<Sparkline values={spark} />} />
            <Kpi label="Booked sales" value={money(d.sales.booked)} icon={<TrendingUp size={18} />} sub={<>{money(aov)} average order</>} />
            <Kpi label="Orders" value={String(d.orders.total)} icon={<ShoppingBag size={18} />} sub={<>{d.orders.completed} completed · {d.orders.pending} open</>} />
            <Kpi label="Outstanding" value={money(d.sales.outstanding)} icon={<Receipt size={18} />} sub={<>{d.sales.refund_count} refund(s) · {d.customers.repeat} repeat customer(s)</>} />
          </div>

          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 420px), 1fr))', marginBottom: 20 }}>
            <section className="card chart-card" style={{ gridColumn: 'span 2' }} aria-label="Revenue trend">
              <div className="chart-head"><div><h2>Revenue</h2><span className="muted">Money collected per {group}, refunds dashed</span></div>
                <div className="legend"><span><i style={{ background: 'var(--brand)' }} />Collected</span><span><i style={{ background: 'var(--gold)' }} />Refunds</span></div></div>
              <AreaChart points={points} second={d.series.map((s) => ({ label: s.period.slice(5), value: Number(s.refunds) }))} label="Money collected over time" format={(n) => money(n.toFixed(2))} secondLabel="Refunds" />
            </section>
            <section className="card chart-card" aria-label="Order mix">
              <div className="chart-head"><h2>Order status</h2></div>
              <Donut centre={String(d.orders.total)} sub="orders" slices={[{ label: 'Completed', value: d.orders.completed, color: 'var(--ok)' }, { label: 'In progress', value: d.orders.pending, color: 'var(--gold)' }, { label: 'Cancelled', value: d.orders.cancelled, color: 'var(--danger)' }]} />
              <h3 style={{ marginTop: 22, fontSize: '1rem' }}>How customers pay</h3>
              <BarList format={(n) => money(n.toFixed(2))} rows={[{ label: 'Cash', value: Number(d.payment_breakdown.cash) }, { label: 'Mobile money', value: Number(d.payment_breakdown.mobile_money) }, { label: 'Online orders', value: Number(d.payment_breakdown.online) }].filter((x) => x.value > 0)} empty="No payments yet." />
            </section>
          </div>

          <div className="grid g2" style={{ marginBottom: 20, alignItems: 'start' }}>
            <section className="card chart-card">
              <div className="chart-head"><h2>Popular menu items</h2><Link to="/manage/reports" className="btn sm ghost">Analytics</Link></div>
              <BarList format={(n) => `${n} sold`} rows={d.top_products.map((p) => ({ label: p.name, value: p.quantity, sub: money(p.revenue) }))} empty="No sales in this period." />
            </section>
            <section className="card">
              <div className="chart-head"><h2 style={{ fontSize: '1.15rem', margin: 0 }}>Recent orders</h2><Link to="/manage/orders" className="btn sm ghost">All orders</Link></div>
              {recent.loading && !recent.data ? <Skeleton h={140} /> : !recent.data?.results.length ? <Empty title="No orders yet" /> : recent.data.results.map((o) => (
                <Link key={o.id} to="/manage/orders" className="list-row" style={{ textDecoration: 'none', color: 'inherit' }}>
                  <span><b>{o.number}</b> <span className="muted">{o.contact_name} · {o.fulfilment.replace('_', ' ')}</span><br /><small className="muted">{new Date(o.created_at).toLocaleString()}</small></span>
                  <span style={{ textAlign: 'right' }}><b className="num">{money(o.total)}</b><br /><StatusBadge s={o.status} label={o.status_label} /></span>
                </Link>))}
            </section>
          </div>

          <div className="grid g2" style={{ alignItems: 'start' }}>
            <section className="card">
              <div className="chart-head"><h2 style={{ fontSize: '1.15rem', margin: 0 }}>Activity</h2></div>
              {isAdmin ? (audit.loading && !audit.data ? <Skeleton h={120} /> : !audit.data?.results.length ? <Empty title="No activity yet" /> : (
                <ul className="feed">{audit.data.results.map((a) => <li key={a.id}><span className="dot" /><span><b>{nice(a.action)}</b> <span className="muted">by {a.actor ?? 'the system'}</span><br /><small className="muted">{new Date(a.created_at).toLocaleString()}</small></span></li>)}</ul>
              )) : !d.staff_activity.length ? <Empty title="No staff activity in this period" /> : <ul className="feed">{d.staff_activity.map((s, i) => <li key={i}><span className="dot" /><span><b>{s.name}</b> <span className="muted">{s.role} · {s.actions} order update(s)</span></span></li>)}</ul>}
            </section>
            <section className="card">
              <div className="chart-head"><h2 style={{ fontSize: '1.15rem', margin: 0 }}>Stock alerts</h2><Link to="/manage/inventory" className="btn sm ghost">Inventory</Link></div>
              {!d.inventory.low_stock.length ? <p className="muted" style={{ margin: 0 }}>Every tracked product is above its alert level.</p> : d.inventory.low_stock.map((x) => (
                <div className="list-row" key={x.name}><span style={{ display: 'flex', gap: 8, alignItems: 'center' }}><AlertTriangle size={16} color="var(--warn)" aria-hidden /> {x.name}</span><span><b>{x.stock}</b> <span className="muted">left (alert at {x.alert_at})</span></span></div>))}
            </section>
            {d.by_branch.length > 1 && (
              <section className="card chart-card" style={{ gridColumn: '1 / -1' }}>
                <div className="chart-head"><h2>Branches</h2></div>
                <BarList format={(n) => money(n.toFixed(2))} rows={d.by_branch.map((b) => ({ label: b.name, value: Number(b.net_collected), sub: `${b.orders} orders` }))} />
              </section>)}
            {d.cashiers.length > 0 && (
              <section className="card table-wrap" style={{ gridColumn: '1 / -1' }}>
                <h2 style={{ fontSize: '1.15rem' }}>Cashier performance</h2>
                <table className="tbl"><thead><tr><th>Cashier</th><th>Cash</th><th>Mobile</th><th>Orders</th><th>Shifts</th><th>Variance</th></tr></thead><tbody>
                  {d.cashiers.map((c) => <tr key={c.user_id}><td><b>{c.name}</b></td><td>{money(c.cash)}</td><td>{money(c.mobile_money)}</td><td>{c.orders_entered}</td><td>{c.shifts_closed}</td><td style={{ color: Number(c.variance) !== 0 ? 'var(--danger)' : undefined }}>{money(c.variance)}</td></tr>)}
                </tbody></table>
              </section>)}
          </div>
        </>
      )}
    </>
  )
}

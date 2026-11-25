import { Download } from 'lucide-react'
import { useState } from 'react'
import { ApiError, api, downloadFile, type Page } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Empty, ErrorState, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'

type Finance = {
  range: { from: string; to: string }
  orders: { count: number; booked: string; subtotal: string; discounts: string; tax: string; delivery_fees: string }
  income: { collected: string; refunds: string; sales_received: string; catering_received: string; total_received: string; by_method: Record<string, string> }
  expenses: { payroll_paid: string; payroll_gross: string; payroll_records: number; statutory_withheld: string; employer_contributions: string; payroll_cost: string; recorded: string; by_category: { category: string; amount: string }[]; total: string }
  operating_result: string
  receivables: { orders: string; catering: string; invoices: string; total: string }
  cash_control: { shifts_closed: number; shortages: string; overages: string; net_variance: string }
  trend: { month: string; sales_received: string; catering_received: string; payroll_paid: string; operating_result: string }[]
  by_branch: { branch: string; orders: number; booked: string; tax: string; collected: string; refunds: string; net: string }[]
  notes: string[]
}
type Analytics = {
  orders: number; average_order_value: string; cancellation_rate_percent: string; timezone: string
  by_hour: { hour: number; orders: number; booked: string }[]
  by_weekday: { day: string; orders: number; booked: string }[]
  by_source: { source: string; orders: number; booked: string }[]
  by_fulfilment: { fulfilment: string; orders: number; booked: string }[]
  customers: { ordering: number; repeat: number; repeat_rate_percent: string }
}
type AuditRow = { id: number; created_at: string; action: string; actor: string | null; object_type: string; object_id: string; metadata: Record<string, unknown> }

const iso = (d: Date) => d.toISOString().slice(0, 10)
const msg = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

function Range({ from, to, setFrom, setTo }: { from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void }) {
  return (
    <>
      <label>From <input className="input" style={{ width: 150 }} type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></label>
      <label>To <input className="input" style={{ width: 150 }} type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></label>
    </>
  )
}

export default function Reports() {
  useDocumentTitle('Reports')
  const { me } = useAuth()
  const isAdmin = me?.role === 'restaurant_admin' || me?.role === 'platform_admin'
  const [tab, setTab] = useState<'finance' | 'analytics' | 'audit'>(isAdmin ? 'finance' : 'analytics')
  const tabs = [...(isAdmin ? [['finance', 'Financial summary']] : []), ['analytics', 'Sales analytics'], ...(isAdmin ? [['audit', 'Audit trail']] : [])] as [typeof tab, string][]
  return (
    <>
      <h1 className="page-title">Reports</h1>
      <div className="toolbar" role="tablist" aria-label="Report sections">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={`btn sm ${tab === k ? '' : 'secondary'}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === 'finance' && isAdmin && <FinanceTab />}
      {tab === 'analytics' && <AnalyticsTab />}
      {tab === 'audit' && isAdmin && <AuditTab />}
    </>
  )
}

function FinanceTab() {
  const { money } = useSite()
  const toast = useToast()
  const today = new Date()
  const [from, setFrom] = useState(iso(new Date(today.getTime() - 29 * 86400000)))
  const [to, setTo] = useState(iso(today))
  const r = useAsync(() => api<Finance>('/reports/finance/', { params: { from, to } }), [from, to])
  const d = r.data
  const invalid = from > to
  const neg = d && d.operating_result.startsWith('-')
  return (
    <>
      <div className="toolbar">
        <Range from={from} to={to} setFrom={setFrom} setTo={setTo} />
        <button className="btn sm secondary" disabled={invalid} onClick={() => downloadFile(`/reports/finance/export/?from=${from}&to=${to}`, `financial-summary-${from}-to-${to}.csv`).catch((e) => toast(msg(e)))}><Download size={14} aria-hidden /> CSV</button>
      </div>
      {invalid && <div className="alert error">The start date must not be after the end date.</div>}
      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {r.loading && !d ? <Skeleton h={220} /> : d && (
        <>
          <div className="grid g3" style={{ marginBottom: 16 }}>
            <div className="card stat"><span className="muted">Sales received</span><b>{money(d.income.sales_received)}</b><span className="muted">{money(d.income.collected)} collected − {money(d.income.refunds)} refunds</span></div>
            <div className="card stat"><span className="muted">Catering received</span><b>{money(d.income.catering_received)}</b></div>
            <div className="card stat"><span className="muted">Payroll cost</span><b>{money(d.expenses.payroll_cost)}</b><span className="muted">{money(d.expenses.payroll_paid)} net pay · {money(d.expenses.statutory_withheld)} tax and pension withheld · {money(d.expenses.employer_contributions)} employer contributions</span></div>
            <div className="card stat"><span className="muted">Other expenses</span><b>{money(d.expenses.recorded)}</b><span className="muted">{d.expenses.by_category.map((c) => `${c.category} ${money(c.amount)}`).join(' · ') || 'None recorded'}</span></div>
            <div className="card stat"><span className="muted">Operating result</span><b style={{ color: neg ? 'var(--danger, #c0392b)' : undefined }}>{money(d.operating_result)}</b><span className="muted">Cash basis: received money minus payroll and recorded expenses. Not an accounting profit.</span></div>
            <div className="card stat"><span className="muted">Receivables</span><b>{money(d.receivables.total)}</b><span className="muted">{money(d.receivables.orders)} orders · {money(d.receivables.catering)} catering · {money(d.receivables.invoices)} invoices</span></div>
            <div className="card stat"><span className="muted">Tax on orders</span><b>{money(d.orders.tax)}</b><span className="muted">{d.orders.count} orders · {money(d.orders.discounts)} discounts</span></div>
          </div>
          <div className="grid g2">
            <div className="card table-wrap"><h3 style={{ marginTop: 0 }}>Monthly trend</h3>
              {!d.trend.length ? <Empty title="No money moved in this period" /> : (
                <table className="tbl"><thead><tr><th>Month</th><th>Sales</th><th>Catering</th><th>Payroll</th><th>Result</th></tr></thead><tbody>
                  {d.trend.map((t) => <tr key={t.month}><td>{t.month}</td><td>{money(t.sales_received)}</td><td>{money(t.catering_received)}</td><td>{money(t.payroll_paid)}</td><td><b>{money(t.operating_result)}</b></td></tr>)}
                </tbody></table>)}
            </div>
            <div className="card table-wrap"><h3 style={{ marginTop: 0 }}>By branch (orders)</h3>
              <table className="tbl"><thead><tr><th>Branch</th><th>Orders</th><th>Booked</th><th>Net received</th></tr></thead><tbody>
                {d.by_branch.map((b) => <tr key={b.branch}><td>{b.branch}</td><td>{b.orders}</td><td>{money(b.booked)}</td><td>{money(b.net)}</td></tr>)}
              </tbody></table>
            </div>
            <div className="card"><h3 style={{ marginTop: 0 }}>Payment methods</h3>
              {Object.entries(d.income.by_method).length === 0 ? <p className="muted">No payments.</p> : Object.entries(d.income.by_method).map(([k, v]) => <p key={k} style={{ margin: '4px 0' }}>{k.replace('_', ' ')}: <b>{money(v)}</b></p>)}
            </div>
            <div className="card"><h3 style={{ marginTop: 0 }}>Cash control</h3>
              <p style={{ margin: '4px 0' }}>{d.cash_control.shifts_closed} shift(s) closed</p>
              <p style={{ margin: '4px 0' }}>Shortages: <b>{money(d.cash_control.shortages)}</b> · Overages: <b>{money(d.cash_control.overages)}</b></p>
            </div>
          </div>
          <p className="muted" style={{ marginTop: 12 }}>{d.notes.join(' ')}</p>
        </>
      )}
    </>
  )
}

function Bars({ rows, label, value }: { rows: { k: string; v: number; t: string }[]; label: string; value: string }) {
  const max = Math.max(1, ...rows.map((r) => r.v))
  return (
    <div role="img" aria-label={`${label}: ${value}`} style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 120 }}>
      {rows.map((r) => <div key={r.k} title={`${r.k}: ${r.v} order(s), ${r.t}`} style={{ flex: 1, background: 'var(--primary, #1f7a6d)', height: `${(r.v / max) * 100}%`, minHeight: r.v ? 3 : 1, opacity: r.v ? 1 : 0.25, borderRadius: 2 }} />)}
    </div>
  )
}

function AnalyticsTab() {
  const { money } = useSite()
  const today = new Date()
  const [from, setFrom] = useState(iso(new Date(today.getTime() - 29 * 86400000)))
  const [to, setTo] = useState(iso(today))
  const [branch, setBranch] = useState('')
  const branches = useAsync(() => api<Page<{ id: number; name: string }>>('/restaurants/branches/', { params: { page_size: 100 } }), [])
  const r = useAsync(() => api<Analytics>('/reports/analytics/', { params: { from, to, branch } }), [from, to, branch])
  const d = r.data
  const peak = d ? [...d.by_hour].sort((a, b) => b.orders - a.orders)[0] : null
  return (
    <>
      <div className="toolbar">
        <Range from={from} to={to} setFrom={setFrom} setTo={setTo} />
        {(branches.data?.results.length ?? 0) > 1 && <select className="input" style={{ maxWidth: 180 }} aria-label="Branch" value={branch} onChange={(e) => setBranch(e.target.value)}><option value="">All my branches</option>{branches.data!.results.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>}
      </div>
      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {r.loading && !d ? <Skeleton h={220} /> : d && (
        <>
          <div className="grid g3" style={{ marginBottom: 16 }}>
            <div className="card stat"><span className="muted">Orders</span><b>{d.orders}</b></div>
            <div className="card stat"><span className="muted">Average order value</span><b>{money(d.average_order_value)}</b></div>
            <div className="card stat"><span className="muted">Cancellation rate</span><b>{d.cancellation_rate_percent}%</b></div>
            <div className="card stat"><span className="muted">Repeat customers</span><b>{d.customers.repeat_rate_percent}%</b><span className="muted">{d.customers.repeat} of {d.customers.ordering} signed-in customers</span></div>
          </div>
          <div className="card" style={{ marginBottom: 16 }}>
            <h3 style={{ marginTop: 0 }}>Orders by hour ({d.timezone}){peak && peak.orders > 0 ? ` · busiest ${String(peak.hour).padStart(2, '0')}:00` : ''}</h3>
            <Bars rows={d.by_hour.map((h) => ({ k: `${String(h.hour).padStart(2, '0')}:00`, v: h.orders, t: money(h.booked) }))} label="Orders by hour" value={d.by_hour.map((h) => h.orders).join(',')} />
            <div className="muted" style={{ display: 'flex', justifyContent: 'space-between', fontSize: '.75rem' }}><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>
          </div>
          <div className="grid g2">
            <div className="card table-wrap"><h3 style={{ marginTop: 0 }}>By weekday</h3><table className="tbl"><thead><tr><th>Day</th><th>Orders</th><th>Booked</th></tr></thead><tbody>{d.by_weekday.map((w) => <tr key={w.day}><td>{w.day}</td><td>{w.orders}</td><td>{money(w.booked)}</td></tr>)}</tbody></table></div>
            <div className="card table-wrap"><h3 style={{ marginTop: 0 }}>How orders arrive</h3><table className="tbl"><thead><tr><th>Channel</th><th>Orders</th><th>Booked</th></tr></thead><tbody>
              {d.by_source.map((s) => <tr key={s.source}><td>{s.source}</td><td>{s.orders}</td><td>{money(s.booked)}</td></tr>)}
              {d.by_fulfilment.map((s) => <tr key={`f-${s.fulfilment}`}><td>{s.fulfilment}</td><td>{s.orders}</td><td>{money(s.booked)}</td></tr>)}
            </tbody></table></div>
          </div>
        </>
      )}
    </>
  )
}

function AuditTab() {
  const [f, setF] = useState({ action: '', from: '', to: '' })
  const [page, setPage] = useState(1)
  const list = useAsync(() => api<Page<AuditRow>>('/reports/audit/', { params: { ...f, page } }), [f.action, f.from, f.to, page])
  return (
    <>
      <div className="toolbar">
        <input className="input" style={{ maxWidth: 240 }} placeholder="Action, e.g. payroll." aria-label="Filter by action" value={f.action} onChange={(e) => { setF({ ...f, action: e.target.value }); setPage(1) }} />
        <label>From <input className="input" style={{ width: 150 }} type="date" value={f.from} onChange={(e) => { setF({ ...f, from: e.target.value }); setPage(1) }} /></label>
        <label>To <input className="input" style={{ width: 150 }} type="date" value={f.to} onChange={(e) => { setF({ ...f, to: e.target.value }); setPage(1) }} /></label>
      </div>
      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
      <div className="card table-wrap">
        {list.loading && !list.data ? <Skeleton h={100} /> : !list.data?.results.length ? <Empty title="No audit entries" /> : (
          <table className="tbl"><thead><tr><th>When</th><th>Action</th><th>By</th><th>Record</th><th>Details</th></tr></thead><tbody>
            {list.data.results.map((l) => <tr key={l.id}><td>{new Date(l.created_at).toLocaleString()}</td><td>{l.action}</td><td>{l.actor ?? 'System'}</td><td>{l.object_type ? `${l.object_type} #${l.object_id}` : '–'}</td><td className="muted" style={{ maxWidth: 260, overflowWrap: 'anywhere' }}>{Object.keys(l.metadata).length ? JSON.stringify(l.metadata) : '–'}</td></tr>)}
          </tbody></table>)}
      </div>
      {list.data && (list.data.next || list.data.previous) && <div className="toolbar" style={{ marginTop: 12 }}><button className="btn sm secondary" disabled={!list.data.previous} onClick={() => setPage(page - 1)}>Previous</button><span className="muted">Page {page}</span><button className="btn sm secondary" disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next</button></div>}
    </>
  )
}

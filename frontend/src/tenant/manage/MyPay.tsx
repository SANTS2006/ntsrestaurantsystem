import { Download } from 'lucide-react'
import { downloadFile, api } from '../../lib/api'
import { Empty, ErrorState, Skeleton, useAsync, useDocumentTitle, useToast } from '../../ui/kit'
import { useSite } from '../SiteContext'

type Slip = { id: number; period: string; status: string; gross: string; total_deductions: string; net: string; paid_on: string | null; receipt_number: string | null; lines: { type: string; name: string; amount: string }[] }
type Data = { structure: { basic_salary: string; frequency: string; effective_from: string; version: number; components: { type: string; name: string; mode: string; amount: string }[] } | null; slips: Slip[] }

export default function MyPay() {
  useDocumentTitle('My pay')
  const { money } = useSite()
  const toast = useToast()
  const d = useAsync(() => api<Data>('/payroll/me/'), [])
  return (
    <>
      <h1 className="page-title">My pay</h1>
      <p className="muted">Only you can see this page. It shows your own salary and pay slips.</p>
      {d.error && <ErrorState message={d.error} onRetry={d.reload} />}
      {!d.data ? <Skeleton h={140} /> : (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <h3 style={{ marginTop: 0 }}>Current salary</h3>
            {d.data.structure ? (
              <>
                <p style={{ margin: 0 }}><b>{money(d.data.structure.basic_salary)}</b> basic · {d.data.structure.frequency} · since {d.data.structure.effective_from}</p>
                {d.data.structure.components.map((c, i) => <p key={i} className="muted" style={{ margin: '4px 0 0' }}>{c.name}: {c.mode === 'percent_of_basic' ? `${c.amount}% of basic` : money(c.amount)}</p>)}
              </>
            ) : <p className="muted">No salary has been set up for you yet.</p>}
          </div>
          <h3>Pay slips</h3>
          {!d.data.slips.length ? <Empty title="No pay slips yet">Slips appear here once your pay has been approved.</Empty> : (
            <div className="card table-wrap"><table className="tbl"><thead><tr><th>Month</th><th>Gross</th><th>Deductions</th><th>Net pay</th><th>Status</th><th /></tr></thead><tbody>
              {d.data.slips.map((s) => (
                <tr key={s.id}><td><b>{s.period}</b></td><td>{money(s.gross)}</td><td>{money(s.total_deductions)}</td><td><b>{money(s.net)}</b></td><td><span className={`badge ${s.status === 'paid' ? 'active' : ''}`}>{s.status === 'paid' ? `Paid ${s.paid_on}` : 'Approved, awaiting payment'}</span></td>
                  <td>{s.status === 'paid' && <button className="btn sm" onClick={() => downloadFile(`/payroll/me/records/${s.id}/pdf/`, `${s.receipt_number}.pdf`).catch(() => toast('Could not download the PDF.'))}><Download size={16} aria-hidden /> PDF</button>}</td></tr>))}
            </tbody></table></div>
          )}
        </>
      )}
    </>
  )
}

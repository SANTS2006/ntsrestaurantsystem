import { api } from '../../lib/api'
import { ErrorState, Skeleton, useAsync, useDocumentTitle } from '../../ui/kit'

type Stats = Record<'restaurants_total' | 'restaurants_active' | 'restaurants_suspended' | 'branches_total' | 'customers_total' | 'employees_total', number>
const labels: [keyof Stats, string][] = [
  ['restaurants_total', 'Total restaurants'], ['restaurants_active', 'Active'], ['restaurants_suspended', 'Suspended'],
  ['branches_total', 'Branches'], ['customers_total', 'Registered customers'], ['employees_total', 'Employees'],
]

export default function Dashboard() {
  useDocumentTitle('Platform dashboard')
  const { data, loading, error, reload } = useAsync(() => api<Stats>('/platform/dashboard/'), [])
  return (
    <>
      <h1 className="page-title">Dashboard</h1>
      {error && <ErrorState message={error} onRetry={reload} />}
      <div className="grid g3">
        {labels.map(([k, l]) => (
          <div className="card stat" key={k}>
            <span className="muted">{l}</span>
            {loading ? <Skeleton h={34} w="60%" /> : <b>{data?.[k] ?? '–'}</b>}
          </div>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 20 }}>Order, payment and revenue figures will appear here once ordering and payments are enabled.</p>
    </>
  )
}

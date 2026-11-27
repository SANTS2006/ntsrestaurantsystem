// Which ticked payroll records each bulk action applies to. The server checks every record again.
export type BulkAction = 'submit' | 'approve' | 'reject' | 'pay' | 'cancel'
export type BulkRecord = { id: number; status: string; net: string; employee: { name: string } }
export type BulkResult = { done: { id: number; name: string; net: string; reference: string; receipt_number: string | null }[]; failed: { id: number; name: string; reason: string }[] }

const FROM: Record<BulkAction, string[]> = { submit: ['draft'], approve: ['submitted'], reject: ['submitted'], pay: ['approved'], cancel: ['draft', 'submitted', 'approved', 'rejected'] }

export function eligibleFor<T extends BulkRecord>(action: BulkAction, rows: T[], isAdmin: boolean): T[] {
  if (!isAdmin && (action === 'approve' || action === 'reject')) return []
  return rows.filter((r) => FROM[action].includes(r.status))
}

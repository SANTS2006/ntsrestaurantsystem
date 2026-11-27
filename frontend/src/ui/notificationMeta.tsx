import { Banknote, Bell, BellRing, CalendarDays, CircleCheck, Inbox, QrCode, Receipt } from 'lucide-react'

const LABELS: Record<string, string> = { order_new: 'New order', order_ready: 'Ready', order_update: 'Order update', payment: 'Payment', reservation: 'Reservation', request: 'Table request', catering: 'Catering', contact_message: 'Website message', payroll: 'Payroll', salary: 'Salary' }

export const kindLabel = (kind: string) => LABELS[kind] ?? 'Notification'

export function kindIcon(kind: string, size = 18) {
  const p = { size, 'aria-hidden': true } as const
  if (kind === 'order_ready') return <BellRing {...p} />
  if (kind === 'order_new') return <Receipt {...p} />
  if (kind === 'order_update') return <CircleCheck {...p} />
  if (kind === 'payment' || kind === 'payroll' || kind === 'salary') return <Banknote {...p} />
  if (kind === 'contact_message') return <Inbox {...p} />
  if (kind === 'reservation' || kind === 'catering') return <CalendarDays {...p} />
  if (kind === 'request') return <QrCode {...p} />
  return <Bell {...p} />
}

export function ago(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return new Date(iso).toLocaleDateString()
}

/** Where this person's notification pages live. */
export function notificationsBase(role: string | null | undefined): string {
  if (role === 'customer') return '/account/notifications'
  if (role === 'platform_admin' && !window.location.pathname.includes('/manage')) return '/admin/notifications'
  return '/manage/notifications'
}

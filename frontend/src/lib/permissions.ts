// What each role may DO, mirroring the permission classes of the API (backend/apps/*/views.py). Screens use this so people only see
// the modules and buttons they can actually use. The server still enforces every rule: this file never grants anything.
const ADMIN = ['platform_admin', 'restaurant_admin']
const MANAGER_UP = [...ADMIN, 'manager']
const CASHIER_UP = [...MANAGER_UP, 'cashier']
const FLOOR_STAFF = ['kitchen', 'waiter', 'waitress', 'delivery']
export const STAFF_ALL = [...CASHIER_UP, ...FLOOR_STAFF]

const ABILITIES = {
  'orders.view': STAFF_ALL,
  'payments.cash': CASHIER_UP, // IsCashierOrAbove
  'payments.refund': MANAGER_UP, // IsManagerOrAbove
  'payments.receipt': [...CASHIER_UP, 'waiter', 'waitress'], // the receipt view's role list
  'pos.use': CASHIER_UP,
  'floor.use': CASHIER_UP,
  'kitchen.use': [...MANAGER_UP, 'kitchen'],
  'manage.use': MANAGER_UP, // dashboard, catalogue, stock, finance, staff, reports, payroll, tables, catering, shifts
  'admin.use': ADMIN, // branches, website content, payroll settings, financial summary, audit trail
  'mypay.view': [...MANAGER_UP.filter((r) => r !== 'platform_admin'), 'cashier', ...FLOOR_STAFF],
} as const

export type Ability = keyof typeof ABILITIES

export function can(role: string | null | undefined, ability: Ability): boolean {
  return !!role && (ABILITIES[ability] as readonly string[]).includes(role)
}

const SECTION_ABILITY: Record<string, Ability> = {
  dashboard: 'manage.use', customers: 'manage.use', stock: 'manage.use', finance: 'manage.use', tables: 'manage.use', catering: 'manage.use',
  shifts: 'manage.use', products: 'manage.use', categories: 'manage.use', inventory: 'manage.use', reports: 'manage.use', staff: 'manage.use',
  payroll: 'manage.use', services: 'manage.use', gallery: 'manage.use', 'website-contact': 'manage.use',
  branches: 'admin.use', site: 'admin.use', builder: 'admin.use', cashier: 'pos.use', floor: 'floor.use', kitchen: 'kitchen.use', orders: 'orders.view', 'my-pay': 'mypay.view',
}

/** May this role open the workspace page /manage/<section>? Pages not listed (profile, security, notifications) are for all staff. */
export function canOpen(role: string, section: string): boolean {
  const need = SECTION_ABILITY[section]
  return need ? can(role, need) : STAFF_ALL.includes(role)
}

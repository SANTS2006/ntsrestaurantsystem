import { describe, expect, it } from 'vitest'
import { can, canOpen } from '../lib/permissions'

// Mirrors the API's rules: a role must never be offered an action the server would refuse.
describe('role abilities', () => {
  it('only till staff can take cash; only managers and up can refund', () => {
    for (const r of ['kitchen', 'waiter', 'waitress', 'delivery', 'customer', null]) expect(can(r, 'payments.cash')).toBe(false)
    for (const r of ['cashier', 'manager', 'restaurant_admin', 'platform_admin']) expect(can(r, 'payments.cash')).toBe(true)
    expect(can('cashier', 'payments.refund')).toBe(false)
    expect(can('manager', 'payments.refund')).toBe(true)
  })
  it('pages open only for roles that can act on them', () => {
    for (const r of ['kitchen', 'waiter', 'waitress', 'delivery']) {
      for (const s of ['dashboard', 'products', 'staff', 'finance', 'cashier', 'floor', 'branches', 'site']) expect(canOpen(r, s)).toBe(false)
      expect(canOpen(r, 'orders')).toBe(true)
      expect(canOpen(r, 'profile')).toBe(true)
      expect(canOpen(r, 'notifications')).toBe(true)
    }
    expect(canOpen('kitchen', 'kitchen')).toBe(true)
    expect(canOpen('cashier', 'kitchen')).toBe(false)
    expect(canOpen('cashier', 'cashier')).toBe(true)
    expect(canOpen('manager', 'branches')).toBe(false)
    expect(canOpen('restaurant_admin', 'branches')).toBe(true)
    expect(canOpen('platform_admin', 'my-pay')).toBe(false)
    expect(canOpen('customer', 'orders')).toBe(false)
  })
})

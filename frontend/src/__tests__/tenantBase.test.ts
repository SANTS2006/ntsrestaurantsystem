import { describe, expect, it } from 'vitest'
import { tenantBase } from '../lib/config'

// Restaurants are addressed by path on the platform host: https://<platform domain>/<slug>/...
describe('tenantBase', () => {
  it('uses the first path segment as the restaurant slug on the platform host', () => {
    expect(tenantBase('/alpha/menu', 'localhost')).toBe('/alpha')
    expect(tenantBase('/alpha', 'localhost')).toBe('/alpha')
    expect(tenantBase('/ocean-view/manage/orders', 'localhost')).toBe('/ocean-view')
  })
  it('leaves platform pages without a prefix', () => {
    for (const p of ['/', '/pricing', '/features', '/login', '/admin/restaurants', '/legal/privacy-policy', '/contact']) expect(tenantBase(p, 'localhost')).toBe('')
  })
  it('has no prefix on a custom domain', () => {
    expect(tenantBase('/menu', 'order.alpha-food.com')).toBe('')
  })
})

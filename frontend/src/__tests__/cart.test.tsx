import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { CartProvider, useCart } from '../tenant/cart'

const wrapper = ({ children }: { children: ReactNode }) => <CartProvider>{children}</CartProvider>
const base = { product_id: 1, name: 'Rice', image: null, variation_id: 2, variation_name: 'Large', addons: [{ id: 5, name: 'Egg', quantity: 1 }], quantity: 1, instructions: '' }

describe('cart', () => {
  beforeEach(() => localStorage.clear())

  it('merges identical lines and keeps different choices separate', () => {
    const { result } = renderHook(() => useCart(), { wrapper })
    act(() => { result.current.add(base); result.current.add(base); result.current.add({ ...base, instructions: 'no pepper' }) })
    expect(result.current.lines).toHaveLength(2)
    expect(result.current.count).toBe(3)
  })

  it('clamps quantities to 1..50', () => {
    const { result } = renderHook(() => useCart(), { wrapper })
    act(() => result.current.add(base))
    const key = result.current.lines[0].key
    act(() => result.current.setQty(key, 999))
    expect(result.current.lines[0].quantity).toBe(50)
    act(() => result.current.setQty(key, 0))
    expect(result.current.lines[0].quantity).toBe(1)
  })

  it('never stores or sends prices; the API payload holds only ids, quantities and text', () => {
    const { result } = renderHook(() => useCart(), { wrapper })
    act(() => result.current.add({ ...base, quantity: 2, instructions: 'extra sauce' }))
    expect(JSON.stringify(localStorage.getItem('nts.cart.v1'))).not.toMatch(/price|total/i)
    expect(result.current.apiItems()).toEqual([{ product_id: 1, variation_id: 2, quantity: 2, addons: [{ id: 5, quantity: 1 }], instructions: 'extra sauce' }])
  })

  it('survives a reload and tolerates corrupt storage', () => {
    const first = renderHook(() => useCart(), { wrapper })
    act(() => first.result.current.add(base))
    const again = renderHook(() => useCart(), { wrapper })
    expect(again.result.current.lines).toHaveLength(1)
    localStorage.setItem('nts.cart.v1', '{not json')
    expect(renderHook(() => useCart(), { wrapper }).result.current.lines).toEqual([])
  })
})

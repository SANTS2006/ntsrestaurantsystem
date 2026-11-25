import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

/** A cart line stores only what the customer chose. Prices are never stored: the server prices every cart. */
export type CartLine = {
  key: string
  product_id: number
  name: string
  image: string | null
  variation_id: number | null
  variation_name: string
  addons: { id: number; name: string; quantity: number }[]
  quantity: number
  instructions: string
}

type Ctx = {
  lines: CartLine[]
  count: number
  add: (l: Omit<CartLine, 'key'>) => void
  setQty: (key: string, q: number) => void
  remove: (key: string) => void
  clear: () => void
  apiItems: () => { product_id: number; variation_id: number | null; quantity: number; addons: { id: number; quantity: number }[]; instructions: string }[]
}

const KEY = 'nts.cart.v1'
const CartCtx = createContext<Ctx | null>(null)
export const useCart = () => {
  const c = useContext(CartCtx)
  if (!c) throw new Error('useCart outside CartProvider')
  return c
}

const lineKey = (l: Omit<CartLine, 'key'>) =>
  JSON.stringify([l.product_id, l.variation_id, [...l.addons].sort((a, b) => a.id - b.id).map((a) => [a.id, a.quantity]), l.instructions.trim()])

function load(): CartLine[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

export function CartProvider({ children }: { children: ReactNode }) {
  const [lines, setLines] = useState<CartLine[]>(load)
  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(lines)) } catch { /* storage unavailable: cart lasts for this page only */ }
  }, [lines])
  // keep tabs in sync
  useEffect(() => {
    const on = (e: StorageEvent) => e.key === KEY && setLines(load())
    window.addEventListener('storage', on)
    return () => window.removeEventListener('storage', on)
  }, [])

  const add = useCallback((l: Omit<CartLine, 'key'>) => {
    const key = lineKey(l)
    setLines((cur) => {
      const hit = cur.find((x) => x.key === key)
      return hit ? cur.map((x) => (x.key === key ? { ...x, quantity: Math.min(50, x.quantity + l.quantity) } : x)) : [...cur, { ...l, key }]
    })
  }, [])
  const setQty = useCallback((key: string, q: number) => setLines((cur) => cur.map((x) => (x.key === key ? { ...x, quantity: Math.max(1, Math.min(50, q)) } : x))), [])
  const remove = useCallback((key: string) => setLines((cur) => cur.filter((x) => x.key !== key)), [])
  const clear = useCallback(() => setLines([]), [])
  const apiItems = useCallback(() => lines.map((l) => ({ product_id: l.product_id, variation_id: l.variation_id, quantity: l.quantity, addons: l.addons.map((a) => ({ id: a.id, quantity: a.quantity })), instructions: l.instructions })), [lines])

  const value = useMemo(() => ({ lines, count: lines.reduce((n, l) => n + l.quantity, 0), add, setQty, remove, clear, apiItems }), [lines, add, setQty, remove, clear, apiItems])
  return <CartCtx.Provider value={value}>{children}</CartCtx.Provider>
}

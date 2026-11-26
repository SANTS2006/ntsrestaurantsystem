import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useSeo } from '../tenant/seo'
import { formatMoney } from '../tenant/SiteContext'

function Probe({ path, ld }: { path: string; ld?: object }) {
  useSeo({ title: 'Dish | Ocean', description: 'Tasty', path, jsonLd: ld })
  return null
}

describe('formatMoney', () => {
  it('formats valid ISO currencies', () => {
    expect(formatMoney('39.5', 'SLE')).toBe('SLE 39.50')
    expect(formatMoney(1250)).toBe('SLE 1,250.00')
  })
  it('falls back safely for unknown currency codes instead of throwing', () => {
    expect(formatMoney('39', 'ZZZ1')).toBe('ZZZ1 39.00')
  })
})

describe('useSeo', () => {
  it('sets title, description, canonical, Open Graph and JSON-LD, and removes JSON-LD when absent', () => {
    const { rerender } = render(<Probe path="/menu/x" ld={{ '@type': 'Product', name: '</script><b>x' }} />)
    expect(document.title).toBe('Dish | Ocean')
    expect(document.querySelector('meta[name=description]')?.getAttribute('content')).toBe('Tasty')
    expect(document.querySelector('link[rel=canonical]')?.getAttribute('href')).toBe(`${window.location.origin}/menu/x`)
    expect(document.querySelector('meta[property="og:title"]')?.getAttribute('content')).toBe('Dish | Ocean')
    const script = document.getElementById('jsonld')!
    expect(script.children.length).toBe(0) // injected as text, not parsed as markup
    expect(JSON.parse(script.textContent!).name).toBe('</script><b>x')
    rerender(<Probe path="/menu/x" />)
    expect(document.getElementById('jsonld')).toBeNull()
  })
})

import { renderHook } from '@testing-library/react'
import { useAsync } from '../ui/kit'

describe('useAsync', () => {
  it('returns a stable reload function so effects that depend on it cannot loop', async () => {
    const { result, rerender } = renderHook(() => useAsync(() => Promise.resolve(1), []))
    const first = result.current.reload
    rerender()
    expect(result.current.reload).toBe(first)
  })
})

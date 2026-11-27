import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { destination } from '../tenant/CustomerAuth'
import { eligibleFor } from '../tenant/manage/payrollRules'
import { boldSelection, plain, splitBold } from '../ui/boldText'
import { directionsUrl, embedUrl, fullAddress, mapQuery, parseCoordinates } from '../ui/geo'
import { LocationCard } from '../ui/Maps'
import { printWhenReady } from '../ui/print'
import { RichText } from '../ui/RichText'

describe('bold website text', () => {
  it('splits marked words and leaves the rest alone', () => {
    expect(splitBold('Fresh **fish** daily')).toEqual([{ text: 'Fresh ', bold: false }, { text: 'fish', bold: true }, { text: ' daily', bold: false }])
    expect(plain('**Open** every **day**')).toBe('Open every day')
  })
  it('wraps a selection, keeps spaces outside, and removes bold when pressed again', () => {
    const on = boldSelection('We are open today', 7, 12)
    expect(on.value).toBe('We are **open** today')
    expect(boldSelection(on.value, on.start, on.end).value).toBe('We are open today')
  })
  it('renders bold words without reading any HTML', () => {
    const { container } = render(<RichText text={'**Hot** <img src=x onerror=alert(1)>'} />)
    expect(container.querySelector('strong')?.textContent).toBe('Hot')
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('locations', () => {
  it('prefers the exact pin and otherwise searches for the written address', () => {
    expect(mapQuery({ address: '12 Beach Road', latitude: '8.484400', longitude: '-13.234400' })).toBe('8.4844,-13.2344')
    expect(mapQuery({ address: ' 12 Beach Road ', latitude: null, longitude: null })).toBe('12 Beach Road')
    expect(mapQuery({ address: '', latitude: '', longitude: '' })).toBe('')
    expect(embedUrl('A & B')).toContain('q=A%20%26%20B')
    expect(directionsUrl('8.1,-13.2')).toContain('destination=8.1%2C-13.2')
  })
  it('reads coordinates from what people paste', () => {
    const pin = { latitude: '8.4844', longitude: '-13.2344' }
    expect(parseCoordinates('8.4844, -13.2344')).toEqual(pin)
    expect(parseCoordinates('https://www.google.com/maps/@8.4844,-13.2344,17z')).toEqual(pin)
    expect(parseCoordinates('https://maps.google.com/?q=8.4844,-13.2344')).toEqual(pin)
    expect(parseCoordinates('https://www.google.com/maps/place/X/@8.0,-13.0,15z/data=!3d8.4844!4d-13.2344')).toEqual(pin)
    expect(parseCoordinates('200, 10')).toBeNull()
    expect(parseCoordinates('12 Beach Road')).toBeNull()
  })
  it('joins an address without repeating parts', () => {
    expect(fullAddress('12 Beach Road, Freetown', 'Freetown', 'Sierra Leone')).toBe('12 Beach Road, Freetown, Sierra Leone')
  })
  it('shows the address in words, on a map and with directions', () => {
    render(<MemoryRouter><LocationCard name="Lumley" place={{ address: '12 Beach Road, Freetown' }} /></MemoryRouter>)
    expect(screen.getByText('12 Beach Road, Freetown')).toBeTruthy()
    expect(screen.getByTitle('Map showing Lumley').getAttribute('src')).toContain('output=embed')
    expect(screen.getByRole('link', { name: /get directions/i }).getAttribute('href')).toContain('destination=12%20Beach%20Road')
  })
})

describe('printing', () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })
  it('returns people to the receipt after signing in', () => {
    expect(destination('cashier', '/receipts/7?print=1')).toBe('/receipts/7?print=1')
    expect(destination('cashier', null)).toBe('/manage')
    expect(destination('customer', '/manage/payroll')).toBe('/account')
    expect(destination('customer', '/receipts/7')).toBe('/receipts/7')
  })
  it('opens the print window once, and not at all when cancelled', async () => {
    vi.useFakeTimers()
    const print = vi.fn()
    window.print = print
    const started = vi.fn()
    printWhenReady(document.createElement('div'), started)
    await vi.advanceTimersByTimeAsync(3000)
    expect(print).toHaveBeenCalledTimes(1)
    expect(started).toHaveBeenCalledTimes(1)
    printWhenReady(document.createElement('div'))()
    await vi.advanceTimersByTimeAsync(3000)
    expect(print).toHaveBeenCalledTimes(1)
  })
})

describe('bulk payroll', () => {
  const rows = ['draft', 'submitted', 'approved', 'paid'].map((status, id) => ({ id, status, net: '10.00', employee: { name: status } }))
  const ids = (a: Parameters<typeof eligibleFor>[0], admin: boolean) => eligibleFor(a, rows, admin).map((r) => r.id)
  it('offers each action only for the records it fits', () => {
    expect(ids('submit', false)).toEqual([0])
    expect(ids('approve', true)).toEqual([1])
    expect(ids('approve', false)).toEqual([])
    expect(ids('pay', false)).toEqual([2])
    expect(ids('cancel', true)).toEqual([0, 1, 2])
  })
})

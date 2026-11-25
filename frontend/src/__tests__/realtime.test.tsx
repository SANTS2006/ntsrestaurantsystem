import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { tokenStore } from '../lib/api'
import { useStaffSocket } from '../lib/realtime'

class FakeSocket {
  static instances: FakeSocket[] = []
  static OPEN = 1
  readyState = 1
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((m: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  url: string
  constructor(url: string) { this.url = url; FakeSocket.instances.push(this) }
  send(d: string) { this.sent.push(d) }
  close() { this.onclose?.({ code: 1000 }) }
}

describe('useStaffSocket', () => {
  beforeEach(() => {
    FakeSocket.instances = []
    sessionStorage.clear()
    tokenStore.set({ access: 'SECRET-ACCESS', refresh: 'r' })
    vi.stubGlobal('WebSocket', FakeSocket)
    vi.useFakeTimers()
  })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

  it('sends the token as the first message, never in the URL, and goes live on "ready"', () => {
    const events: unknown[] = []
    const { result } = renderHook(() => useStaffSocket((e) => events.push(e)))
    const ws = FakeSocket.instances[0]
    expect(ws.url).toMatch(/^ws:\/\/.*\/ws\/staff\/$/)
    expect(ws.url).not.toContain('SECRET')
    act(() => ws.onopen?.())
    expect(JSON.parse(ws.sent[0])).toEqual({ type: 'auth', token: 'SECRET-ACCESS' })
    expect(result.current).toBe('connecting')
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: 'ready', branches: [1] }) }))
    expect(result.current).toBe('live')
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: 'qr.request.created', id: 7 }) }))
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: 'pong' }) }))
    act(() => ws.onmessage?.({ data: 'not json' }))
    expect(events).toEqual([{ type: 'qr.request.created', id: 7 }])
  })

  it('falls back to polling and reconnects with backoff after a dropped connection', () => {
    const { result } = renderHook(() => useStaffSocket(() => {}))
    act(() => FakeSocket.instances[0].onclose?.({ code: 1006 }))
    expect(result.current).toBe('polling')
    act(() => { vi.advanceTimersByTime(1100) })
    expect(FakeSocket.instances.length).toBe(2)
  })

  it('does not retry after the server rejects the login (4403)', () => {
    const { result } = renderHook(() => useStaffSocket(() => {}))
    act(() => FakeSocket.instances[0].onclose?.({ code: 4403 }))
    act(() => { vi.advanceTimersByTime(60000) })
    expect(result.current).toBe('polling')
    expect(FakeSocket.instances.length).toBe(1)
  })

  it('stays in polling mode when there is no signed-in user', () => {
    tokenStore.set(null)
    const { result } = renderHook(() => useStaffSocket(() => {}))
    expect(result.current).toBe('polling')
    expect(FakeSocket.instances.length).toBe(0)
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, tokenStore } from '../lib/api'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('api client', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('unwraps the success envelope and sends the bearer token', async () => {
    tokenStore.set({ access: 'A', refresh: 'R' })
    const f = vi.fn(async () => json({ success: true, data: { ok: 1 } }))
    vi.stubGlobal('fetch', f)
    expect(await api('/x/')).toEqual({ ok: 1 })
    expect((f.mock.calls[0] as unknown[])[1]).toMatchObject({ headers: { Authorization: 'Bearer A' } })
  })

  it('turns error envelopes into ApiError with field errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ success: false, error: { code: 'invalid', message: 'Bad', details: { slug: ['Taken.'] } } }, 400)))
    const err = (await api('/x/', { body: {} }).catch((e: unknown) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.fieldErrors()).toEqual({ slug: 'Taken.' })
  })

  it('refreshes an expired access token once and retries', async () => {
    tokenStore.set({ access: 'old', refresh: 'R' })
    const f = vi.fn()
      .mockResolvedValueOnce(json({ success: false, error: { code: 'x', message: 'expired' } }, 401))
      .mockResolvedValueOnce(json({ success: true, data: { access: 'new', refresh: 'R2' } }))
      .mockResolvedValueOnce(json({ success: true, data: 'done' }))
    vi.stubGlobal('fetch', f)
    expect(await api('/x/')).toBe('done')
    expect(tokenStore.get()).toEqual({ access: 'new', refresh: 'R2' })
  })

  it('clears tokens when refresh fails and reports network errors safely', async () => {
    tokenStore.set({ access: 'old', refresh: 'R' })
    vi.stubGlobal('fetch', vi.fn(async () => json({ success: false, error: { code: 'x', message: 'no' } }, 401)))
    await expect(api('/x/')).rejects.toBeInstanceOf(ApiError)
    expect(tokenStore.get()).toBeNull()
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
    await expect(api('/x/')).rejects.toMatchObject({ code: 'network' })
  })
})

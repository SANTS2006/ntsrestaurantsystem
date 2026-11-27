import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SiteProvider } from '../tenant/SiteContext'
import { NotFound } from '../ui/NotFound'

const respond = (status: number, message: string) =>
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ success: false, error: { code: 'x', message } }), { status })))

describe('404 page', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('says the page is missing, offers a way on and keeps itself out of search engines', () => {
    const { unmount } = render(<MemoryRouter><NotFound links={[{ to: '/', label: 'Back to home' }, { to: '/menu', label: 'View the menu' }]} /></MemoryRouter>)
    expect(screen.getByLabelText('Error 404')).toBeTruthy()
    expect(screen.getByRole('link', { name: /back to home/i }).getAttribute('href')).toBe('/')
    expect(screen.getByRole('link', { name: 'View the menu' }).getAttribute('href')).toBe('/menu')
    expect(document.title).toBe('Page not found (404)')
    expect(document.querySelector('meta[name=robots]')?.getAttribute('content')).toBe('noindex')
    unmount()
    expect(document.querySelector('meta[name=robots]')).toBeNull()
  })

  it('is shown for an address that names no restaurant, with a way back to the main website', async () => {
    respond(404, 'Not found.')
    render(<MemoryRouter><SiteProvider><p>restaurant page</p></SiteProvider></MemoryRouter>)
    expect(await screen.findByText('We could not find this page')).toBeTruthy()
    expect(screen.getByRole('link', { name: /main website/i }).getAttribute('href')).toBe('/')
    expect(screen.queryByText('restaurant page')).toBeNull()
  })

  it('is not shown when the restaurant exists but cannot be loaded', async () => {
    respond(500, 'Server error.')
    render(<MemoryRouter><SiteProvider><p>restaurant page</p></SiteProvider></MemoryRouter>)
    expect(await screen.findByText(/Server error/)).toBeTruthy()
    expect(screen.queryByLabelText('Error 404')).toBeNull()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })
})

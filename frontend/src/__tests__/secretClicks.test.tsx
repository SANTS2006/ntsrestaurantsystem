import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SiteLayout from '../platform/site/SiteLayout'

function setup() {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ success: true, data: { platform_name: 'P', whatsapp_number: '', support_email: '' } }), { status: 200 })))
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<SiteLayout />}><Route index element={<div>home page</div>} /></Route>
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  )
  return screen.getByTestId('secret-area')
}

describe('hidden platform login access', () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }) })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

  it('has no visible login button or link in the navigation', () => {
    setup()
    expect(screen.queryByRole('link', { name: /log ?in|sign ?in/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /log ?in|sign ?in/i })).toBeNull()
  })

  it('does not navigate after four clicks', () => {
    const area = setup()
    for (let i = 0; i < 4; i++) fireEvent.click(area)
    expect(screen.queryByText('login page')).toBeNull()
  })

  it('navigates to the login page after five quick clicks', () => {
    const area = setup()
    for (let i = 0; i < 5; i++) fireEvent.click(area)
    expect(screen.getByText('login page')).toBeTruthy()
  })

  it('restarts the count when clicks are too slow', () => {
    const area = setup()
    for (let i = 0; i < 4; i++) fireEvent.click(area)
    vi.setSystemTime(Date.now() + 5000)
    fireEvent.click(area)
    expect(screen.queryByText('login page')).toBeNull()
  })
})

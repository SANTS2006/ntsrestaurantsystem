import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tokenStore } from '../lib/api'
import { refreshAll, registerRefresh } from '../lib/refresh'
import { ThemeProvider, useTheme } from '../lib/theme'
import { AuthField, RememberRow } from '../ui/Auth'
import { DialogProvider, useConfirm, usePrompt } from '../ui/dialogs'
import { Spinner, setBrand } from '../ui/Loaders'
import { Mail } from 'lucide-react'

function Harness({ onResult }: { onResult: (v: unknown) => void }) {
  const confirm = useConfirm()
  const prompt = usePrompt()
  return (
    <>
      <button onClick={async () => onResult(await confirm({ title: 'Delete it?', message: 'Gone for good.', confirmLabel: 'Delete', danger: true }))}>ask</button>
      <button onClick={async () => onResult(await prompt({ title: 'Why?', label: 'Reason', required: true }))}>ask-text</button>
    </>
  )
}

describe('in-app dialogs (no browser alert boxes)', () => {
  it('confirm resolves true on Confirm, false on Cancel and Escape', async () => {
    const got = vi.fn()
    render(<DialogProvider><Harness onResult={got} /></DialogProvider>)
    fireEvent.click(screen.getByText('ask'))
    expect(screen.getByRole('alertdialog').textContent).toContain('Gone for good.')
    fireEvent.click(screen.getByText('Delete'))
    await waitFor(() => expect(got).toHaveBeenLastCalledWith(true))
    fireEvent.click(screen.getByText('ask'))
    fireEvent.click(screen.getByText('Cancel'))
    await waitFor(() => expect(got).toHaveBeenLastCalledWith(false))
    fireEvent.click(screen.getByText('ask'))
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(got).toHaveBeenLastCalledWith(false))
  })

  it('prompt returns the typed text, insists on a value when required, and null when dismissed', async () => {
    const got = vi.fn()
    render(<DialogProvider><Harness onResult={got} /></DialogProvider>)
    fireEvent.click(screen.getByText('ask-text'))
    fireEvent.click(screen.getByText('Continue'))
    expect(screen.getByText('This is required.')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: '  too slow  ' } })
    fireEvent.click(screen.getByText('Continue'))
    await waitFor(() => expect(got).toHaveBeenLastCalledWith('too slow'))
    fireEvent.click(screen.getByText('ask-text'))
    fireEvent.click(screen.getByText('Cancel'))
    await waitFor(() => expect(got).toHaveBeenLastCalledWith(null))
  })
})

describe('remember me', () => {
  beforeEach(() => { sessionStorage.clear(); localStorage.clear() })
  it('keeps the session in this tab only unless Remember me is ticked', () => {
    tokenStore.set({ access: 'a', refresh: 'r' }, false)
    expect(sessionStorage.length).toBe(1)
    expect(localStorage.length).toBe(0)
    tokenStore.set({ access: 'a', refresh: 'r' }, true)
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(1)
    expect(tokenStore.get()).toEqual({ access: 'a', refresh: 'r' })
  })
  it('a token refresh keeps the original choice, and signing out clears both', () => {
    tokenStore.set({ access: 'a', refresh: 'r' }, true)
    tokenStore.set({ access: 'b', refresh: 'r' })
    expect(localStorage.length).toBe(1)
    tokenStore.set(null)
    expect(tokenStore.get()).toBeNull()
    expect(localStorage.length + sessionStorage.length).toBe(0)
  })
})

describe('theme', () => {
  function Probe() {
    const { resolved, toggle } = useTheme()
    return <button onClick={toggle}>{resolved}</button>
  }
  it('toggles light and dark, remembers the choice and sets the page attribute', () => {
    localStorage.clear()
    render(<ThemeProvider><Probe /></ThemeProvider>)
    const first = screen.getByRole('button').textContent
    fireEvent.click(screen.getByRole('button'))
    const second = screen.getByRole('button').textContent
    expect(second).not.toBe(first)
    expect(document.documentElement.dataset.theme).toBe(second)
    expect(localStorage.getItem('nts.theme')).toBe(second)
  })
})

describe('live refresh and branded loader', () => {
  it('refreshAll reloads everything registered and stops after unregistering', () => {
    const a = vi.fn()
    const off = registerRefresh(a)
    refreshAll()
    expect(a).toHaveBeenCalledTimes(1)
    off()
    refreshAll()
    expect(a).toHaveBeenCalledTimes(1)
  })
  it('the loader shows the restaurant logo once it is set', () => {
    setBrand({ logo: 'https://cdn.test/alpha.png', name: 'Alpha' })
    const { container } = render(<Spinner />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe('https://cdn.test/alpha.png')
    setBrand(null)
  })
})

describe('sign-in form pieces', () => {
  it('password field can be shown and hidden, and Remember me reports its state', () => {
    const changed = vi.fn()
    render(<MemoryRouter><AuthField label="Password" icon={Mail} secret defaultValue="x" /><RememberRow remember={false} onChange={changed} forgotTo="/forgot-password" /></MemoryRouter>)
    const input = screen.getByLabelText('Password') as HTMLInputElement
    expect(input.type).toBe('password')
    fireEvent.click(screen.getByLabelText('Show password'))
    expect(input.type).toBe('text')
    fireEvent.click(screen.getByLabelText('Remember me'))
    expect(changed).toHaveBeenCalledWith(true)
    expect(screen.getByText('Forgot Password?')).toBeTruthy()
  })
})

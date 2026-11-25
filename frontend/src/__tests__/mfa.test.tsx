import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const completeMfa = vi.fn()
vi.mock('../lib/auth', () => ({ useAuth: () => ({ completeMfa }) }))

import { MfaChallengeForm } from '../ui/Mfa'

describe('two-step sign-in form', () => {
  it('asks for the 6-digit code, validates, and submits it with the login token', async () => {
    completeMfa.mockResolvedValue({})
    const done = vi.fn()
    render(<MfaChallengeForm token="tok" onDone={done} onCancel={() => {}} />)
    fireEvent.click(screen.getByText('Verify and sign in'))
    expect(screen.getByRole('alert').textContent).toContain('6-digit')
    expect(completeMfa).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Authentication code'), { target: { value: '123456' } })
    fireEvent.click(screen.getByText('Verify and sign in'))
    await waitFor(() => expect(done).toHaveBeenCalled())
    expect(completeMfa).toHaveBeenCalledWith('tok', '123456', false)
  })

  it('switches to a recovery code and shows server errors', async () => {
    completeMfa.mockRejectedValue(new Error('x'))
    render(<MfaChallengeForm token="tok" onDone={() => {}} onCancel={() => {}} />)
    fireEvent.click(screen.getByText('Use a recovery code instead'))
    fireEvent.change(screen.getByLabelText('Recovery code'), { target: { value: 'abcd-1234-ef56' } })
    fireEvent.click(screen.getByText('Verify and sign in'))
    await waitFor(() => expect(completeMfa).toHaveBeenLastCalledWith('tok', 'abcd-1234-ef56', true))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Verification failed'))
  })

  it('can go back to the password step', () => {
    const back = vi.fn()
    render(<MfaChallengeForm token="tok" onDone={() => {}} onCancel={back} />)
    fireEvent.click(screen.getByText('Back'))
    expect(back).toHaveBeenCalled()
  })
})

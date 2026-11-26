import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { installPlaceholders, placeholderFor } from '../lib/placeholders'
import { Field, PasswordInput } from '../ui/kit'

describe('placeholders say what to enter', () => {
  it('builds "Enter your ..." from the label and keeps examples', () => {
    expect(placeholderFor('Full name', '')).toBe('Enter your full name')
    expect(placeholderFor('Phone number (optional)', '')).toBe('Enter your phone number')
    expect(placeholderFor('Amount', 'e.g. 120.50')).toBe('Enter your amount, e.g. 120.50')
    expect(placeholderFor('Option name', 'Name, e.g. Large')).toBe('Enter your option name, e.g. Large')
    expect(placeholderFor('Price', '0.00')).toBe('Enter your price, e.g. 0.00')
    expect(placeholderFor('SKU code', '')).toBe('Enter your SKU code')
    expect(placeholderFor('Description', 'Short description')).toBe('Enter your description')
    expect(placeholderFor('Password', 'Enter your password')).toBeNull() // already right
    expect(placeholderFor('Full name', 'Enter the full name')).toBe('Enter your full name')
    expect(placeholderFor('Your password', '')).toBe('Enter your password')
    expect(placeholderFor('Confirm with your password', '')).toBe('Enter your password')
    expect(placeholderFor('Confirm new password', '')).toBe('Re-enter your new password')
    expect(placeholderFor('Why would you like to cancel?', '')).toBe('Enter your answer')
  })

  it('applies to labelled boxes on the page and leaves search, dates and checkboxes alone', () => {
    render(
      <>
        <Field label="Street address">{(p) => <input {...p} className="input" />}</Field>
        <input aria-label="Internal note" />
        <input type="search" aria-label="Search staff" placeholder="Search name or email" />
        <input type="date" aria-label="Date received" />
        <input type="checkbox" aria-label="Agree" />
        <Field label="Notes">{(p) => <textarea {...p} className="input" />}</Field>
      </>,
    )
    installPlaceholders()
    expect(screen.getByLabelText('Street address').getAttribute('placeholder')).toBe('Enter your street address')
    expect(screen.getByLabelText('Internal note').getAttribute('placeholder')).toBe('Enter your internal note')
    expect(screen.getByLabelText('Notes').getAttribute('placeholder')).toBe('Enter your notes')
    expect(screen.getByLabelText('Search staff').getAttribute('placeholder')).toBe('Search name or email')
    expect(screen.getByLabelText('Date received').getAttribute('placeholder')).toBeNull()
    expect(screen.getByLabelText('Agree').getAttribute('placeholder')).toBeNull()
  })
})

describe('password fields', () => {
  it('can be shown and hidden', () => {
    render(<Field label="Current password">{(p) => <PasswordInput {...p} defaultValue="secret" />}</Field>)
    const input = screen.getByLabelText('Current password') as HTMLInputElement
    expect(input.type).toBe('password')
    fireEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(input.type).toBe('text')
    fireEvent.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(input.type).toBe('password')
  })
})

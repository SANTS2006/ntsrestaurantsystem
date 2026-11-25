import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { CompEditor, type Comp } from '../tenant/manage/Payroll'

function Harness() {
  const [items, setItems] = useState<Comp[]>([])
  return (
    <>
      <CompEditor items={items} onChange={setItems} types={[['bonus', 'Bonus'], ['deduction', 'Deduction']]} />
      <output data-testid="count">{items.length}</output>
    </>
  )
}

describe('payroll item editor', () => {
  it('adds, edits and removes items', () => {
    render(<Harness />)
    fireEvent.click(screen.getByText('+ Add item'))
    fireEvent.change(screen.getByLabelText('Item name'), { target: { value: 'Tips' } })
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '12.50' } })
    expect((screen.getByLabelText('Item name') as HTMLInputElement).value).toBe('Tips')
    expect(screen.getByTestId('count').textContent).toBe('1')
    fireEvent.click(screen.getByLabelText('Remove item'))
    expect(screen.getByTestId('count').textContent).toBe('0')
  })
})

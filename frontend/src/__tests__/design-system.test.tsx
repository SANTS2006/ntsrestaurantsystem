import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AreaChart, BarList, Donut, Sparkline } from '../ui/charts'
import { Drawer, Kpi, Pager, SearchInput } from '../ui/kit'
import Shell from '../ui/Shell'

const fmt = (n: number) => `$${n.toFixed(2)}`

describe('charts', () => {
  it('describes the data to screen readers and shows tooltips on focus', () => {
    render(<AreaChart label="Money collected" format={fmt} points={[{ label: '01-01', value: 10 }, { label: '01-02', value: 30 }]} />)
    expect(screen.getByRole('img', { name: /Money collected\. Total \$40\.00 over 2 periods/ })).toBeTruthy()
    fireEvent.focus(screen.getByRole('img', { name: /01-02: \$30\.00/ }))
    expect(screen.getByText('Collected: $30.00')).toBeTruthy()
  })

  it('shows an honest empty state instead of an empty chart', () => {
    render(<AreaChart label="x" format={fmt} points={[{ label: 'a', value: 0 }]} />)
    expect(screen.getByText('No data in this period.')).toBeTruthy()
    render(<BarList rows={[]} format={String} empty="Nothing sold." />)
    expect(screen.getByText('Nothing sold.')).toBeTruthy()
    render(<Donut slices={[{ label: 'A', value: 0, color: 'red' }]} centre="0" sub="orders" />)
    expect(screen.getByText('No orders in this period.')).toBeTruthy()
  })

  it('ranks bars and scales them to the largest value', () => {
    const { container } = render(<BarList format={(n) => `${n} sold`} rows={[{ label: 'Rice', value: 10 }, { label: 'Fish', value: 5 }]} />)
    const fills = container.querySelectorAll<HTMLElement>('.fill')
    expect(fills[0].style.width).toBe('100%')
    expect(fills[1].style.width).toBe('50%')
    expect(screen.getByText('10 sold')).toBeTruthy()
  })

  it('draws a donut with a centre total and legend', () => {
    render(<Donut centre="7" sub="orders" slices={[{ label: 'Completed', value: 5, color: 'green' }, { label: 'Cancelled', value: 2, color: 'red' }]} />)
    expect(screen.getByText('7')).toBeTruthy()
    expect(screen.getByText('Completed')).toBeTruthy()
  })

  it('renders nothing for a flat sparkline', () => {
    const { container } = render(<Sparkline values={[0, 0, 0]} />)
    expect(container.querySelector('svg')).toBeNull()
  })
})

describe('layout components', () => {
  it('Drawer closes with Escape and the close button, and is a labelled dialog', () => {
    const close = vi.fn()
    render(<Drawer title="Order 12" onClose={close}><p>details</p></Drawer>)
    expect(screen.getByRole('dialog', { name: 'Order 12' })).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.click(screen.getByLabelText('Close'))
    expect(close).toHaveBeenCalledTimes(2)
  })

  it('Pager disables unavailable directions and reports the total', () => {
    const go = vi.fn()
    render(<Pager page={2} hasPrev hasNext={false} onPage={go} total={41} />)
    expect((screen.getByText('Next') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByText('Previous'))
    expect(go).toHaveBeenCalledWith(1)
    expect(screen.getByText(/41 results/)).toBeTruthy()
  })

  it('SearchInput is labelled and reports typing', () => {
    const on = vi.fn()
    render(<SearchInput value="" onChange={on} placeholder="Find" label="Search orders" />)
    fireEvent.change(screen.getByLabelText('Search orders'), { target: { value: 'abc' } })
    expect(on).toHaveBeenCalledWith('abc')
  })

  it('Kpi shows label, value and detail', () => {
    render(<Kpi label="Collected" value="$10.00" sub="net of refunds" />)
    expect(screen.getByText('Collected')).toBeTruthy()
    expect(screen.getByText('$10.00')).toBeTruthy()
  })

  it('Shell shows only the navigation it is given, marks the current page and opens the mobile menu', () => {
    const Icon = () => <svg />
    render(
      <MemoryRouter initialEntries={['/manage/orders']}>
        <Shell brand="Ocean View" tagline="Workspace" groups={[{ label: 'Service', items: [{ to: '/manage/orders', label: 'Orders', icon: Icon }] }, { label: 'Empty', items: [] }]}
          user={{ name: 'Casey Cashier', role: 'Cashier' }} onLogout={() => {}} profilePath="/profile"><p>page</p></Shell>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /Orders/ }).className).toContain('active')
    expect(screen.queryByText('Empty')).toBeNull()
    expect(screen.getAllByText('CC').length).toBe(2) // sidebar profile and top bar avatar
    fireEvent.click(screen.getByLabelText('Open navigation'))
    expect(document.querySelector('.shell')?.className).toContain('open')
  })
})

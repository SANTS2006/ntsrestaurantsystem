import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { BlockView, SmartLink } from '../ui/builder/PageDesign'
import { modelFor, newBlock, pageIdOf } from '../ui/builder/types'

const items = ['One', 'Two'].map((title) => ({ title, text: `About **${title}**`, image: null, button_label: '', button_link: '' }))

describe('page builder', () => {
  it('knows which page an address shows and which 3D model it gets', () => {
    expect([pageIdOf('/'), pageIdOf('/menu'), pageIdOf('/menu/rice'), pageIdOf('/legal/privacy-policy')]).toEqual(['home', 'menu', '', 'legal'])
    expect(modelFor('menu', 'auto')).toBe('burger')
    expect(modelFor('menu', 'none')).toBeNull()
    expect(modelFor('legal')).toBeNull()
    expect(modelFor('legal', 'globe')).toBe('globe')
  })

  it('shows the same entries as cards, an accordion or a carousel', () => {
    for (const layout of ['cards', 'accordion', 'carousel'] as const) {
      const { container, unmount } = render(<MemoryRouter><BlockView block={{ ...newBlock(layout), title: 'Why us', items }} /></MemoryRouter>)
      expect(container.querySelectorAll({ cards: '.pb-card', accordion: 'details', carousel: '.pb-slide' }[layout]).length).toBe(2)
      expect(container.querySelector('strong')?.textContent).toBe('One')
      if (layout === 'carousel') {
        fireEvent.click(screen.getByRole('button', { name: 'Next slide' }))
        expect(screen.getByRole('button', { name: 'Slide 2' }).getAttribute('aria-current')).toBe('true')
      }
      unmount()
    }
  })

  it('never turns a script address into a working link', () => {
    render(<MemoryRouter><SmartLink to="javascript:alert(1)">bad</SmartLink><SmartLink to="/menu">menu</SmartLink></MemoryRouter>)
    expect(screen.getByText('bad').getAttribute('href')).toBe('#')
    expect(screen.getByText('menu').getAttribute('href')).toBe('/menu')
  })
})

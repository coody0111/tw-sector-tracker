import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { StockModal } from './StockModal'
import type { Stock } from '../types'

const stock: Stock = {
  id: '3583', name: '辛耘', close: 905, changePct: 0.11, volume: 3000,
  weeklyPct: 6.23, foreignNet: 336, trustNet: -82, marginBalance: 0,
  marginChange: 0, sparkline: [0.1, 4.99, 4.99],
}

describe('StockModal', () => {
  it('renders stock id, name, price and chips info', () => {
    render(<StockModal stock={stock} onClose={() => {}} />)
    expect(screen.getByText('3583')).toBeInTheDocument()
    expect(screen.getByText('辛耘')).toBeInTheDocument()
    expect(screen.getByText('905')).toBeInTheDocument()
    expect(screen.getByText(/336/)).toBeInTheDocument()
    expect(screen.getByText(/-82/)).toBeInTheDocument()
  })

  it('renders one sparkline bar per data point', () => {
    render(<StockModal stock={stock} onClose={() => {}} />)
    expect(screen.getAllByTestId('spark-bar')).toHaveLength(3)
  })

  it('calls onClose when the close button is clicked', () => {
    const onClose = vi.fn()
    render(<StockModal stock={stock} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: /關閉/ }))
    expect(onClose).toHaveBeenCalled()
  })
})

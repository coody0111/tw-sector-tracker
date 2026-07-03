import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SignalChips } from './SignalChips'
import type { MetaSector } from '../types'

function makeMeta(overrides: Partial<MetaSector>): MetaSector {
  return {
    name: 'X', avgChangePct: 1, upCount: 0, downCount: 0,
    cum3: null, cum5: null, cum7: null,
    todayRank: 1, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
    streak: 0, volRatio: null, subGroups: [],
    ...overrides,
  }
}

describe('SignalChips', () => {
  it('renders nothing when there are no signals', () => {
    const { container } = render(<SignalChips meta={makeMeta({})} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders daily rank chip when rank improved', () => {
    render(<SignalChips meta={makeMeta({ todayRank: 1, yesterdayRank: 10 })} />)
    expect(screen.getByText(/日/)).toBeInTheDocument()
    expect(screen.getByText(/#10→#1/)).toBeInTheDocument()
    expect(screen.getByText(/▲9/)).toBeInTheDocument()
  })

  it('renders weekly rank chip', () => {
    render(<SignalChips meta={makeMeta({ thisWeekRank: 1, lastWeekRank: 8 })} />)
    expect(screen.getByText(/週/)).toBeInTheDocument()
    expect(screen.getByText(/#8→#1/)).toBeInTheDocument()
  })

  it('renders streak chip only when streak >= 2 days', () => {
    const { rerender } = render(<SignalChips meta={makeMeta({ streak: 1 })} />)
    expect(screen.queryByText(/連漲/)).not.toBeInTheDocument()

    rerender(<SignalChips meta={makeMeta({ streak: 3 })} />)
    expect(screen.getByText('連漲3日')).toBeInTheDocument()
  })

  it('renders volume spike chip only when ratio >= 1.5', () => {
    render(<SignalChips meta={makeMeta({ volRatio: 2.5 })} />)
    expect(screen.getByText(/量↑2.5x/)).toBeInTheDocument()
  })

  it('exposes signal intensity via a data attribute for the row color-strip', () => {
    const { container: none } = render(<SignalChips meta={makeMeta({})} />)
    expect(none.firstChild).toBeNull()

    const { container: strong } = render(
      <SignalChips meta={makeMeta({ todayRank: 1, yesterdayRank: 10, streak: 3 })} />,
    )
    expect(strong.firstElementChild).toHaveAttribute('data-intensity', 'strong')

    const { container: weak } = render(<SignalChips meta={makeMeta({ streak: 2 })} />)
    expect(weak.firstElementChild).toHaveAttribute('data-intensity', 'weak')
  })
})

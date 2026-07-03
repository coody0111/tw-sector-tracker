import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SectorDetail } from './SectorDetail'
import type { MetaSector } from '../types'

const meta: MetaSector = {
  name: '先進封裝設備', avgChangePct: 4.77, upCount: 1, downCount: 0,
  cum3: null, cum5: null, cum7: null,
  todayRank: 1, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
  streak: 0, volRatio: null,
  subGroups: [
    {
      name: '半導體製程設備',
      stocks: [
        { id: '3583', name: '辛耘', close: 905, changePct: 0.11, volume: 3000,
          weeklyPct: 6.23, foreignNet: 336, trustNet: -82, marginBalance: 0,
          marginChange: 0, sparkline: [] },
      ],
    },
  ],
}

describe('SectorDetail', () => {
  it('shows a placeholder when no sector is selected', () => {
    render(<SectorDetail meta={null} />)
    expect(screen.getByText(/請選擇/)).toBeInTheDocument()
  })

  it('renders sub-group label and stock rows', () => {
    render(<SectorDetail meta={meta} />)
    expect(screen.getByText('先進封裝設備')).toBeInTheDocument()
    expect(screen.getByText('半導體製程設備')).toBeInTheDocument()
    expect(screen.getByText('辛耘')).toBeInTheDocument()
    expect(screen.getByText('3583')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from './App'
import type { SectorData } from './types'

const fakeData: SectorData = {
  date: '2026-07-01',
  market: { avgPct: 1.2, up: 1, down: 0, flat: 0 },
  metaSectors: [
    {
      name: '先進封裝設備', avgChangePct: 4.77, upCount: 1, downCount: 0,
      cum3: null, cum5: null, cum7: null,
      todayRank: 1, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
      streak: 0, volRatio: null,
      subGroups: [
        { name: '半導體製程設備', stocks: [
          { id: '3583', name: '辛耘', close: 905, changePct: 0.11, volume: 3000,
            weeklyPct: 6.23, foreignNet: 336, trustNet: -82, marginBalance: 0,
            marginChange: 0, sparkline: [] },
        ] },
      ],
    },
  ],
}

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(fakeData) } as Response),
  )
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: true, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }))
})

describe('App', () => {
  it('loads data and selecting a rank row shows its detail', async () => {
    render(<App />)

    await waitFor(() => expect(screen.getByText('先進封裝設備')).toBeInTheDocument())

    fireEvent.click(screen.getByText('先進封裝設備'))
    expect(await screen.findByText('辛耘')).toBeInTheDocument()
  })
})

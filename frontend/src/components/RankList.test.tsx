import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { RankList } from './RankList'
import type { MetaSector } from '../types'

function makeMeta(overrides: Partial<MetaSector> & { name: string; avgChangePct: number }): MetaSector {
  return {
    upCount: 1, downCount: 0,
    cum3: null, cum5: null, cum7: null,
    todayRank: 0, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
    streak: 0, volRatio: null, subGroups: [],
    ...overrides,
  }
}

describe('RankList', () => {
  it('renders meta sectors ranked descending by default with rank numbers', () => {
    const metaSectors = [makeMeta({ name: '半導體材料', avgChangePct: 3.28 }), makeMeta({ name: '先進封裝設備', avgChangePct: 4.77 })]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={() => {}} />)

    const rows = screen.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('先進封裝設備')
    expect(rows[0]).toHaveTextContent('01')
    expect(rows[1]).toHaveTextContent('半導體材料')
  })

  it('calls onSelect with the meta sector name when a row is clicked', () => {
    const onSelect = vi.fn()
    const metaSectors = [makeMeta({ name: '先進封裝設備', avgChangePct: 4.77 })]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={onSelect} />)

    fireEvent.click(screen.getByText('先進封裝設備'))
    expect(onSelect).toHaveBeenCalledWith('先進封裝設備')
  })

  it('flips sort direction when the toggle is clicked', () => {
    const metaSectors = [makeMeta({ name: 'B', avgChangePct: 1.0 }), makeMeta({ name: 'A', avgChangePct: 5.0 })]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /切換排序/ }))
    const rows = screen.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('B')
  })

  it('renders SignalChips under a row that has signals, and applies a strip class matching intensity', () => {
    const metaSectors = [
      makeMeta({ name: '先進封裝設備', avgChangePct: 4.77, todayRank: 1, yesterdayRank: 10, streak: 3 }),
      makeMeta({ name: '安靜的族群', avgChangePct: 1.0 }),
    ]
    render(<RankList metaSectors={metaSectors} selectedName={null} onSelect={() => {}} />)

    const rows = screen.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('#10→#1')
    expect(rows[0].className).toContain('strip-strong')
    expect(rows[1].className).not.toContain('strip-strong')
    expect(rows[1].className).not.toContain('strip-weak')
  })
})

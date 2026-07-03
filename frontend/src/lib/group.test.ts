import { describe, it, expect } from 'vitest'
import { sortStocksWithinGroups } from './group'
import type { SubGroup } from '../types'

function makeStock(id: string, pct: number) {
  return {
    id, name: id, close: 100, changePct: pct, volume: 100,
    weeklyPct: 0, foreignNet: 0, trustNet: 0, marginBalance: 0, marginChange: 0,
    sparkline: [],
  }
}

describe('sortStocksWithinGroups', () => {
  it('sorts stocks within each sub-group descending by changePct', () => {
    const groups: SubGroup[] = [
      { name: '電腦系統業', stocks: [makeStock('B', 1.0), makeStock('A', 5.0)] },
      { name: '伺服器機殼', stocks: [makeStock('C', -1.0)] },
    ]
    const result = sortStocksWithinGroups(groups)
    expect(result[0].stocks.map((s) => s.id)).toEqual(['A', 'B'])
    expect(result[1].stocks.map((s) => s.id)).toEqual(['C'])
  })

  it('does not mutate the input', () => {
    const groups: SubGroup[] = [
      { name: 'g', stocks: [makeStock('B', 1.0), makeStock('A', 5.0)] },
    ]
    sortStocksWithinGroups(groups)
    expect(groups[0].stocks.map((s) => s.id)).toEqual(['B', 'A'])
  })
})

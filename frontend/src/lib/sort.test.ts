import { describe, it, expect } from 'vitest'
import { sortMetaSectors } from './sort'
import type { MetaSector } from '../types'

function makeMeta(name: string, pct: number): MetaSector {
  return {
    name, avgChangePct: pct, upCount: 0, downCount: 0,
    cum3: null, cum5: null, cum7: null,
    todayRank: 0, yesterdayRank: null, thisWeekRank: null, lastWeekRank: null,
    streak: 0, volRatio: null, subGroups: [],
  }
}

describe('sortMetaSectors', () => {
  it('sorts descending by default (gainers first)', () => {
    const input = [makeMeta('B', 1.0), makeMeta('A', 5.0), makeMeta('C', -2.0)]
    const sorted = sortMetaSectors(input, 'desc')
    expect(sorted.map((m) => m.name)).toEqual(['A', 'B', 'C'])
  })

  it('sorts ascending (losers first) when direction is asc', () => {
    const input = [makeMeta('B', 1.0), makeMeta('A', 5.0), makeMeta('C', -2.0)]
    const sorted = sortMetaSectors(input, 'asc')
    expect(sorted.map((m) => m.name)).toEqual(['C', 'B', 'A'])
  })

  it('does not mutate the input array', () => {
    const input = [makeMeta('B', 1.0), makeMeta('A', 5.0)]
    sortMetaSectors(input, 'desc')
    expect(input.map((m) => m.name)).toEqual(['B', 'A'])
  })
})

import type { SubGroup } from '../types'

export function sortStocksWithinGroups(subGroups: SubGroup[]): SubGroup[] {
  return subGroups.map((group) => ({
    ...group,
    stocks: [...group.stocks].sort(
      (a, b) => (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity),
    ),
  }))
}

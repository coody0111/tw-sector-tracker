import type { MetaSector } from '../types'

export type SortDirection = 'asc' | 'desc'

export function sortMetaSectors(
  metaSectors: MetaSector[],
  direction: SortDirection,
): MetaSector[] {
  const sorted = [...metaSectors]
  sorted.sort((a, b) =>
    direction === 'desc'
      ? b.avgChangePct - a.avgChangePct
      : a.avgChangePct - b.avgChangePct,
  )
  return sorted
}

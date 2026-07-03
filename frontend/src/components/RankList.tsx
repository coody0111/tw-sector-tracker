import { useState } from 'react'
import type { MetaSector } from '../types'
import { sortMetaSectors, type SortDirection } from '../lib/sort'
import { SignalChips } from './SignalChips'

interface RankListProps {
  metaSectors: MetaSector[]
  selectedName: string | null
  onSelect: (name: string) => void
}

function hasAnySignal(meta: MetaSector): boolean {
  const dailyDelta = meta.yesterdayRank != null ? meta.yesterdayRank - meta.todayRank : 0
  const weeklyDelta =
    meta.lastWeekRank != null && meta.thisWeekRank != null
      ? meta.lastWeekRank - meta.thisWeekRank
      : 0
  return (
    dailyDelta !== 0 ||
    weeklyDelta !== 0 ||
    Math.abs(meta.streak) >= 2 ||
    (meta.volRatio != null && meta.volRatio >= 1.5)
  )
}

function stripIntensityClass(meta: MetaSector): string {
  if (!hasAnySignal(meta)) return ''
  const dailyDelta = meta.yesterdayRank != null ? Math.abs(meta.yesterdayRank - meta.todayRank) : 0
  const weeklyDelta =
    meta.lastWeekRank != null && meta.thisWeekRank != null
      ? Math.abs(meta.lastWeekRank - meta.thisWeekRank)
      : 0
  const strong =
    dailyDelta >= 5 || weeklyDelta >= 5 || Math.abs(meta.streak) >= 3 || (meta.volRatio ?? 0) >= 2
  return strong ? 'strip-strong' : 'strip-weak'
}

export function RankList({ metaSectors, selectedName, onSelect }: RankListProps) {
  const [direction, setDirection] = useState<SortDirection>('desc')
  const sorted = sortMetaSectors(metaSectors, direction)

  return (
    <div className="rank-list">
      <div className="rank-list-header">
        <span>族群排名</span>
        <button
          aria-label="切換排序方向"
          onClick={() => setDirection((d) => (d === 'desc' ? 'asc' : 'desc'))}
        >
          {direction === 'desc' ? '▲' : '▼'}
        </button>
      </div>
      <ul>
        {sorted.map((meta, i) => {
          const sign = meta.avgChangePct >= 0 ? '+' : ''
          const color = meta.avgChangePct >= 0 ? '#f87171' : '#4ade80'
          const stripClass = stripIntensityClass(meta)
          return (
            <li
              key={meta.name}
              role="listitem"
              className={[
                stripClass,
                meta.name === selectedName ? 'active' : '',
              ].filter(Boolean).join(' ')}
              onClick={() => onSelect(meta.name)}
              style={{ cursor: 'pointer' }}
            >
              <div className="rank-row-main">
                <span className="rank-num">{String(i + 1).padStart(2, '0')}</span>
                <span className="rank-name">{meta.name}</span>
                <span className="rank-pct" style={{ color }}>
                  {sign}
                  {meta.avgChangePct.toFixed(2)}%
                </span>
              </div>
              <SignalChips meta={meta} />
            </li>
          )
        })}
      </ul>
    </div>
  )
}

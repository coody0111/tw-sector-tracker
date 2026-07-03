import type { MetaSector } from '../types'

interface SignalChipsProps {
  meta: MetaSector
}

export function SignalChips({ meta }: SignalChipsProps) {
  const chips: React.ReactNode[] = []
  let strongSignal = false

  if (meta.yesterdayRank != null) {
    const delta = meta.yesterdayRank - meta.todayRank
    if (delta !== 0) {
      if (Math.abs(delta) >= 5) strongSignal = true
      const arrow = delta > 0 ? '▲' : '▼'
      chips.push(
        <span key="daily-rank" className="chip chip-rank chip-rank-daily">
          <span className="chip-label">日</span> #{meta.yesterdayRank}→#{meta.todayRank}{' '}
          <span className="chip-delta">
            {arrow}
            {Math.abs(delta)}
          </span>
        </span>,
      )
    }
  }

  if (meta.lastWeekRank != null && meta.thisWeekRank != null) {
    const delta = meta.lastWeekRank - meta.thisWeekRank
    if (delta !== 0) {
      if (Math.abs(delta) >= 5) strongSignal = true
      const arrow = delta > 0 ? '▲' : '▼'
      chips.push(
        <span key="weekly-rank" className="chip chip-rank chip-rank-weekly">
          <span className="chip-label">週</span> #{meta.lastWeekRank}→#{meta.thisWeekRank}{' '}
          <span className="chip-delta">
            {arrow}
            {Math.abs(delta)}
          </span>
        </span>,
      )
    }
  }

  if (Math.abs(meta.streak) >= 2) {
    if (Math.abs(meta.streak) >= 3) strongSignal = true
    const label = meta.streak > 0 ? `連漲${meta.streak}日` : `連跌${Math.abs(meta.streak)}日`
    chips.push(
      <span key="streak" className="chip chip-signal">
        <span className="chip-icon">🔥</span> {label}
      </span>,
    )
  }

  if (meta.volRatio != null && meta.volRatio >= 1.5) {
    if (meta.volRatio >= 2) strongSignal = true
    chips.push(
      <span key="vol" className="chip chip-signal">
        <span className="chip-icon">📊</span> 量↑{meta.volRatio.toFixed(1)}x
      </span>,
    )
  }

  if (chips.length === 0) {
    return null
  }

  return (
    <div className="signal-chips" data-intensity={strongSignal ? 'strong' : 'weak'}>
      {chips}
    </div>
  )
}

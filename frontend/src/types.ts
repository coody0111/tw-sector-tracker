export interface Stock {
  id: string
  name: string
  close: number | null
  changePct: number | null
  volume: number | null
  weeklyPct: number
  foreignNet: number
  trustNet: number
  marginBalance: number
  marginChange: number
  sparkline: number[]
}

export interface SubGroup {
  name: string
  stocks: Stock[]
}

export interface MetaSector {
  name: string
  avgChangePct: number
  upCount: number
  downCount: number
  cum3: number | null
  cum5: number | null
  cum7: number | null
  todayRank: number
  yesterdayRank: number | null
  thisWeekRank: number | null
  lastWeekRank: number | null
  streak: number
  volRatio: number | null
  subGroups: SubGroup[]
}

export interface SectorData {
  date: string
  market: { avgPct: number; up: number; down: number; flat: number }
  metaSectors: MetaSector[]
}

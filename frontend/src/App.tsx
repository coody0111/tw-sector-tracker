import { useMemo, useState } from 'react'
import { useSectorData } from './hooks/useSectorData'
import { useMediaQuery } from './hooks/useMediaQuery'
import { RankList } from './components/RankList'
import { SectorDetail } from './components/SectorDetail'
import { SearchBar } from './components/SearchBar'
import type { MetaSector } from './types'

function matchesQuery(meta: MetaSector, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (meta.name.toLowerCase().includes(q)) return true
  return meta.subGroups.some((g) =>
    g.stocks.some(
      (s) => s.id.includes(q) || s.name.toLowerCase().includes(q),
    ),
  )
}

export default function App() {
  const { data, loading, error } = useSectorData()
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const filteredMetaSectors = useMemo(() => {
    if (!data) return []
    return data.metaSectors.filter((m) => matchesQuery(m, query))
  }, [data, query])

  if (loading) return <div className="status">載入中...</div>
  if (error) return <div className="status status-error">資料載入失敗：{error}</div>
  if (!data) return null

  const selectedMeta = filteredMetaSectors.find((m) => m.name === selectedName) ?? null

  return (
    <div className="app">
      <header className="market-header">
        <span>{data.date}</span>
        <span>大盤平均 {data.market.avgPct.toFixed(2)}%</span>
        <SearchBar onSearch={setQuery} />
      </header>
      <main className={isDesktop ? 'layout-desktop' : 'layout-mobile'}>
        <RankList
          metaSectors={filteredMetaSectors}
          selectedName={selectedName}
          onSelect={(name) => setSelectedName(name === selectedName ? null : name)}
        />
        {isDesktop ? (
          <SectorDetail meta={selectedMeta} />
        ) : (
          selectedMeta && <SectorDetail meta={selectedMeta} />
        )}
      </main>
    </div>
  )
}

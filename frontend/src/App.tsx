import { useState } from 'react'
import { useSectorData } from './hooks/useSectorData'
import { useMediaQuery } from './hooks/useMediaQuery'
import { RankList } from './components/RankList'
import { SectorDetail } from './components/SectorDetail'

export default function App() {
  const { data, loading, error } = useSectorData()
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [selectedName, setSelectedName] = useState<string | null>(null)

  if (loading) return <div className="status">載入中...</div>
  if (error) return <div className="status status-error">資料載入失敗：{error}</div>
  if (!data) return null

  const selectedMeta = data.metaSectors.find((m) => m.name === selectedName) ?? null

  return (
    <div className="app">
      <header className="market-header">
        <span>{data.date}</span>
        <span>大盤平均 {data.market.avgPct.toFixed(2)}%</span>
      </header>
      <main className={isDesktop ? 'layout-desktop' : 'layout-mobile'}>
        <RankList
          metaSectors={data.metaSectors}
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

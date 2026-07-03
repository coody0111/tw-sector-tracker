import { useState } from 'react'
import type { MetaSector, Stock } from '../types'
import { sortStocksWithinGroups } from '../lib/group'
import { SignalChips } from './SignalChips'
import { StockModal } from './StockModal'

interface SectorDetailProps {
  meta: MetaSector | null
}

export function SectorDetail({ meta }: SectorDetailProps) {
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null)

  if (!meta) {
    return <div className="sector-detail-empty">請選擇左側的族群查看個股明細</div>
  }

  const groups = sortStocksWithinGroups(meta.subGroups)
  const sign = meta.avgChangePct >= 0 ? '+' : ''

  return (
    <div className="sector-detail">
      <div className="sector-detail-header">
        <h2>{meta.name}</h2>
        <span>
          {sign}
          {meta.avgChangePct.toFixed(2)}%
        </span>
      </div>
      <SignalChips meta={meta} />
      {groups.map((group) => (
        <div key={group.name} className="sub-group">
          <div className="sub-group-label">{group.name}</div>
          {group.stocks.map((stock) => {
            const pctSign = (stock.changePct ?? 0) >= 0 ? '+' : ''
            return (
              <div
                key={stock.id}
                className="stock-row"
                onClick={() => setSelectedStock(stock)}
                style={{ cursor: 'pointer' }}
              >
                <span className="stock-id">{stock.id}</span>
                <span className="stock-name">{stock.name}</span>
                <span className="stock-close">{stock.close ?? '—'}</span>
                <span className="stock-pct">
                  {stock.changePct != null ? `${pctSign}${stock.changePct.toFixed(2)}%` : '—'}
                </span>
              </div>
            )
          })}
        </div>
      ))}
      {selectedStock && (
        <StockModal stock={selectedStock} onClose={() => setSelectedStock(null)} />
      )}
    </div>
  )
}

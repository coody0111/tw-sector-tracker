import type { Stock } from '../types'

interface StockModalProps {
  stock: Stock
  onClose: () => void
}

export function StockModal({ stock, onClose }: StockModalProps) {
  const maxAbs = Math.max(1, ...stock.sparkline.map((p) => Math.abs(p)))
  const pctSign = (stock.changePct ?? 0) >= 0 ? '+' : ''
  const pctColor = (stock.changePct ?? 0) >= 0 ? '#f87171' : '#4ade80'

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button aria-label="關閉" onClick={onClose}>
          ×
        </button>
        <div className="modal-header">
          <span>{stock.id}</span>
          <span>{stock.name}</span>
        </div>
        <div className="modal-price">
          <span>{stock.close ?? '—'}</span>
          <span style={{ color: pctColor }}>
            {stock.changePct != null ? `${pctSign}${stock.changePct.toFixed(2)}%` : '—'}
          </span>
        </div>
        <div className="modal-sparkline">
          {stock.sparkline.map((pct, i) => {
            const up = pct >= 0
            const height = Math.max(3, (Math.abs(pct) / maxAbs) * 32)
            return (
              <div
                key={i}
                data-testid="spark-bar"
                title={`${pct.toFixed(2)}%`}
                style={{
                  height: `${height}px`,
                  width: '8px',
                  background: up ? '#ef4444' : '#22c55e',
                  alignSelf: up ? 'flex-end' : 'flex-start',
                }}
              />
            )
          })}
        </div>
        <div className="modal-chips">
          <div>外資 {stock.foreignNet.toLocaleString()} 張</div>
          <div>投信 {stock.trustNet.toLocaleString()} 張</div>
          <div>
            融資 {stock.marginBalance.toLocaleString()}（{stock.marginChange >= 0 ? '+' : ''}
            {stock.marginChange.toLocaleString()}）
          </div>
        </div>
      </div>
    </div>
  )
}

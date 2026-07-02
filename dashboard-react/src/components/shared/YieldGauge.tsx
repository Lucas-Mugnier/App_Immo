// Calibré sur le marché Chamonix : rendement locatif moyen 4-5%
export function YieldGauge({ value, isEstimate = false }: { value: number; isEstimate?: boolean }) {
  const MIN = 2, MAX = 6.5
  const pct  = Math.max(4, Math.min(100, (value - MIN) / (MAX - MIN) * 100))
  const color = value >= 4.5 ? 'var(--green)' : value >= 3 ? 'var(--amber)' : 'var(--red)'
  const label = value >= 4.5 ? 'bon rendement' : value >= 3 ? 'rendement moyen' : 'faible rendement'
  return (
    <div
      className="yield-gauge has-tooltip"
      data-tip={`${label} · ${value.toFixed(1)}% brut${isEstimate ? ' estimé' : ''}`}
    >
      <span className="yield-gauge-val" style={{ color }}>{value.toFixed(1)}%</span>
      <div className="yield-gauge-track">
        <div className="yield-gauge-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

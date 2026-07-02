import { cn, eur, ratioBg } from '@/lib/utils'

interface Props {
  pred: number | null
  ratio: number | null
  model?: string | null
  showModel?: boolean
}

export function AVMBadge({ pred, ratio, model, showModel = false }: Props) {
  if (!pred || !ratio) {
    return <span className="text-faint text-xs">—</span>
  }

  const cls = cn('chip', ratioBg(ratio))
  const pct = ((ratio - 1) * 100).toFixed(0)
  const sign = ratio >= 1 ? '+' : ''
  const verdict = ratio >= 1.15 ? 'Sous-évalué' : ratio >= 0.90 ? 'Prix marché' : 'Sur-évalué'

  return (
    <div className="flex flex-col gap-0.5 items-start">
      <span className="num text-[0.78rem] text-sub">{eur(pred)}</span>
      <span className={cls} title={`${verdict} — AVM: ${eur(pred)}, ratio ×${ratio.toFixed(2)}`}>
        {sign}{pct}%
      </span>
      {showModel && model && (
        <span className="text-[0.6rem] text-faint">
          {model === 'chamonix_apt' ? 'Cham 8.8%' : model === 'vallee_apt' ? 'Vallée ~15%' : model}
        </span>
      )}
    </div>
  )
}

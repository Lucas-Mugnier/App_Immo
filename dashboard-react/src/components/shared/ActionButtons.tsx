import { Eye, X, Calculator, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useStore } from '@/store/useStore'

interface AppartActionsProps {
  id: string
  surface?: number
  rooms?: number
  location?: string
  price?: number
}

export function AppartActions({ id, surface, rooms, location, price }: AppartActionsProps) {
  const { seen, rejected, hidden, setSeen, setRejected, setHidden, openEstimateur } = useStore()

  const isSeen = !!seen[id]
  const isRejected = !!rejected[id]
  const isHidden = !!hidden[id]

  const canEstimate = surface != null && rooms != null && location != null
  // Normalise vers les clés AVM_LOOKUP ("Argentiere" en data, "Argentière" en lookup)
  const avmCommune = location === 'Argentiere' || location === 'Argentière'
    ? 'Argentière'
    : 'Chamonix'

  return (
    <div className="flex gap-1 items-center">
      <button
        className={cn('action-btn has-tooltip', isSeen && 'active')}
        data-tip={isSeen ? 'Marquer non vu' : 'Marquer vu'}
        onClick={() => setSeen(id, !isSeen)}
      >
        <Eye size={13} />
      </button>

      <button
        className={cn('action-btn has-tooltip', isRejected && 'rejected')}
        data-tip={isRejected ? 'Restaurer' : 'Rejeter'}
        onClick={() => setRejected(id, !isRejected)}
      >
        <X size={13} />
      </button>

      {canEstimate && (
        <button
          className="action-btn has-tooltip"
          data-tip="Affiner estimation AVM"
          onClick={() =>
            openEstimateur({
              surface: surface!,
              rooms: rooms!,
              commune: avmCommune,
              price: price ?? 0,
              listingId: id,
            })
          }
        >
          <Calculator size={13} />
        </button>
      )}

      <button
        className={cn('action-btn has-tooltip', isHidden && 'hidden-btn')}
        data-tip={isHidden ? 'Afficher' : 'Masquer (sans rejeter)'}
        onClick={() => setHidden(id, !isHidden)}
      >
        <EyeOff size={13} />
      </button>
    </div>
  )
}

interface MaisonActionsProps {
  id: number
}

export function MaisonActions({ id }: MaisonActionsProps) {
  const key = `m_${id}`
  const { seen, rejected, setSeen, setRejected } = useStore()
  const isSeen = !!seen[key]
  const isRejected = !!rejected[key]

  return (
    <div className="flex gap-1 items-center">
      <button
        className={cn('action-btn has-tooltip', isSeen && 'active')}
        data-tip={isSeen ? 'Marquer non vu' : 'Marquer vu'}
        onClick={() => setSeen(key, !isSeen)}
      >
        <Eye size={13} />
      </button>
      <button
        className={cn('action-btn has-tooltip', isRejected && 'rejected')}
        data-tip={isRejected ? 'Restaurer' : 'Rejeter'}
        onClick={() => setRejected(key, !isRejected)}
      >
        <X size={13} />
      </button>
    </div>
  )
}

import { useState } from 'react'
import { X, Send, CheckCircle, AlertCircle } from 'lucide-react'
import type { BienRow } from '@/components/tabs/BiensTab'
import {
  submitCorrection, supabase,
  FIELD_LABELS, type CorrectionField,
} from '@/lib/supabase'
import { eur } from '@/lib/utils'

const FIELDS: CorrectionField[] = ['neighbourhood', 'surface', 'carrez', 'prix', 'autre']

function getCurrentValue(row: BienRow, field: CorrectionField): string {
  switch (field) {
    case 'neighbourhood': return row.neighbourhood ?? ''
    case 'surface':       return `${row.surface}m²`
    case 'carrez':        return row.surface_carrez ? `${row.surface_carrez}m²` : 'Non renseigné'
    case 'prix':          return eur(row.price)
    case 'autre':         return ''
  }
}

interface Props {
  row: BienRow
  onClose: () => void
}

export function CorrectionModal({ row, onClose }: Props) {
  const [field, setField]       = useState<CorrectionField>('neighbourhood')
  const [suggested, setSuggested] = useState('')
  const [comment, setComment]   = useState('')
  const [name, setName]         = useState('')
  const [sending, setSending]   = useState(false)
  const [done, setDone]         = useState(false)
  const [error, setError]       = useState(false)

  const currentValue = getCurrentValue(row, field)
  const configured   = !!supabase

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!suggested.trim() || !configured) return
    setSending(true)
    setError(false)
    const ok = await submitCorrection({
      listing_id:    row._key,
      listing_url:   row.url ?? null,
      listing_title: row.title,
      field,
      current_value:   currentValue || null,
      suggested_value: suggested.trim(),
      comment:         comment.trim() || null,
      reporter_name:   name.trim() || null,
    })
    setSending(false)
    if (ok) setDone(true)
    else setError(true)
  }

  return (
    <div className="correction-backdrop" onClick={onClose}>
      <div className="correction-modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">

        <div className="correction-modal-header">
          <span className="correction-modal-title">Proposer une correction</span>
          <button className="correction-modal-close" onClick={onClose} aria-label="Fermer">
            <X size={14} />
          </button>
        </div>

        {!configured && (
          <div className="correction-unconfigured">
            <AlertCircle size={18} />
            <p>Supabase non configuré — les corrections ne peuvent pas être envoyées.</p>
          </div>
        )}

        {done ? (
          <div className="correction-success">
            <CheckCircle size={32} />
            <p>Merci ! Ta correction a été envoyée et sera examinée.</p>
            <button className="correction-btn-primary" onClick={onClose}>Fermer</button>
          </div>
        ) : (
          <form className="correction-form" onSubmit={handleSubmit}>
            <div className="correction-listing-ref">
              <span className="correction-listing-title">{row.title}</span>
              <span className="correction-listing-loc">{row.neighbourhood}</span>
            </div>

            <label className="correction-label">
              Champ à corriger
              <select
                className="correction-select"
                value={field}
                onChange={e => { setField(e.target.value as CorrectionField); setSuggested('') }}
              >
                {FIELDS.map(f => (
                  <option key={f} value={f}>{FIELD_LABELS[f]}</option>
                ))}
              </select>
            </label>

            {field !== 'autre' && currentValue && (
              <div className="correction-current">
                <span className="correction-current-label">Valeur actuelle</span>
                <span className="correction-current-val">{currentValue}</span>
              </div>
            )}

            <label className="correction-label">
              {field === 'autre' ? 'Décris le problème *' : 'Valeur correcte *'}
              <input
                className="correction-input"
                type="text"
                placeholder={
                  field === 'neighbourhood' ? 'ex: Les Tines' :
                  field === 'surface'       ? 'ex: 52' :
                  field === 'carrez'        ? 'ex: 48' :
                  field === 'prix'          ? 'ex: 295000' :
                  'Décris le problème...'
                }
                value={suggested}
                onChange={e => setSuggested(e.target.value)}
                disabled={!configured}
                required
              />
            </label>

            <label className="correction-label">
              Commentaire <span className="correction-optional">(optionnel)</span>
              <textarea
                className="correction-textarea"
                placeholder="Source, explication, lien vers le cadastre..."
                value={comment}
                onChange={e => setComment(e.target.value)}
                disabled={!configured}
                rows={2}
              />
            </label>

            <label className="correction-label">
              Ton prénom <span className="correction-optional">(optionnel)</span>
              <input
                className="correction-input"
                type="text"
                placeholder="ex: Marie"
                value={name}
                onChange={e => setName(e.target.value)}
                disabled={!configured}
              />
            </label>

            {error && (
              <div className="correction-error">
                <AlertCircle size={13} /> Erreur lors de l'envoi, réessaie.
              </div>
            )}

            <div className="correction-actions">
              <button type="button" className="correction-btn-secondary" onClick={onClose}>
                Annuler
              </button>
              <button
                type="submit"
                className="correction-btn-primary"
                disabled={sending || !suggested.trim() || !configured}
              >
                {sending ? 'Envoi…' : <><Send size={12} /> Envoyer</>}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { CheckCircle, XCircle, RefreshCw, Download, ExternalLink, RotateCcw, PlayCircle } from 'lucide-react'
import {
  fetchAllCorrections, updateCorrectionStatus, supabase,
  FIELD_LABELS, type Correction,
} from '@/lib/supabase'

const GITHUB_ACTIONS_URL = 'https://github.com/Lucas-Mugnier/immo-radar/actions'

function RefreshDataButton() {
  const [state, setState] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')

  async function handleClick() {
    if (!supabase) return
    setState('loading')
    const { data } = await supabase.auth.getSession()
    const token = data.session?.access_token
    if (!token) { setState('error'); return }
    try {
      const res = await fetch('/api/refresh', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      setState(res.ok ? 'ok' : 'error')
    } catch {
      setState('error')
    }
  }

  return (
    <div className="admin-refresh">
      <button className="admin-tool-btn" onClick={handleClick} disabled={state === 'loading'}>
        <PlayCircle size={13} />
        <span>{state === 'loading' ? 'Lancement…' : 'Actualiser les données'}</span>
      </button>
      {state === 'ok' && (
        <span className="admin-refresh-status admin-refresh-status--ok">
          Scraping lancé (~30 min) —{' '}
          <a href={GITHUB_ACTIONS_URL} target="_blank" rel="noopener noreferrer">
            suivre sur GitHub <ExternalLink size={11} />
          </a>
        </span>
      )}
      {state === 'error' && (
        <span className="admin-refresh-status admin-refresh-status--error">
          Échec du déclenchement, réessaie.
        </span>
      )}
    </div>
  )
}

const STATUS_LABEL: Record<string, string> = {
  pending:  'En attente',
  approved: 'Approuvé',
  rejected: 'Rejeté',
}

const STATUS_COLOR: Record<string, string> = {
  pending:  'var(--amber)',
  approved: 'var(--green)',
  rejected: 'var(--red)',
}

export function AdminTab() {
  const [corrections, setCorrections] = useState<Correction[]>([])
  const [loading, setLoading]         = useState(true)
  const [working, setWorking]         = useState<string | null>(null)
  const configured                    = !!supabase

  async function load() {
    setLoading(true)
    setCorrections(await fetchAllCorrections())
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  async function handleStatus(id: string, status: 'approved' | 'rejected') {
    setWorking(id)
    const ok = await updateCorrectionStatus(id, status)
    if (ok) {
      setCorrections(cs =>
        cs.map(c => c.id === id
          ? { ...c, status, reviewed_at: new Date().toISOString() }
          : c
        )
      )
    }
    setWorking(null)
  }

  function exportApproved() {
    const approved = corrections.filter(c => c.status === 'approved')
    const blob = new Blob([JSON.stringify(approved, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `corrections_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const pending  = corrections.filter(c => c.status === 'pending')
  const reviewed = corrections.filter(c => c.status !== 'pending')

  return (
    <div className="admin-tab">
      <div className="admin-header">
        <div className="admin-header-left">
          <h2 className="admin-title">Corrections communautaires</h2>
          {!configured && (
            <span className="admin-unconfigured">Supabase non configuré</span>
          )}
        </div>
        <div className="admin-toolbar">
          <RefreshDataButton />
          <button className="admin-tool-btn" onClick={load} disabled={loading} title="Rafraîchir">
            <RefreshCw size={13} className={loading ? 'spinning' : ''} />
          </button>
          {corrections.some(c => c.status === 'approved') && (
            <button className="admin-tool-btn" onClick={exportApproved} title="Exporter JSON">
              <Download size={13} />
              <span>Export JSON</span>
            </button>
          )}
        </div>
      </div>

      {!configured ? (
        <div className="admin-empty">
          <p>Configure <code>VITE_SUPABASE_URL</code> et <code>VITE_SUPABASE_ANON_KEY</code> dans <code>.env.local</code>.</p>
        </div>
      ) : loading ? (
        <div className="admin-loading">Chargement…</div>
      ) : corrections.length === 0 ? (
        <div className="admin-empty">Aucune correction pour l'instant.</div>
      ) : (
        <div className="admin-sections">
          {pending.length > 0 && (
            <section className="admin-section">
              <div className="admin-section-title">
                En attente
                <span className="admin-count-badge">{pending.length}</span>
              </div>
              {pending.map(c => (
                <CorrectionRow key={c.id} c={c} working={working} onStatus={handleStatus} />
              ))}
            </section>
          )}

          {reviewed.length > 0 && (
            <section className="admin-section admin-section--reviewed">
              <div className="admin-section-title">Traités</div>
              {reviewed.map(c => (
                <CorrectionRow key={c.id} c={c} working={working} onStatus={handleStatus} />
              ))}
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function CorrectionRow({ c, working, onStatus }: {
  c: Correction
  working: string | null
  onStatus: (id: string, status: 'approved' | 'rejected') => void
}) {
  const busy = working === c.id
  const reviewedDate = c.reviewed_at
    ? new Date(c.reviewed_at).toLocaleDateString('fr-FR')
    : null

  return (
    <div className={`admin-row admin-row--${c.status}`}>
      <div className="admin-row-left">
        {/* Field + change */}
        <div className="admin-field-change">
          <span className="admin-field-name">{FIELD_LABELS[c.field] ?? c.field}</span>
          <span className="admin-change-arrow">
            {c.current_value && (
              <><span className="admin-old">{c.current_value}</span><span className="admin-arrow"> → </span></>
            )}
            <span className="admin-new">{c.suggested_value}</span>
          </span>
        </div>

        {/* Listing + meta */}
        <div className="admin-row-meta">
          <span className="admin-listing-name">
            {c.listing_title ?? c.listing_id.slice(0, 12)}
          </span>
          {c.reporter_name && (
            <span className="admin-reporter">par {c.reporter_name}</span>
          )}
          <span className="admin-date">
            {new Date(c.created_at).toLocaleDateString('fr-FR')}
          </span>
          <span className="admin-status-badge" style={{ color: STATUS_COLOR[c.status] }}>
            {STATUS_LABEL[c.status]}
            {reviewedDate && ` le ${reviewedDate}`}
          </span>
        </div>

        {c.comment && (
          <div className="admin-comment">"{c.comment}"</div>
        )}

        {c.listing_url && (
          <a
            href={c.listing_url}
            target="_blank"
            rel="noopener noreferrer"
            className="admin-listing-link"
          >
            <ExternalLink size={11} /> Voir l'annonce
          </a>
        )}
      </div>

      <div className="admin-row-actions">
        {c.status === 'pending' ? (
          <>
            <button
              className="admin-btn admin-btn--approve"
              onClick={() => onStatus(c.id, 'approved')}
              disabled={busy}
              title="Approuver"
            >
              <CheckCircle size={13} />
              Approuver
            </button>
            <button
              className="admin-btn admin-btn--reject"
              onClick={() => onStatus(c.id, 'rejected')}
              disabled={busy}
              title="Rejeter"
            >
              <XCircle size={13} />
              Rejeter
            </button>
          </>
        ) : (
          <button
            className="admin-btn admin-btn--reopen"
            onClick={() => onStatus(c.id, c.status === 'approved' ? 'rejected' : 'approved')}
            disabled={busy}
            title="Inverser la décision"
          >
            <RotateCcw size={11} />
            Inverser
          </button>
        )}
      </div>
    </div>
  )
}

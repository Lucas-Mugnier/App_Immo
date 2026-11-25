import { useEffect, useState } from 'react'
import { AlertCircle, X } from 'lucide-react'
import { signInWithEmail, signInWithGoogle, supabase } from '@/lib/supabase'
import { useStore } from '@/store/useStore'

/**
 * Connexion — accès sur invitation uniquement.
 * Les inscriptions publiques sont fermées côté Supabase ; il n'y a donc pas de
 * formulaire d'inscription ici. Un compte connecté mais absent de la liste
 * public.allowed_users ne peut pas lire les annonces (RLS Storage).
 */
export function LoginModal() {
  const open      = useStore((s) => s.loginOpen)
  const setOpen   = useStore((s) => s.setLoginOpen)
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const configured = !!supabase

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  if (!open) return null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || !password) return
    setLoading(true)
    setError(null)
    const { error } = await signInWithEmail(email.trim(), password)
    setLoading(false)
    if (error) setError(error === 'Invalid login credentials' ? 'Email ou mot de passe incorrect.' : error)
    else setOpen(false)
  }

  async function handleGoogle() {
    setError(null)
    const { error } = await signInWithGoogle()
    if (error) setError(error)
  }

  return (
    <div className="login-overlay" role="dialog" aria-modal="true" aria-labelledby="login-title" onClick={() => setOpen(false)}>
      <div className="login-card" onClick={(e) => e.stopPropagation()}>
        <button className="login-close" onClick={() => setOpen(false)} aria-label="Fermer"><X size={16} /></button>
        <div className="login-brand" id="login-title">Alpestate</div>
        <p className="login-intro">
          L'analyse des annonces en cours est réservée aux comptes invités.
        </p>

        {!configured ? (
          <div className="login-unconfigured">
            <AlertCircle size={18} />
            <p>Supabase non configuré — connexion indisponible.</p>
          </div>
        ) : (
          <>
            <form className="login-form" onSubmit={handleSubmit}>
              <label className="login-label">
                Email
                <input className="login-input" type="email" autoComplete="email" autoFocus
                  value={email} onChange={(e) => setEmail(e.target.value)} required />
              </label>
              <label className="login-label">
                Mot de passe
                <input className="login-input" type="password" autoComplete="current-password"
                  value={password} onChange={(e) => setPassword(e.target.value)} required />
              </label>
              {error && (
                <div className="login-error" role="alert"><AlertCircle size={13} /> {error}</div>
              )}
              <button type="submit" className="login-btn-primary" disabled={loading}>
                {loading ? 'Connexion…' : 'Se connecter'}
              </button>
            </form>
            <div className="login-divider"><span>ou</span></div>
            <button className="login-btn-google" onClick={handleGoogle}>Continuer avec Google</button>
          </>
        )}
      </div>
    </div>
  )
}

import { useState } from 'react'
import { AlertCircle, Mail } from 'lucide-react'
import { signInWithEmail, signUpWithEmail, signInWithGoogle, supabase } from '@/lib/supabase'

export function LoginScreen() {
  const [mode, setMode]         = useState<'signin' | 'signup'>('signin')
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [signupDone, setSignupDone] = useState(false)
  const configured = !!supabase

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || !password) return
    setLoading(true)
    setError(null)
    const { error } = mode === 'signup'
      ? await signUpWithEmail(email.trim(), password)
      : await signInWithEmail(email.trim(), password)
    setLoading(false)
    if (error) setError(error)
    else if (mode === 'signup') setSignupDone(true)
  }

  async function handleGoogle() {
    setError(null)
    const { error } = await signInWithGoogle()
    if (error) setError(error)
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-brand">Alpestate</div>

        {!configured ? (
          <div className="login-unconfigured">
            <AlertCircle size={18} />
            <p>Supabase non configuré — connexion indisponible.</p>
          </div>
        ) : signupDone ? (
          <div className="login-success">
            <Mail size={28} />
            <p>Vérifie ta boîte mail pour confirmer ton compte, puis connecte-toi.</p>
            <button className="login-btn-secondary" onClick={() => { setSignupDone(false); setMode('signin') }}>
              Retour à la connexion
            </button>
          </div>
        ) : (
          <>
            <form className="login-form" onSubmit={handleSubmit}>
              <label className="login-label">
                Email
                <input
                  className="login-input"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                />
              </label>

              <label className="login-label">
                Mot de passe
                <input
                  className="login-input"
                  type="password"
                  autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  minLength={6}
                  required
                />
              </label>

              {error && (
                <div className="login-error">
                  <AlertCircle size={13} /> {error}
                </div>
              )}

              <button type="submit" className="login-btn-primary" disabled={loading}>
                {loading ? 'Chargement…' : mode === 'signup' ? 'Créer un compte' : 'Se connecter'}
              </button>
            </form>

            <div className="login-divider"><span>ou</span></div>

            <button className="login-btn-google" onClick={handleGoogle}>
              Continuer avec Google
            </button>

            <button
              className="login-switch"
              onClick={() => { setMode(m => m === 'signin' ? 'signup' : 'signin'); setError(null) }}
            >
              {mode === 'signin' ? "Pas encore de compte ? S'inscrire" : 'Déjà un compte ? Se connecter'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

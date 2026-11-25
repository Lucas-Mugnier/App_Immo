import { Lock, LogIn } from 'lucide-react'
import { useStore } from '@/store/useStore'
import { signOut } from '@/lib/supabase'

/** Affiché à la place d'un onglet privé quand les annonces ne sont pas accessibles. */
export function LockedPanel() {
  const status       = useStore((s) => s.dataStatus)
  const session      = useStore((s) => s.session)
  const setLoginOpen = useStore((s) => s.setLoginOpen)
  const setActiveTab = useStore((s) => s.setActiveTab)

  return (
    <div className="locked-panel">
      <div className="locked-card">
        <Lock size={22} />
        {status === 'loading' ? (
          <p>Chargement des annonces…</p>
        ) : status === 'denied' ? (
          <>
            <h2>Compte non autorisé</h2>
            <p>
              Tu es connecté avec <b>{session?.user.email}</b>, mais ce compte n'a pas
              accès aux annonces. L'accès se fait sur invitation.
            </p>
            <button className="login-btn-secondary" onClick={() => signOut()}>Changer de compte</button>
          </>
        ) : status === 'error' ? (
          <>
            <h2>Chargement impossible</h2>
            <p>Les annonces n'ont pas pu être chargées. Vérifie ta connexion puis recharge la page.</p>
            <button className="login-btn-secondary" onClick={() => window.location.reload()}>Recharger</button>
          </>
        ) : (
          <>
            <h2>Espace réservé</h2>
            <p>
              Le suivi des annonces en cours (scoring, comparateur, simulation de
              rendement) est réservé aux comptes invités. Les statistiques de marché
              et l'estimateur restent en accès libre.
            </p>
            <div className="locked-actions">
              <button className="login-btn-primary" onClick={() => setLoginOpen(true)}>
                <LogIn size={14} /> Se connecter
              </button>
              <button className="login-btn-secondary" onClick={() => setActiveTab('insights')}>
                Voir le marché
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

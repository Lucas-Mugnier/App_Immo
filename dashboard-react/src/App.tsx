import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useStore } from '@/store/useStore'
import { supabase } from '@/lib/supabase'
import { loadPrivateData } from '@/lib/privateData'
import { LoginModal } from '@/components/auth/LoginScreen'
import { LockedPanel } from '@/components/auth/LockedPanel'
import { AppShell } from '@/components/layout/AppShell'
import { AboutModal } from '@/components/layout/AboutModal'
import { EstimateurModal, EstimateurFAB } from '@/components/estimateur/EstimateurModal'
import { COUNTS } from '@/lib/data'
import type { TabId } from '@/types'

// Onglets chargés à la demande : réduit le bundle initial et garantit que le code
// module-level des onglets privés s'exécute APRÈS l'injection des annonces.
const named = <K extends string>(p: Promise<Record<K, React.ComponentType>>, k: K) =>
  p.then((m) => ({ default: m[k] }))
const InsightsTab    = lazy(() => named(import('@/components/tabs/InsightsTab'), 'InsightsTab'))
const ApprendreTab   = lazy(() => named(import('@/components/tabs/ApprendreTab'), 'ApprendreTab'))
const BiensTab       = lazy(() => named(import('@/components/tabs/BiensTab'), 'BiensTab'))
const ComparateurTab = lazy(() => named(import('@/components/tabs/ComparateurTab'), 'ComparateurTab'))
const AnalyseTab     = lazy(() => named(import('@/components/tabs/AnalyseTab'), 'AnalyseTab'))
const ProfilTab      = lazy(() => named(import('@/components/tabs/ProfilTab'), 'ProfilTab'))
const AdminTab       = lazy(() => named(import('@/components/admin/AdminTab'), 'AdminTab'))

/** Onglets qui exposent des annonces : jamais rendus sans données privées chargées. */
export const PRIVATE_TABS = new Set<TabId>(['biens', 'comparateur', 'analyse', 'profil', 'admin'])

const LEGACY: Record<string, TabId> = { apparts: 'biens', maisons: 'biens', simulation: 'analyse', optimiseur: 'analyse' }

export default function App() {
  const activeTab       = useStore((s) => s.activeTab)
  const session         = useStore((s) => s.session)
  const setSession      = useStore((s) => s.setSession)
  const dataStatus      = useStore((s) => s.dataStatus)
  const setDataStatus   = useStore((s) => s.setDataStatus)
  const dataVersion     = useStore((s) => s.dataVersion)
  const bumpDataVersion = useStore((s) => s.bumpDataVersion)
  const loadedFor       = useRef<string | null>(null)
  const [sessionChecked, setSessionChecked] = useState(!supabase)

  // Session Supabase
  useEffect(() => {
    if (!supabase) return
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setSessionChecked(true) })
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => setSession(s))
    return () => sub.subscription.unsubscribe()
  }, [setSession])

  // Chargement des annonces quand un compte se connecte
  useEffect(() => {
    const uid = session?.user.id ?? null
    if (uid === loadedFor.current) return
    if (!uid) {
      // Déconnexion après chargement : on recharge la page pour purger les annonces de la mémoire.
      if (loadedFor.current) { window.location.reload(); return }
      setDataStatus('anon')
      return
    }
    loadedFor.current = uid
    setDataStatus('loading')
    loadPrivateData().then((st) => {
      setDataStatus(st)
      if (st === 'ready') bumpDataVersion()
    })
  }, [session, setDataStatus, bumpDataVersion])

  // Visiteur anonyme revenant avec un onglet privé mémorisé : on ouvre le Marché
  // plutôt qu'un écran verrouillé (une seule fois, au premier chargement).
  const setActiveTab = useStore((s) => s.setActiveTab)
  const firstResolve = useRef(true)
  useEffect(() => {
    if (!sessionChecked) return
    if (session && (dataStatus === 'anon' || dataStatus === 'loading')) return // chargement en cours
    if (!firstResolve.current) return
    firstResolve.current = false
    const t: TabId = LEGACY[activeTab as string] ?? activeTab
    if (dataStatus !== 'ready' && PRIVATE_TABS.has(t)) setActiveTab('insights')
  }, [sessionChecked, session, dataStatus, activeTab, setActiveTab])

  const tab: TabId = LEGACY[activeTab as string] ?? activeTab
  const ready = dataStatus === 'ready'
  const locked = PRIVATE_TABS.has(tab) && !ready

  return (
    <>
      <AppShell
        apportCount={ready ? COUNTS.apparts : undefined}
        maisonCount={ready ? COUNTS.maisons : undefined}
      >
        {/* key: remonte l'onglet quand les annonces arrivent (useMemo/state recalculés) */}
        <div key={`${tab}-${dataVersion}`} className="h-full overflow-hidden flex flex-col tab-enter">
          <Suspense fallback={<div className="tab-loading">Chargement…</div>}>
            {locked ? <LockedPanel /> : (
              <>
                {tab === 'biens'       && <BiensTab />}
                {tab === 'insights'    && <InsightsTab />}
                {tab === 'comparateur' && <ComparateurTab />}
                {tab === 'analyse'     && <AnalyseTab />}
                {tab === 'apprendre'   && <ApprendreTab />}
                {tab === 'profil'      && <ProfilTab />}
                {tab === 'admin'       && <AdminTab />}
              </>
            )}
          </Suspense>
        </div>
      </AppShell>

      {/* Global modals */}
      <EstimateurModal />
      <EstimateurFAB />
      <LoginModal />
      <AboutModal />
    </>
  )
}

import { useStore } from '@/store/useStore'
import { AppShell } from '@/components/layout/AppShell'
import { BiensTab } from '@/components/tabs/BiensTab'
import { InsightsTab } from '@/components/tabs/InsightsTab'
import { ComparateurTab } from '@/components/tabs/ComparateurTab'
import { AnalyseTab } from '@/components/tabs/AnalyseTab'
import { ApprendreTab } from '@/components/tabs/ApprendreTab'
import { ProfilTab } from '@/components/tabs/ProfilTab'
import { EstimateurModal, EstimateurFAB } from '@/components/estimateur/EstimateurModal'
import { AdminTab } from '@/components/admin/AdminTab'
import { COUNTS } from '@/lib/data'

export default function App() {
  const activeTab = useStore((s) => s.activeTab)

  // normalize legacy persisted tab values
  const LEGACY: Record<string, string> = { apparts: 'biens', maisons: 'biens', simulation: 'analyse', optimiseur: 'analyse' }
  const tab = LEGACY[activeTab as string] ?? activeTab

  return (
    <>
      <AppShell
        apportCount={COUNTS.apparts}
        maisonCount={COUNTS.maisons}
      >
        <div key={tab} className="h-full overflow-hidden flex flex-col tab-enter">
          {tab === 'biens'       && <BiensTab />}
          {tab === 'insights'    && <InsightsTab />}
          {tab === 'comparateur' && <ComparateurTab />}
          {tab === 'analyse'     && <AnalyseTab />}
          {tab === 'apprendre'   && <ApprendreTab />}
          {tab === 'profil'      && <ProfilTab />}
          {tab === 'admin'       && <AdminTab />}
        </div>
      </AppShell>

      {/* Global modals */}
      <EstimateurModal />
      <EstimateurFAB />
    </>
  )
}

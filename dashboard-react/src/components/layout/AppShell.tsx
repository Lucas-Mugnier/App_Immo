import { useEffect } from 'react'
import { useStore, useIsAdmin } from '@/store/useStore'
import { signOut } from '@/lib/supabase'
import type { TabId } from '@/types'
import { cn } from '@/lib/utils'
import { BarChart2, Scale, LineChart, Moon, Sun, Building2, ShieldCheck, BookOpen, User, LogOut } from 'lucide-react'

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'biens',       label: 'Biens',        icon: <Building2 size={13} /> },
  { id: 'insights',    label: 'Insights',     icon: <BarChart2 size={13} /> },
  { id: 'comparateur', label: 'Comparateur',  icon: <Scale size={13} /> },
  { id: 'analyse',     label: 'Analyse',      icon: <LineChart size={13} /> },
  { id: 'apprendre',   label: "S'instruire",  icon: <BookOpen size={13} /> },
  { id: 'profil',      label: 'Profil',       icon: <User size={13} /> },
]

interface Props {
  children: React.ReactNode
  apportCount?: number
  maisonCount?: number
}

export function AppShell({ children, apportCount, maisonCount }: Props) {
  const { activeTab, setActiveTab, dark, setDark } = useStore()
  const isAdmin = useIsAdmin()

  // migrate legacy persisted tab values
  const LEGACY: Record<string, TabId> = { apparts: 'biens', maisons: 'biens', simulation: 'analyse', optimiseur: 'analyse' }
  const resolvedTab: TabId = LEGACY[activeTab as string] ?? activeTab

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add('dark')
      localStorage.setItem('alpestate-theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      localStorage.setItem('alpestate-theme', 'light')
    }
  }, [dark])

  const toggleDark = () => setDark(!dark)

  return (
    <div className="flex flex-col h-dvh overflow-hidden">
      {/* Header */}
      <header className="app-header">
        {/* Mountain panorama background */}
        <svg
          className="mountain-bg"
          viewBox="0 0 1400 88"
          preserveAspectRatio="xMidYMax slice"
          aria-hidden="true"
        >
          {/* Far mountains */}
          <path
            fillOpacity="0.06"
            fill="currentColor"
            d="M0,68
               C40,62 90,52 150,38 C190,28 228,8 268,0
               C308,8 342,36 390,52 C430,62 480,66 530,56
               C558,48 572,22 590,2
               C608,20 624,48 662,56
               C702,66 750,68 802,56
               C840,48 878,26 940,10
               C972,4 1002,6 1032,10
               C1062,14 1102,38 1158,54
               C1198,64 1260,68 1320,68
               L1400,68 L0,68Z"
          />
          {/* Mid mountains */}
          <path
            fillOpacity="0.12"
            fill="currentColor"
            d="M0,68
               C55,64 112,58 168,48
               C212,40 248,30 298,22
               C334,16 362,20 400,32
               C436,44 468,50 508,40
               C536,32 562,16 602,6
               C626,14 650,36 692,44
               C732,54 778,60 822,48
               C860,40 898,22 952,12
               C990,4 1028,8 1070,24
               C1110,36 1160,54 1222,62
               C1270,66 1328,68 1400,68
               L1400,68 L0,68Z"
          />
          {/* Near ridge */}
          <path
            fillOpacity="0.18"
            fill="currentColor"
            d="M0,68
               C60,64 120,60 200,56
               C260,52 310,54 380,58
               C440,62 500,60 560,62
               C620,58 700,60 780,56
               C840,52 900,54 960,60
               C1020,58 1080,56 1150,60
               C1220,56 1310,62 1400,66
               L1400,68 L0,68Z"
          />
        </svg>

        <div className="header-content">
          {/* Left — counts */}
          <div className="header-left">
            {apportCount != null && (
              <span className="num text-faint" style={{ fontSize: '11px' }}>
                {apportCount}A · {maisonCount}M
              </span>
            )}
          </div>

          {/* Centre — logo in glass pill */}
          <div className="header-logo-glass">
            <img src="/logo.png" alt="ALPESTATE" className="header-logo-img" />
          </div>

          {/* Right — controls */}
          <div className="header-right">
            <span className="chip text-[0.65rem]"
              style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-faint)' }}>
              <span style={{ color: 'var(--accent)', fontWeight: 700 }}>▲</span>
              &nbsp;Chamonix · Argentière
            </span>
            <button
              className="theme-toggle"
              onClick={toggleDark}
              title={dark ? 'Mode clair' : 'Mode sombre'}
              aria-label={dark ? 'Passer au mode clair' : 'Passer au mode sombre'}
            >
              {dark ? <Sun size={14} /> : <Moon size={14} />}
            </button>
            <button
              className="theme-toggle"
              onClick={() => signOut()}
              title="Se déconnecter"
              aria-label="Se déconnecter"
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </header>

      {/* Tab bar */}
      <nav className="tab-bar">
        {TABS.filter((t) => t.id !== 'profil').map((tab) => (
          <button
            key={tab.id}
            className={cn('tab-btn', resolvedTab === tab.id && 'active')}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
        {isAdmin && (
          <button
            className={cn('tab-btn tab-btn--admin', resolvedTab === 'admin' && 'active')}
            onClick={() => setActiveTab('admin')}
            title="Mode admin"
          >
            <ShieldCheck size={13} />
            <span>Admin</span>
          </button>
        )}
        <div style={{ flex: 1 }} />
        <button
          className={cn('tab-btn', resolvedTab === 'profil' && 'active')}
          onClick={() => setActiveTab('profil')}
        >
          <User size={13} />
          <span>Profil</span>
        </button>
      </nav>

      {/* Content */}
      <main className="flex-1 overflow-hidden">
        {children}
      </main>
    </div>
  )
}

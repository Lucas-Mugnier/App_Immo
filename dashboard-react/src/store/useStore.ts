import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type {
  TabId, BienType, AppartFilters, MaisonFilters, SortState,
  InsightType, MapMetric, EstimateurState, WatchlistStatus, WatchlistEntry, InvestProfile,
  FiscalMode, SimObjectif, SimParams,
} from '@/types'
import type { ProfilAcquisition } from '@/lib/optimizer'

const STORAGE_KEY = 'appart-alert-state'

interface StoreState {
  // Theme
  dark: boolean
  setDark: (d: boolean) => void

  // Tab
  activeTab: TabId
  setActiveTab: (tab: TabId) => void
  bienTypes: BienType[]
  toggleBienType: (t: BienType) => void
  setBienTypes: (types: BienType[]) => void

  // Overrides (persist)
  seen: Record<string, boolean>
  rejected: Record<string, boolean>
  hidden: Record<string, boolean>
  notes: Record<string, string>
  locationEdits: Record<string, string>
  setSeen: (id: string, val: boolean) => void
  setRejected: (id: string, val: boolean) => void
  setHidden: (id: string, val: boolean) => void
  setNote: (id: string, note: string) => void
  setLocationEdit: (id: string, loc: string) => void

  // Apparts filters & sort
  appartFilters: AppartFilters
  setAppartFilters: (f: Partial<AppartFilters>) => void
  appartSort: SortState
  setAppartSort: (s: SortState) => void

  // Maisons filters & sort
  maisonFilters: MaisonFilters
  setMaisonFilters: (f: Partial<MaisonFilters>) => void
  maisonSort: SortState
  setMaisonSort: (s: SortState) => void

  // Insights
  insightType: InsightType
  setInsightType: (t: InsightType) => void
  mapMetric: MapMetric
  setMapMetric: (m: MapMetric) => void

  // Estimateur
  estimateur: EstimateurState
  openEstimateur: (opts: Partial<EstimateurState>) => void
  closeEstimateur: () => void
  updateEstimateur: (opts: Partial<EstimateurState>) => void

  // Watchlist
  watchlist: Record<string, WatchlistEntry>
  setWatchlist: (key: string, entry: WatchlistEntry | null) => void
  updateWatchlistStatus: (key: string, status: WatchlistStatus) => void

  // Invest profile
  investProfile: InvestProfile
  setInvestProfile: (p: Partial<InvestProfile>) => void

  // Compare
  compareIds: string[]
  toggleCompare: (key: string) => void
  clearCompare: () => void

  // Simulation preselect (navigation state, not persisted)
  simPreselect: string | null
  setSimPreselect: (id: string | null) => void

  // Simulation params (survives tab switches, not persisted to localStorage)
  simParams: SimParams
  setSimParams: (p: Partial<SimParams>) => void

  // Profil acquéreur (persisted)
  profilAcquisition: ProfilAcquisition
  setProfilAcquisition: (p: ProfilAcquisition) => void

  // Capacité d'emprunt (persisted)
  salaireNet: number
  dettesExistantes: number
  setSalaireNet: (v: number) => void
  setDettesExistantes: (v: number) => void
}

const defaultAppartFilters: AppartFilters = {
  search: '',
  minScore: 0,
  minPrice: 0,
  maxPrice: 2_000_000,
  minSurface: 0,
  minRooms: 0,
  minYield: 0,
  maxDpe: '',
  location: [],
  priceDropOnly: false,
  freshOnly: false,
  showHidden: false,
  showRejected: false,
  hideStructured: true,
}

const defaultMaisonFilters: MaisonFilters = {
  search: '',
  minScore: 0,
  minPrice: 0,
  maxPrice: 5_000_000,
  minSurface: 0,
  minTerrain: 0,
  minRooms: 0,
  section: [],
  renovationFilter: 'all',
  showRejected: false,
  hideStructured: true,
}

const defaultEstimateur: EstimateurState = {
  open: false,
  propType: 'appart',
  surface: 60,
  rooms: 3,
  commune: 'Chamonix',
  price: 500_000,
  etat: 'bon',
  vue: 'default',
  etage: 'inter',
  parking: 'aucun',
  ext: 'aucun',
  surfTerrain: 500,
  secteur: 'Chamonix Centre',
}

export const useStore = create<StoreState>()(
  persist(
    (set) => ({
      dark: localStorage.getItem('alpestate-theme') === 'dark',
      setDark: (d) => set({ dark: d }),

      activeTab: 'biens',
      setActiveTab: (tab) => set({ activeTab: tab }),
      bienTypes: ['apparts'],
      toggleBienType: (t) => set((s) => {
        const has = s.bienTypes.includes(t)
        if (has && s.bienTypes.length === 1) return s // keep at least one
        return { bienTypes: has ? s.bienTypes.filter((x) => x !== t) : [...s.bienTypes, t] }
      }),
      setBienTypes: (types) => set({ bienTypes: types.length > 0 ? types : ['apparts'] }),

      seen: {},
      rejected: {},
      hidden: {},
      notes: {},
      locationEdits: {},

      setSeen: (id, val) =>
        set((s) => ({ seen: { ...s.seen, [id]: val } })),
      setRejected: (id, val) =>
        set((s) => ({ rejected: { ...s.rejected, [id]: val } })),
      setHidden: (id, val) =>
        set((s) => ({ hidden: { ...s.hidden, [id]: val } })),
      setNote: (id, note) =>
        set((s) => ({ notes: { ...s.notes, [id]: note } })),
      setLocationEdit: (id, loc) =>
        set((s) => ({ locationEdits: { ...s.locationEdits, [id]: loc } })),

      appartFilters: defaultAppartFilters,
      setAppartFilters: (f) =>
        set((s) => ({ appartFilters: { ...s.appartFilters, ...f } })),
      appartSort: { key: 'score', dir: 'desc' },
      setAppartSort: (s) => set({ appartSort: s }),

      maisonFilters: defaultMaisonFilters,
      setMaisonFilters: (f) =>
        set((s) => ({ maisonFilters: { ...s.maisonFilters, ...f } })),
      maisonSort: { key: 'avm_score', dir: 'desc' },
      setMaisonSort: (s) => set({ maisonSort: s }),

      insightType: 'all',
      setInsightType: (t) => set({ insightType: t }),
      mapMetric: 'pm2',
      setMapMetric: (m) => set({ mapMetric: m }),

      estimateur: defaultEstimateur,
      openEstimateur: (opts) =>
        set((s) => ({ estimateur: { ...s.estimateur, ...opts, open: true } })),
      closeEstimateur: () =>
        set((s) => ({ estimateur: { ...s.estimateur, open: false } })),
      updateEstimateur: (opts) =>
        set((s) => ({ estimateur: { ...s.estimateur, ...opts } })),

      watchlist: {},
      setWatchlist: (key, entry) =>
        set((s) => {
          const next = { ...s.watchlist }
          if (entry === null) delete next[key]; else next[key] = entry
          return { watchlist: next }
        }),
      updateWatchlistStatus: (key, status) =>
        set((s) => s.watchlist[key]
          ? { watchlist: { ...s.watchlist, [key]: { ...s.watchlist[key], status } } }
          : s
        ),

      investProfile: {
        budgetMax: 0, surfaceMin: 0, rendementMin: 0,
        scoreMin: 0, types: ['appart', 'maison'], secteurs: [], strategie: 'mixte',
      },
      setInvestProfile: (p) =>
        set((s) => ({ investProfile: { ...s.investProfile, ...p } })),

      compareIds: [],
      toggleCompare: (key) => set((s) => {
        const has = s.compareIds.includes(key)
        if (has) return { compareIds: s.compareIds.filter((k) => k !== key) }
        if (s.compareIds.length >= 4) return s
        return { compareIds: [...s.compareIds, key] }
      }),
      clearCompare: () => set({ compareIds: [] }),

      simPreselect: null,
      setSimPreselect: (id) => set({ simPreselect: id }),

      simParams: {
        selectedId: '',
        mode: 'lmnp_reel' as FiscalMode,
        tmi: 30, taux: 3.5, duree: 20,
        loyer: 1500, chargesAn: 2400, apportEur: 80_000,
        fraisNotaireP: 7.5,
        indexLoyer: 2, indexPrix: 3,
        revente: 10, planRevente: true,
        objectif: 'tri' as SimObjectif,
      },
      setSimParams: (p) => set((s) => ({ simParams: { ...s.simParams, ...p } })),

      profilAcquisition: 'locatif' as ProfilAcquisition,
      setProfilAcquisition: (p) => set({ profilAcquisition: p }),

      salaireNet: 0,
      dettesExistantes: 0,
      setSalaireNet: (v) => set({ salaireNet: v }),
      setDettesExistantes: (v) => set({ dettesExistantes: v }),
    }),
    {
      name: STORAGE_KEY,
      partialize: (state) => ({
        seen: state.seen,
        rejected: state.rejected,
        hidden: state.hidden,
        notes: state.notes,
        locationEdits: state.locationEdits,
        activeTab: state.activeTab,
        bienTypes: state.bienTypes,
        watchlist: state.watchlist,
        investProfile: state.investProfile,
        compareIds: state.compareIds,
        profilAcquisition: state.profilAcquisition,
        salaireNet: state.salaireNet,
        dettesExistantes: state.dettesExistantes,
      }),
    }
  )
)

import { create } from 'zustand'

interface ScheduleStore {
  selectedSession: string
  selectedMatch: string | null
  swapMode: { first: string | null }
  filters: { categories: string[]; search: string }
  zoom: number
  conflictPanelOpen: boolean
  unscheduledPanelOpen: boolean
  configWizardOpen: boolean
  importDialogOpen: boolean
  printDialogOpen: boolean

  setSelectedSession: (session: string) => void
  setSelectedMatch: (matchId: string | null) => void
  startSwap: (matchId: string) => void
  cancelSwap: () => void
  setFilters: (filters: Partial<{ categories: string[]; search: string }>) => void
  setZoom: (zoom: number) => void
  toggleConflictPanel: () => void
  toggleUnscheduledPanel: () => void
  setConfigWizardOpen: (open: boolean) => void
  setImportDialogOpen: (open: boolean) => void
  setPrintDialogOpen: (open: boolean) => void
}

export const useScheduleStore = create<ScheduleStore>((set) => ({
  selectedSession: '',
  selectedMatch: null,
  swapMode: { first: null },
  filters: { categories: [], search: '' },
  zoom: 1,
  conflictPanelOpen: true,
  unscheduledPanelOpen: true,
  configWizardOpen: false,
  importDialogOpen: false,
  printDialogOpen: false,

  setSelectedSession: (session) => set({ selectedSession: session }),
  setSelectedMatch: (matchId) => set({ selectedMatch: matchId }),
  startSwap: (matchId) => set({ swapMode: { first: matchId } }),
  cancelSwap: () => set({ swapMode: { first: null } }),
  setFilters: (filters) => set((s) => ({ filters: { ...s.filters, ...filters } })),
  setZoom: (zoom) => set({ zoom }),
  toggleConflictPanel: () => set((s) => ({ conflictPanelOpen: !s.conflictPanelOpen })),
  toggleUnscheduledPanel: () => set((s) => ({ unscheduledPanelOpen: !s.unscheduledPanelOpen })),
  setConfigWizardOpen: (open) => set({ configWizardOpen: open }),
  setImportDialogOpen: (open) => set({ importDialogOpen: open }),
  setPrintDialogOpen: (open) => set({ printDialogOpen: open }),
}))

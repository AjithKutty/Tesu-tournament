import { apiGet, apiPost, apiPostFile, apiPostHtml } from './client'
import type {
  TournamentConfig, ScheduleState, ImportResponse,
  MoveResponse, SwapResponse, ValidateResponse,
  MatchCard, ResultUpdateResponse,
} from '../types/api'

// Config
export const getConfig = () => apiGet<TournamentConfig>('/api/config')
export const setConfig = (config: TournamentConfig) => apiPost<TournamentConfig>('/api/config', config)
export const getTemplates = () => apiGet<{ templates: { id: string; name: string }[] }>('/api/config/templates')
export const loadConfig = (path: string) => apiPost<TournamentConfig>('/api/config/load', { path })
export const saveConfig = (path: string) => apiPost<{ path: string }>('/api/config/save', { path })
export const setDivisionMap = (map: Record<string, string>) =>
  apiPost<TournamentConfig>('/api/config/division-map', { division_category_map: map })

// Import
export const importExcel = (file: File) => apiPostFile<ImportResponse>('/api/import/excel', file)
export const importWeb = (url: string, fullResults = false) =>
  apiPost<ImportResponse>('/api/import/web', { url, full_results: fullResults })

// Schedule
export const getSchedule = () => apiGet<ScheduleState>('/api/schedule')
export const generateSchedule = (keepPinned = true) =>
  apiPost<ScheduleState>('/api/schedule/generate', { keep_pinned: keepPinned })
export const moveMatch = (matchId: string, court: number, timeMinute: number) =>
  apiPost<MoveResponse>('/api/schedule/move', { match_id: matchId, court, time_minute: timeMinute })
export const swapMatches = (a: string, b: string) =>
  apiPost<SwapResponse>('/api/schedule/swap', { match_id_a: a, match_id_b: b })
export const unscheduleMatch = (matchId: string) =>
  apiPost<MatchCard>('/api/schedule/unschedule', { match_id: matchId })
export const pinMatch = (matchId: string, pinned: boolean) =>
  apiPost<MatchCard>('/api/schedule/pin', { match_id: matchId, pinned })
export const validateSchedule = () => apiGet<ValidateResponse>('/api/schedule/validate')
export const validateMove = (matchId: string, court: number, timeMinute: number) =>
  apiPost<ValidateResponse>('/api/schedule/validate-move', { match_id: matchId, court, time_minute: timeMinute })

// Results
export const updateResult = (matchId: string, score: string) =>
  apiPost<ResultUpdateResponse>('/api/results/update', { match_id: matchId, score })

// Print
export const getMatchCardsHtml = (timeMinute?: number, matchIds?: string[]) =>
  apiPostHtml('/api/print/match-cards', { time_minute: timeMinute ?? null, match_ids: matchIds ?? null })

// Export
export const exportWebsite = () => apiPost<{ path: string }>('/api/export/website')
export const exportSchedule = () => apiPost<{ path: string }>('/api/export/schedule')

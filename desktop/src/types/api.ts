// Types matching backend Pydantic models

export interface CourtAvailability {
  court: number
  available_from: string
  available_to: string
}

export interface DayConfig {
  label: string
  date?: string | null
  courts: CourtAvailability[]
}

export interface SessionConfig {
  name: string
  day_index: number
  start_time: string
  end_time: string
}

export interface CategoryConfig {
  id: string
  label: string
  color: string
  duration_minutes: number
  rest_minutes: number
  required_courts?: number[] | null
  preferred_courts?: number[] | null
  sf_final_day_index?: number | null
}

export interface TournamentConfig {
  name: string
  slot_duration_minutes: number
  days: DayConfig[]
  sessions: SessionConfig[]
  categories: CategoryConfig[]
  division_category_map: Record<string, string>
}

export interface MatchCard {
  id: string
  division_code: string
  division_name: string
  category_id: string
  category_label: string
  category_color: string
  round_name: string
  match_num: number
  player1: string
  player2: string
  duration_min: number
  is_sf_or_final: boolean
  has_real_players: boolean
  prerequisites: string[]
  result?: string | null
  court?: number | null
  time_minute?: number | null
  time_display?: string | null
  day?: string | null
  pinned: boolean
  conflict_ids: string[]
}

export interface Conflict {
  id: string
  type: string
  severity: 'error' | 'warning'
  match_ids: string[]
  message: string
  player?: string | null
}

export interface SessionInfo {
  name: string
  day_label: string
  start_time: string
  end_time: string
  start_minute: number
  end_minute: number
  courts: number[]
  match_count: number
}

export interface ScheduleState {
  matches: MatchCard[]
  conflicts: Conflict[]
  unscheduled: string[]
  sessions: SessionInfo[]
}

export interface DivisionSummary {
  code: string
  name: string
  suggested_category?: string | null
}

export interface ImportResponse {
  tournament_name: string
  division_count: number
  match_count: number
  player_count: number
  divisions: DivisionSummary[]
}

export interface MoveResponse {
  match: MatchCard
  conflicts: Conflict[]
}

export interface SwapResponse {
  matches: MatchCard[]
  conflicts: Conflict[]
}

export interface ValidateResponse {
  conflicts: Conflict[]
}

export interface ResultUpdateResponse {
  match: MatchCard
  resolved_matches: MatchCard[]
}

// Electron API exposed via preload
declare global {
  interface Window {
    electronAPI?: {
      openFile: (filters: { name: string; extensions: string[] }[]) => Promise<string | null>
      saveFile: (defaultPath: string, filters: { name: string; extensions: string[] }[]) => Promise<string | null>
      printHtml: (html: string) => Promise<boolean>
      printPdf: (html: string, savePath: string) => Promise<string>
    }
  }
}

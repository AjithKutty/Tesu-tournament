import { useMemo, useCallback, useState } from 'react'
import { DndContext, DragEndEvent, DragOverlay, DragStartEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { DraggableMatchCard } from './DraggableMatchCard'
import { DroppableCell } from './DroppableCell'
import { MatchCard } from './MatchCard'
import { useMoveMatch, useSwapMatches } from '../../hooks/useSchedule'
import { useScheduleStore } from '../../store/scheduleStore'
import type { MatchCard as MatchCardType, SessionInfo, TournamentConfig } from '../../types/api'

interface Props {
  matches: MatchCardType[]
  session: SessionInfo | null
  config: TournamentConfig
  /** Wraps children in the same DndContext so external panels can participate */
  children?: React.ReactNode
}

function timeStrToMinutes(time: string): number {
  const [h, m] = time.split(':').map(Number)
  return h * 60 + m
}

function minutesToTimeStr(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`
}

export function ScheduleBoard({ matches, session, config, children }: Props) {
  const moveMutation = useMoveMatch()
  const swapMutation = useSwapMatches()
  const { swapMode, cancelSwap } = useScheduleStore()
  const [activeDragMatch, setActiveDragMatch] = useState<MatchCardType | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  )

  const slotDuration = config.slot_duration_minutes || 30

  const timeSlots = useMemo(() => {
    if (!session) return []
    const startMin = timeStrToMinutes(session.start_time)
    const endMin = timeStrToMinutes(session.end_time)
    const slots: { minute: number; display: string }[] = []
    for (let m = startMin; m < endMin; m += slotDuration) {
      slots.push({ minute: m, display: minutesToTimeStr(m) })
    }
    return slots
  }, [session, slotDuration])

  const courts = session?.courts ?? []

  const gridMap = useMemo(() => {
    const map = new Map<string, MatchCardType>()
    if (!session) return map
    for (const match of matches) {
      if (match.court != null && match.time_display && match.day) {
        const matchInSession = match.time_display >= session.start_time &&
          match.time_display < session.end_time &&
          match.day === session.day_label
        if (matchInSession) {
          map.set(`${match.court}:${match.time_display}`, match)
        }
      }
    }
    return map
  }, [matches, session])

  const isOccupiedBySpan = useCallback((court: number, timeDisplay: string): boolean => {
    if (!session) return false
    const timeMin = timeStrToMinutes(timeDisplay)
    for (let offset = slotDuration; offset < 120; offset += slotDuration) {
      const prevMin = timeMin - offset
      if (prevMin < timeStrToMinutes(session.start_time)) break
      const prevDisplay = minutesToTimeStr(prevMin)
      const prevMatch = gridMap.get(`${court}:${prevDisplay}`)
      if (prevMatch && prevMatch.duration_min > offset) {
        return true
      }
    }
    return false
  }, [gridMap, session, slotDuration])

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const match = event.active.data.current?.match as MatchCardType | undefined
    if (match) setActiveDragMatch(match)
  }, [])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    setActiveDragMatch(null)
    const { active, over } = event
    if (!over) return

    const draggedMatchId = active.id as string
    const dropData = over.data.current as { court?: number; timeMinute?: number } | undefined
    if (!dropData || dropData.court == null || dropData.timeMinute == null) return

    const dropKey = `${dropData.court}:${minutesToTimeStr(dropData.timeMinute)}`
    const existingMatch = gridMap.get(dropKey)

    if (existingMatch && existingMatch.id !== draggedMatchId) {
      swapMutation.mutate({ a: draggedMatchId, b: existingMatch.id })
    } else {
      moveMutation.mutate({
        matchId: draggedMatchId,
        court: dropData.court,
        timeMinute: dropData.timeMinute,
      })
    }
  }, [gridMap, moveMutation, swapMutation])

  const handleCellClick = useCallback((court: number, timeMinute: number, existingMatch?: MatchCardType) => {
    if (swapMode.first && existingMatch && existingMatch.id !== swapMode.first) {
      swapMutation.mutate({ a: swapMode.first, b: existingMatch.id })
      cancelSwap()
    } else if (swapMode.first && !existingMatch) {
      moveMutation.mutate({ matchId: swapMode.first, court, timeMinute })
      cancelSwap()
    }
  }, [swapMode, swapMutation, moveMutation, cancelSwap])

  if (!session) {
    return <div className="empty-state">No session selected</div>
  }

  const gridStyle: React.CSSProperties = {
    display: 'grid',
    gridTemplateColumns: `60px repeat(${courts.length}, minmax(140px, 1fr))`,
    gridTemplateRows: `auto repeat(${timeSlots.length}, minmax(60px, auto))`,
    gap: '1px',
    background: 'var(--border)',
    minWidth: 'fit-content',
  }

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      <div className="schedule-board-container">
        <div style={gridStyle}>
          <div className="court-header-corner" />
          {courts.map(court => (
            <div key={court} className="court-header-cell">
              Court {court}
            </div>
          ))}

          {timeSlots.map(slot => (
            <>
              <div key={`time-${slot.display}`} className="time-cell">
                {slot.display}
              </div>
              {courts.map(court => {
                const match = gridMap.get(`${court}:${slot.display}`)
                const occupied = isOccupiedBySpan(court, slot.display)

                if (occupied) return null

                const rowSpan = match ? Math.ceil(match.duration_min / slotDuration) : 1

                return (
                  <DroppableCell
                    key={`${court}-${slot.display}`}
                    court={court}
                    timeDisplay={slot.display}
                    timeMinute={slot.minute}
                    rowSpan={rowSpan}
                  >
                    <div
                      style={{ height: '100%' }}
                      onClick={() => handleCellClick(court, slot.minute, match)}
                    >
                      {match && <DraggableMatchCard match={match} />}
                    </div>
                  </DroppableCell>
                )
              })}
            </>
          ))}
        </div>
      </div>

      {/* Render children (e.g. UnscheduledPanel) inside same DndContext */}
      {children}

      <DragOverlay>
        {activeDragMatch && (
          <div style={{ width: '160px', height: '80px', opacity: 0.9 }}>
            <MatchCard match={activeDragMatch} />
          </div>
        )}
      </DragOverlay>
    </DndContext>
  )
}

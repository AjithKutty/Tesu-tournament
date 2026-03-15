import { useConfig, useSchedule } from './hooks/useSchedule'
import { useScheduleStore } from './store/scheduleStore'
import { Toolbar } from './components/Layout/Toolbar'
import { SessionTabs } from './components/Layout/SessionTabs'
import { ScheduleBoard } from './components/ScheduleBoard/ScheduleBoard'
import { ConflictPanel } from './components/Panels/ConflictPanel'
import { UnscheduledPanel } from './components/Panels/UnscheduledPanel'
import { ImportDialog } from './components/Modals/ImportDialog'
import { MatchDetailModal } from './components/Modals/MatchDetailModal'
import { PrintDialog } from './components/Modals/PrintDialog'

export default function App() {
  const { data: config } = useConfig()
  const { data: schedule, isLoading } = useSchedule()
  const {
    selectedSession,
    selectedMatch,
    setSelectedMatch,
    importDialogOpen,
    printDialogOpen,
    conflictPanelOpen,
    unscheduledPanelOpen,
  } = useScheduleStore()

  const hasData = schedule && schedule.matches.length > 0
  const currentSession = schedule?.sessions.find(s => s.name === selectedSession) || schedule?.sessions[0]
  const unscheduledMatches = hasData ? schedule.matches.filter(m => m.court == null) : []

  return (
    <>
      <Toolbar config={config ?? null} hasData={!!hasData} />

      {config && schedule && schedule.sessions.length > 0 && (
        <SessionTabs sessions={schedule.sessions} />
      )}

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {isLoading ? (
            <div className="empty-state">Loading...</div>
          ) : !hasData ? (
            <div className="empty-state">
              <div>No tournament data loaded</div>
              <button onClick={() => useScheduleStore.getState().setImportDialogOpen(true)}>
                Import Data
              </button>
            </div>
          ) : (
            <ScheduleBoard
              matches={schedule.matches}
              session={currentSession ?? null}
              config={config!}
            >
              {unscheduledPanelOpen && (
                <UnscheduledPanel matches={unscheduledMatches} />
              )}
            </ScheduleBoard>
          )}
        </div>

        {hasData && conflictPanelOpen && (
          <ConflictPanel conflicts={schedule.conflicts} />
        )}
      </div>

      {importDialogOpen && (
        <ImportDialog onClose={() => useScheduleStore.getState().setImportDialogOpen(false)} />
      )}

      {printDialogOpen && hasData && (
        <PrintDialog
          sessions={schedule!.sessions}
          onClose={() => useScheduleStore.getState().setPrintDialogOpen(false)}
        />
      )}

      {selectedMatch && (
        <MatchDetailModal
          matchId={selectedMatch}
          matches={schedule?.matches ?? []}
          onClose={() => setSelectedMatch(null)}
        />
      )}
    </>
  )
}

import { useEffect } from 'react'
import { useScheduleStore } from '../../store/scheduleStore'
import type { SessionInfo } from '../../types/api'

interface Props {
  sessions: SessionInfo[]
}

export function SessionTabs({ sessions }: Props) {
  const { selectedSession, setSelectedSession } = useScheduleStore()

  // Auto-select first session if none selected
  useEffect(() => {
    if (!selectedSession && sessions.length > 0) {
      setSelectedSession(sessions[0].name)
    }
  }, [sessions, selectedSession, setSelectedSession])

  const containerStyle: React.CSSProperties = {
    display: 'flex',
    gap: '0.3rem',
    padding: '0.4rem 1rem',
    background: 'var(--card-bg)',
    borderBottom: '2px solid var(--border)',
    flexShrink: 0,
    overflowX: 'auto',
  }

  return (
    <div style={containerStyle}>
      {sessions.map(session => (
        <button
          key={session.name}
          onClick={() => setSelectedSession(session.name)}
          style={{
            padding: '0.5rem 1rem',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            background: selectedSession === session.name ? 'var(--primary)' : 'var(--bg)',
            color: selectedSession === session.name ? 'white' : 'var(--text)',
            fontSize: '0.82rem',
            fontWeight: 600,
            whiteSpace: 'nowrap',
            transition: 'all 0.2s',
          }}
        >
          {session.name}
          <span style={{
            marginLeft: '0.4rem',
            fontSize: '0.7rem',
            opacity: 0.7,
          }}>
            ({session.match_count})
          </span>
        </button>
      ))}
    </div>
  )
}

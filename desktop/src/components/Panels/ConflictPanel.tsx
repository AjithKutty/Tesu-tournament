import { useScheduleStore } from '../../store/scheduleStore'
import type { Conflict } from '../../types/api'

interface Props {
  conflicts: Conflict[]
}

export function ConflictPanel({ conflicts }: Props) {
  const { setSelectedMatch } = useScheduleStore()
  const errors = conflicts.filter(c => c.severity === 'error')
  const warnings = conflicts.filter(c => c.severity === 'warning')

  const panelStyle: React.CSSProperties = {
    width: '280px',
    flexShrink: 0,
    background: 'var(--card-bg)',
    borderLeft: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  }

  const headerStyle: React.CSSProperties = {
    padding: '0.6rem 0.8rem',
    borderBottom: '1px solid var(--border)',
    fontWeight: 700,
    fontSize: '0.85rem',
    display: 'flex',
    gap: '0.5rem',
    alignItems: 'center',
  }

  const handleConflictClick = (conflict: Conflict) => {
    if (conflict.match_ids.length > 0) {
      setSelectedMatch(conflict.match_ids[0])
    }
  }

  return (
    <div style={panelStyle}>
      <div style={headerStyle}>
        <span>Conflicts</span>
        {errors.length > 0 && (
          <span style={{
            background: 'var(--danger)', color: 'white',
            borderRadius: '10px', padding: '0.1rem 0.5rem', fontSize: '0.7rem',
          }}>
            {errors.length}
          </span>
        )}
        {warnings.length > 0 && (
          <span style={{
            background: 'var(--warning)', color: 'white',
            borderRadius: '10px', padding: '0.1rem 0.5rem', fontSize: '0.7rem',
          }}>
            {warnings.length}
          </span>
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '0.3rem' }}>
        {conflicts.length === 0 ? (
          <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-light)', fontSize: '0.85rem' }}>
            No conflicts
          </div>
        ) : (
          conflicts.map(conflict => (
            <div
              key={conflict.id}
              onClick={() => handleConflictClick(conflict)}
              style={{
                padding: '0.4rem 0.6rem',
                marginBottom: '0.3rem',
                borderRadius: '4px',
                border: `1px solid ${conflict.severity === 'error' ? 'var(--danger)' : 'var(--warning)'}`,
                background: conflict.severity === 'error' ? '#fff5f5' : '#fffaf0',
                fontSize: '0.75rem',
                cursor: 'pointer',
              }}
            >
              <div style={{
                fontWeight: 600,
                color: conflict.severity === 'error' ? 'var(--danger)' : 'var(--warning)',
                fontSize: '0.7rem',
                textTransform: 'uppercase',
              }}>
                {conflict.type.replace(/_/g, ' ')}
              </div>
              <div style={{ marginTop: '2px' }}>{conflict.message}</div>
              {conflict.player && (
                <div style={{ marginTop: '2px', color: 'var(--text-light)', fontSize: '0.7rem' }}>
                  Player: {conflict.player}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

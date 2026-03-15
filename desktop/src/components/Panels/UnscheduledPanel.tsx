import { DraggableMatchCard } from '../ScheduleBoard/DraggableMatchCard'
import type { MatchCard as MatchCardType } from '../../types/api'

interface Props {
  matches: MatchCardType[]
}

export function UnscheduledPanel({ matches }: Props) {
  if (matches.length === 0) return null

  const panelStyle: React.CSSProperties = {
    height: '180px',
    flexShrink: 0,
    background: 'var(--card-bg)',
    borderTop: '2px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  }

  return (
    <div style={panelStyle}>
      <div style={{
        padding: '0.4rem 0.8rem',
        borderBottom: '1px solid var(--border)',
        fontWeight: 700,
        fontSize: '0.82rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span>Unscheduled Matches</span>
        <span style={{
          background: 'var(--warning)',
          color: 'white',
          borderRadius: '10px',
          padding: '0.1rem 0.5rem',
          fontSize: '0.7rem',
        }}>
          {matches.length}
        </span>
      </div>
      <div style={{
        flex: 1,
        overflow: 'auto',
        padding: '0.3rem',
        display: 'flex',
        flexWrap: 'wrap',
        gap: '4px',
        alignContent: 'flex-start',
      }}>
        {matches.map(match => (
          <div key={match.id} style={{ width: '160px', height: '70px' }}>
            <DraggableMatchCard match={match} />
          </div>
        ))}
      </div>
    </div>
  )
}

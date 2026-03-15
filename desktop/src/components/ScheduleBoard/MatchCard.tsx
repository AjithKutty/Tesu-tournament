import { useScheduleStore } from '../../store/scheduleStore'
import type { MatchCard as MatchCardType } from '../../types/api'

interface Props {
  match: MatchCardType
}

export function MatchCard({ match }: Props) {
  const { setSelectedMatch, swapMode, startSwap, cancelSwap } = useScheduleStore()

  const hasConflict = match.conflict_ids.length > 0
  const isCompleted = !!match.result
  const isPlaceholder = !match.has_real_players
  const isSwapSelected = swapMode.first === match.id

  const classes = [
    'match-card',
    hasConflict && 'has-conflict',
    match.pinned && 'is-pinned',
    isCompleted && 'is-completed',
    isPlaceholder && 'is-placeholder',
    isSwapSelected && 'swap-selected',
  ].filter(Boolean).join(' ')

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (swapMode.first && swapMode.first !== match.id) {
      // Second click in swap mode — handled by parent
      return
    }
    setSelectedMatch(match.id)
  }

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (swapMode.first) {
      cancelSwap()
    } else {
      startSwap(match.id)
    }
  }

  return (
    <div
      className={classes}
      style={{ '--card-category-color': match.category_color } as React.CSSProperties}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      title={`${match.id}\n${match.player1} vs ${match.player2}`}
    >
      <div className="match-card-header">
        <span className="match-card-division">{match.division_code}</span>
        <span className="match-card-icons">
          {match.pinned && <span className="match-card-icon" title="Pinned">&#128274;</span>}
          {hasConflict && <span className="match-card-icon" title="Conflict" style={{ color: 'var(--danger)' }}>&#9888;</span>}
          {isCompleted && <span className="match-card-icon" title="Completed" style={{ color: 'var(--success)' }}>&#10004;</span>}
        </span>
      </div>
      <div className="match-card-round">{match.round_name} M{match.match_num}</div>
      <div className="match-card-players">
        <div className="match-card-player">{match.player1 || '—'}</div>
        <div className="match-card-vs">vs</div>
        <div className="match-card-player">{match.player2 || '—'}</div>
      </div>
      {match.result && (
        <div className="match-card-result">{match.result}</div>
      )}
    </div>
  )
}

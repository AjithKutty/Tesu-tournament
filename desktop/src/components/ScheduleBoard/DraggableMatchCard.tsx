import { useDraggable } from '@dnd-kit/core'
import { MatchCard } from './MatchCard'
import type { MatchCard as MatchCardType } from '../../types/api'

interface Props {
  match: MatchCardType
}

export function DraggableMatchCard({ match }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: match.id,
    data: { match },
  })

  const style: React.CSSProperties = {
    transform: transform ? `translate(${transform.x}px, ${transform.y}px)` : undefined,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 100 : undefined,
    height: '100%',
  }

  return (
    <div ref={setNodeRef} style={style} {...listeners} {...attributes}>
      <MatchCard match={match} />
    </div>
  )
}

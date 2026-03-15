import { useDroppable } from '@dnd-kit/core'

interface Props {
  court: number
  timeDisplay: string
  timeMinute: number
  rowSpan?: number
  children?: React.ReactNode
}

export function DroppableCell({ court, timeDisplay, timeMinute, rowSpan, children }: Props) {
  const { setNodeRef, isOver } = useDroppable({
    id: `cell:${court}:${timeDisplay}`,
    data: { court, timeMinute, timeDisplay },
  })

  const className = ['grid-cell', isOver && 'drop-target'].filter(Boolean).join(' ')

  return (
    <div
      ref={setNodeRef}
      className={className}
      style={rowSpan && rowSpan > 1 ? { gridRow: `span ${rowSpan}` } : undefined}
    >
      {children}
    </div>
  )
}

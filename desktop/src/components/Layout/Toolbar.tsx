import { useState } from 'react'
import { useScheduleStore } from '../../store/scheduleStore'
import { useGenerateSchedule } from '../../hooks/useSchedule'
import * as api from '../../api/endpoints'
import type { TournamentConfig } from '../../types/api'

interface Props {
  config: TournamentConfig | null
  hasData: boolean
}

export function Toolbar({ config, hasData }: Props) {
  const { setImportDialogOpen, setPrintDialogOpen, toggleConflictPanel, toggleUnscheduledPanel } = useScheduleStore()
  const generateMutation = useGenerateSchedule()
  const [validating, setValidating] = useState(false)
  const handleValidate = async () => {
    setValidating(true)
    try {
      const result = await api.validateSchedule()
      const errors = result.conflicts.filter(c => c.severity === 'error').length
      const warnings = result.conflicts.filter(c => c.severity === 'warning').length
      if (errors === 0 && warnings === 0) {
        alert('No conflicts found!')
      } else {
        alert(`Validation: ${errors} error(s), ${warnings} warning(s)`)
      }
    } catch (err) {
      alert(`Validation failed: ${err instanceof Error ? err.message : err}`)
    } finally {
      setValidating(false)
    }
  }

  const handleExportWebsite = async () => {
    try {
      const result = await api.exportWebsite()
      alert(`Website exported to: ${result.path}`)
    } catch (err) {
      alert(`Export failed: ${err instanceof Error ? err.message : err}`)
    }
  }

  const handleExportSchedule = async () => {
    try {
      const result = await api.exportSchedule()
      alert(`Schedule exported to: ${result.path}`)
    } catch (err) {
      alert(`Export failed: ${err instanceof Error ? err.message : err}`)
    }
  }

  const toolbarStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    padding: '0.5rem 1rem',
    background: 'var(--primary)',
    color: 'white',
    flexShrink: 0,
  }

  const btnStyle: React.CSSProperties = {
    padding: '0.4rem 0.8rem',
    background: 'rgba(255,255,255,0.15)',
    color: 'white',
    borderRadius: '4px',
    fontSize: '0.8rem',
    fontWeight: 600,
    transition: 'background 0.15s',
  }

  return (
    <div style={toolbarStyle}>
      <span style={{ fontWeight: 700, fontSize: '1rem', marginRight: '1rem' }}>
        {config?.name || 'Tournament Manager'}
      </span>

      <button style={btnStyle} onClick={() => setImportDialogOpen(true)}>
        Import
      </button>

      <button
        style={{ ...btnStyle, opacity: hasData ? 1 : 0.5 }}
        disabled={!hasData || generateMutation.isPending}
        onClick={() => generateMutation.mutate(true)}
      >
        {generateMutation.isPending ? 'Generating...' : 'Generate'}
      </button>

      <button
        style={{ ...btnStyle, opacity: hasData ? 1 : 0.5 }}
        disabled={!hasData || validating}
        onClick={handleValidate}
      >
        {validating ? 'Validating...' : 'Validate'}
      </button>

      <button
        style={{ ...btnStyle, opacity: hasData ? 1 : 0.5 }}
        disabled={!hasData}
        onClick={() => setPrintDialogOpen(true)}
      >
        Print
      </button>

      <div style={{ position: 'relative' }}>
        <button
          style={{ ...btnStyle, opacity: hasData ? 1 : 0.5 }}
          disabled={!hasData}
          onClick={handleExportWebsite}
          onContextMenu={(e) => { e.preventDefault(); handleExportSchedule() }}
          title="Left-click: Export website | Right-click: Export schedule JSON"
        >
          Export
        </button>
      </div>

      <div style={{ flex: 1 }} />

      <button
        style={{ ...btnStyle, opacity: hasData ? 1 : 0.5 }}
        disabled={!hasData}
        onClick={toggleConflictPanel}
        title="Toggle conflict panel"
      >
        Conflicts
      </button>

      <button
        style={{ ...btnStyle, opacity: hasData ? 1 : 0.5 }}
        disabled={!hasData}
        onClick={toggleUnscheduledPanel}
        title="Toggle unscheduled panel"
      >
        Unscheduled
      </button>

      <button style={btnStyle} onClick={() => useScheduleStore.getState().setConfigWizardOpen(true)}>
        Config
      </button>
    </div>
  )
}

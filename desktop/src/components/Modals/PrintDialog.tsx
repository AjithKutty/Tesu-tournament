import { useState } from 'react'
import * as api from '../../api/endpoints'
import type { SessionInfo } from '../../types/api'

interface Props {
  sessions: SessionInfo[]
  onClose: () => void
}

function minutesToTimeStr(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`
}

export function PrintDialog({ sessions, onClose }: Props) {
  const [selectedTime, setSelectedTime] = useState<number | null>(null)
  const [printing, setPrinting] = useState(false)

  // Collect all unique time slots across sessions
  const allTimeSlots: { minute: number; display: string; session: string }[] = []
  for (const session of sessions) {
    for (let m = session.start_minute; m < session.end_minute; m += 30) {
      allTimeSlots.push({ minute: m, display: minutesToTimeStr(m), session: session.name })
    }
  }

  const handlePrint = async () => {
    setPrinting(true)
    try {
      const html = await api.getMatchCardsHtml(selectedTime ?? undefined)
      if (window.electronAPI) {
        await window.electronAPI.printHtml(html)
      } else {
        const w = window.open('', '_blank')
        if (w) {
          w.document.write(html)
          w.document.close()
          w.print()
        }
      }
      onClose()
    } catch (err) {
      alert(`Print failed: ${err instanceof Error ? err.message : err}`)
    } finally {
      setPrinting(false)
    }
  }

  const handleExportPdf = async () => {
    if (!window.electronAPI) {
      alert('PDF export requires the desktop app')
      return
    }
    setPrinting(true)
    try {
      const html = await api.getMatchCardsHtml(selectedTime ?? undefined)
      const savePath = await window.electronAPI.saveFile('match-cards.pdf', [
        { name: 'PDF', extensions: ['pdf'] },
      ])
      if (savePath) {
        await window.electronAPI.printPdf(html, savePath)
        alert(`PDF saved to: ${savePath}`)
      }
      onClose()
    } catch (err) {
      alert(`PDF export failed: ${err instanceof Error ? err.message : err}`)
    } finally {
      setPrinting(false)
    }
  }

  const overlayStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  }

  const dialogStyle: React.CSSProperties = {
    background: 'var(--card-bg)',
    borderRadius: '8px',
    padding: '1.5rem',
    minWidth: '400px',
    maxWidth: '500px',
    maxHeight: '70vh',
    overflow: 'auto',
    boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
  }

  const btnPrimary: React.CSSProperties = {
    padding: '0.5rem 1.2rem',
    background: 'var(--primary)',
    color: 'white',
    borderRadius: '4px',
    fontWeight: 600,
    fontSize: '0.85rem',
  }

  const btnSecondary: React.CSSProperties = {
    padding: '0.5rem 1.2rem',
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    fontSize: '0.85rem',
  }

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={dialogStyle} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 1rem' }}>Print Match Cards</h3>

        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>
            Time Slot (optional)
          </label>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-light)', margin: '0 0 0.5rem' }}>
            Select a time to print only matches starting at that time, or leave blank to print all.
          </p>

          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '4px',
            maxHeight: '200px',
            overflow: 'auto',
          }}>
            <button
              style={{
                ...btnSecondary,
                padding: '0.3rem 0.6rem',
                fontSize: '0.8rem',
                background: selectedTime === null ? 'var(--primary)' : 'var(--bg)',
                color: selectedTime === null ? 'white' : 'var(--text)',
              }}
              onClick={() => setSelectedTime(null)}
            >
              All
            </button>
            {allTimeSlots.map(slot => (
              <button
                key={`${slot.session}-${slot.minute}`}
                style={{
                  ...btnSecondary,
                  padding: '0.3rem 0.6rem',
                  fontSize: '0.8rem',
                  background: selectedTime === slot.minute ? 'var(--primary)' : 'var(--bg)',
                  color: selectedTime === slot.minute ? 'white' : 'var(--text)',
                }}
                onClick={() => setSelectedTime(slot.minute)}
              >
                {slot.display}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
          <button style={btnSecondary} onClick={onClose}>Cancel</button>
          <button style={btnSecondary} onClick={handleExportPdf} disabled={printing}>
            Save as PDF
          </button>
          <button style={btnPrimary} onClick={handlePrint} disabled={printing}>
            {printing ? 'Printing...' : 'Print'}
          </button>
        </div>
      </div>
    </div>
  )
}

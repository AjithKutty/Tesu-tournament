import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../../api/endpoints'
import type { ImportResponse, DivisionSummary } from '../../types/api'

interface Props {
  onClose: () => void
}

type ImportStep = 'source' | 'importing' | 'division-map' | 'done'

export function ImportDialog({ onClose }: Props) {
  const qc = useQueryClient()
  const [step, setStep] = useState<ImportStep>('source')
  const [source, setSource] = useState<'excel' | 'web'>('excel')
  const [webUrl, setWebUrl] = useState('')
  const [fullResults, setFullResults] = useState(false)
  const [importResult, setImportResult] = useState<ImportResponse | null>(null)
  const [divisionMap, setDivisionMap] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const importMutation = useMutation({
    mutationFn: async () => {
      if (source === 'excel') {
        const filePath = await window.electronAPI?.openFile([
          { name: 'Excel Files', extensions: ['xlsx', 'xls'] },
        ])
        if (!filePath) throw new Error('No file selected')
        // For Electron, we need to read the file and send it
        const response = await fetch(filePath)
        const blob = await response.blob()
        const file = new File([blob], filePath.split(/[\\/]/).pop() || 'draws.xlsx')
        return api.importExcel(file)
      } else {
        if (!webUrl.trim()) throw new Error('Please enter a URL')
        return api.importWeb(webUrl.trim(), fullResults)
      }
    },
    onSuccess: (data) => {
      setImportResult(data)
      // Pre-fill division map from suggestions
      const map: Record<string, string> = {}
      for (const div of data.divisions) {
        if (div.suggested_category) {
          map[div.code] = div.suggested_category
        }
      }
      setDivisionMap(map)
      setStep('division-map')
      qc.invalidateQueries({ queryKey: ['config'] })
    },
    onError: (err: Error) => {
      setError(err.message)
      setStep('source')
    },
  })

  const saveDivisionMap = useMutation({
    mutationFn: () => api.setDivisionMap(divisionMap),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['config'] })
      qc.invalidateQueries({ queryKey: ['schedule'] })
      setStep('done')
    },
  })

  const handleImport = () => {
    setError(null)
    setStep('importing')
    importMutation.mutate()
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
    minWidth: '500px',
    maxWidth: '700px',
    maxHeight: '80vh',
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
        {step === 'source' && (
          <>
            <h3 style={{ margin: '0 0 1rem' }}>Import Tournament Data</h3>

            {error && (
              <div style={{
                padding: '0.5rem 0.8rem',
                background: '#fff5f5',
                border: '1px solid var(--danger)',
                borderRadius: '4px',
                color: 'var(--danger)',
                fontSize: '0.85rem',
                marginBottom: '1rem',
              }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
              <button
                style={{
                  ...btnSecondary,
                  background: source === 'excel' ? 'var(--primary)' : 'var(--bg)',
                  color: source === 'excel' ? 'white' : 'var(--text)',
                }}
                onClick={() => setSource('excel')}
              >
                Excel File
              </button>
              <button
                style={{
                  ...btnSecondary,
                  background: source === 'web' ? 'var(--primary)' : 'var(--bg)',
                  color: source === 'web' ? 'white' : 'var(--text)',
                }}
                onClick={() => setSource('web')}
              >
                Web URL
              </button>
            </div>

            {source === 'web' && (
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.3rem' }}>
                  Tournament URL
                </label>
                <input
                  type="url"
                  value={webUrl}
                  onChange={(e) => setWebUrl(e.target.value)}
                  placeholder="https://badmintonfinland.tournamentsoftware.com/..."
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    border: '1px solid var(--border)',
                    borderRadius: '4px',
                    fontSize: '0.85rem',
                    boxSizing: 'border-box',
                  }}
                />
                <label style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  marginTop: '0.5rem',
                  fontSize: '0.82rem',
                }}>
                  <input
                    type="checkbox"
                    checked={fullResults}
                    onChange={(e) => setFullResults(e.target.checked)}
                  />
                  Include match results and scores
                </label>
              </div>
            )}

            {source === 'excel' && (
              <p style={{ fontSize: '0.85rem', color: 'var(--text-light)' }}>
                Select an Excel file (.xlsx) exported from tournamentsoftware.com containing draw data.
              </p>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button style={btnSecondary} onClick={onClose}>Cancel</button>
              <button style={btnPrimary} onClick={handleImport}>Import</button>
            </div>
          </>
        )}

        {step === 'importing' && (
          <div style={{ textAlign: 'center', padding: '2rem' }}>
            <div style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.5rem' }}>
              Importing...
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-light)' }}>
              {source === 'excel' ? 'Parsing Excel file...' : 'Scraping tournament data...'}
            </div>
          </div>
        )}

        {step === 'division-map' && importResult && (
          <>
            <h3 style={{ margin: '0 0 0.5rem' }}>Import Successful</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-light)', margin: '0 0 1rem' }}>
              {importResult.division_count} divisions, {importResult.match_count} matches, {importResult.player_count} players
            </p>

            <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.9rem' }}>
              Map Divisions to Categories
            </h4>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-light)', margin: '0 0 0.8rem' }}>
              Assign each division to a category for scheduling rules (duration, rest periods, court restrictions).
            </p>

            <div style={{ maxHeight: '300px', overflow: 'auto', marginBottom: '1rem' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    <th style={{ textAlign: 'left', padding: '0.3rem 0.5rem' }}>Division</th>
                    <th style={{ textAlign: 'left', padding: '0.3rem 0.5rem' }}>Category</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.divisions.map((div: DivisionSummary) => (
                    <tr key={div.code} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '0.3rem 0.5rem' }}>
                        {div.code}
                        <span style={{ color: 'var(--text-light)', marginLeft: '0.3rem' }}>
                          {div.name}
                        </span>
                      </td>
                      <td style={{ padding: '0.3rem 0.5rem' }}>
                        <input
                          type="text"
                          value={divisionMap[div.code] || ''}
                          onChange={(e) =>
                            setDivisionMap((m) => ({ ...m, [div.code]: e.target.value }))
                          }
                          placeholder={div.suggested_category || 'category_id'}
                          style={{
                            width: '120px',
                            padding: '0.2rem 0.4rem',
                            border: '1px solid var(--border)',
                            borderRadius: '3px',
                            fontSize: '0.82rem',
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button style={btnSecondary} onClick={onClose}>Skip</button>
              <button
                style={btnPrimary}
                onClick={() => saveDivisionMap.mutate()}
                disabled={saveDivisionMap.isPending}
              >
                {saveDivisionMap.isPending ? 'Saving...' : 'Save & Continue'}
              </button>
            </div>
          </>
        )}

        {step === 'done' && importResult && (
          <div style={{ textAlign: 'center', padding: '1.5rem' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>&#10004;</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.5rem' }}>
              Import Complete
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-light)', marginBottom: '1rem' }}>
              {importResult.division_count} divisions with {importResult.match_count} matches ready.
              Use "Generate" to create the schedule.
            </p>
            <button style={btnPrimary} onClick={onClose}>Close</button>
          </div>
        )}
      </div>
    </div>
  )
}

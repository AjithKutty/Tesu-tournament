import { useState } from 'react'
import { useUpdateResult } from '../../hooks/useSchedule'
import { useScheduleStore } from '../../store/scheduleStore'
import * as api from '../../api/endpoints'
import type { MatchCard } from '../../types/api'

interface Props {
  matchId: string
  matches: MatchCard[]
  onClose: () => void
}

export function MatchDetailModal({ matchId, matches, onClose }: Props) {
  const match = matches.find((m) => m.id === matchId)
  const updateResult = useUpdateResult()
  const { startSwap } = useScheduleStore()
  const [score, setScore] = useState(match?.result || '')
  const [saving, setSaving] = useState(false)

  if (!match) {
    return null
  }

  const handleSaveResult = async () => {
    if (!score.trim()) return
    setSaving(true)
    try {
      await updateResult.mutateAsync({ matchId: match.id, score: score.trim() })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const handlePin = async () => {
    await api.pinMatch(match.id, !match.pinned)
    onClose()
  }

  const handleUnschedule = async () => {
    await api.unscheduleMatch(match.id)
    onClose()
  }

  const handleSwap = () => {
    startSwap(match.id)
    onClose()
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
    boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
  }

  const labelStyle: React.CSSProperties = {
    fontSize: '0.75rem',
    color: 'var(--text-light)',
    textTransform: 'uppercase',
    fontWeight: 600,
    marginBottom: '0.2rem',
  }

  const valueStyle: React.CSSProperties = {
    fontSize: '0.9rem',
    marginBottom: '0.8rem',
  }

  const btnStyle: React.CSSProperties = {
    padding: '0.4rem 0.8rem',
    borderRadius: '4px',
    fontSize: '0.82rem',
    fontWeight: 600,
  }

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={dialogStyle} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: '1rem',
        }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: match.category_color, fontWeight: 700 }}>
              {match.category_label}
            </div>
            <h3 style={{ margin: '0.2rem 0 0' }}>
              {match.division_code} &mdash; {match.round_name} M{match.match_num}
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: '1.2rem', cursor: 'pointer', padding: '0.2rem' }}
          >
            &#10005;
          </button>
        </div>

        {/* Players */}
        <div style={labelStyle}>Players</div>
        <div style={valueStyle}>
          <div style={{ fontWeight: 600 }}>{match.player1 || '—'}</div>
          <div style={{ color: 'var(--text-light)', fontSize: '0.8rem', margin: '0.1rem 0' }}>vs</div>
          <div style={{ fontWeight: 600 }}>{match.player2 || '—'}</div>
        </div>

        {/* Schedule Info */}
        <div style={{ display: 'flex', gap: '2rem', marginBottom: '0.8rem' }}>
          <div>
            <div style={labelStyle}>Court</div>
            <div style={valueStyle}>{match.court != null ? `Court ${match.court}` : 'Unscheduled'}</div>
          </div>
          <div>
            <div style={labelStyle}>Time</div>
            <div style={valueStyle}>{match.time_display || '—'}</div>
          </div>
          <div>
            <div style={labelStyle}>Day</div>
            <div style={valueStyle}>{match.day || '—'}</div>
          </div>
          <div>
            <div style={labelStyle}>Duration</div>
            <div style={valueStyle}>{match.duration_min} min</div>
          </div>
        </div>

        {/* Status */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          {match.pinned && (
            <span style={{
              padding: '0.15rem 0.5rem', background: '#e0f0ff', borderRadius: '10px',
              fontSize: '0.75rem', fontWeight: 600, color: '#0066cc',
            }}>
              Pinned
            </span>
          )}
          {match.conflict_ids.length > 0 && (
            <span style={{
              padding: '0.15rem 0.5rem', background: '#fff5f5', borderRadius: '10px',
              fontSize: '0.75rem', fontWeight: 600, color: 'var(--danger)',
            }}>
              {match.conflict_ids.length} conflict(s)
            </span>
          )}
          {!match.has_real_players && (
            <span style={{
              padding: '0.15rem 0.5rem', background: '#f0f0f0', borderRadius: '10px',
              fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-light)',
            }}>
              Placeholder
            </span>
          )}
        </div>

        {/* Result Entry */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: '0.8rem', marginBottom: '1rem' }}>
          <div style={labelStyle}>Result / Score</div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <input
              type="text"
              value={score}
              onChange={(e) => setScore(e.target.value)}
              placeholder="e.g. 21-15 21-18"
              style={{
                flex: 1,
                padding: '0.5rem',
                border: '1px solid var(--border)',
                borderRadius: '4px',
                fontSize: '0.85rem',
              }}
            />
            <button
              style={{ ...btnStyle, background: 'var(--success)', color: 'white' }}
              onClick={handleSaveResult}
              disabled={saving || !score.trim()}
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>

        {/* Actions */}
        <div style={{
          display: 'flex',
          gap: '0.5rem',
          borderTop: '1px solid var(--border)',
          paddingTop: '0.8rem',
        }}>
          <button
            style={{ ...btnStyle, background: 'var(--bg)', border: '1px solid var(--border)' }}
            onClick={handlePin}
          >
            {match.pinned ? 'Unpin' : 'Pin'}
          </button>
          <button
            style={{ ...btnStyle, background: 'var(--bg)', border: '1px solid var(--border)' }}
            onClick={handleSwap}
          >
            Swap
          </button>
          {match.court != null && (
            <button
              style={{ ...btnStyle, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--danger)' }}
              onClick={handleUnschedule}
            >
              Unschedule
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

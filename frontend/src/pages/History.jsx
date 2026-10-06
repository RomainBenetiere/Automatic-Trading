import { useState, useCallback } from 'react'
import { Clock, TrendingUp, Filter } from 'lucide-react'
import { usePolling } from '../hooks/usePolling'
import { recommendations, scores } from '../api/client'

function SignalBadge({ signal }) {
  if (!signal) return null
  const label = signal.replace('_', ' ')
  return <span className={`badge badge-${signal}`}>{label}</span>
}

export default function History() {
  const [symbolFilter, setSymbolFilter] = useState('')

  const { data: recoHistory, loading } = usePolling(
    useCallback(() => recommendations.getHistory(symbolFilter ? { symbol: symbolFilter } : {}), [symbolFilter]),
    60000
  )

  const { data: latestScores } = usePolling(
    useCallback(() => scores.getLatest(), []),
    120000
  )

  // Get unique symbols from scores for filter
  const symbols = latestScores ? [...new Set(latestScores.map(s => s.symbol))].sort() : []

  return (
    <div>
      <div className="page-header">
        <h1>History</h1>
        <p>Historical scores and recommendation archive</p>
      </div>

      {/* Filter */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 'var(--space-lg)' }}>
        <Filter size={16} style={{ color: 'var(--text-muted)' }} />
        <select
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          style={{
            background: 'var(--bg-input)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '8px 12px',
            fontFamily: 'inherit',
            fontSize: '0.875rem',
            cursor: 'pointer',
          }}
        >
          <option value="">All symbols</option>
          {symbols.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {/* Recommendation History */}
      <div className="section">
        <div className="section-title">
          <Clock size={20} style={{ color: 'var(--accent-secondary)' }} />
          Recommendation Archive
        </div>

        {recoHistory && recoHistory.length > 0 ? (
          recoHistory.map((r) => (
            <div key={r.id} className="reco-card animate-in">
              <div className="reco-card-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span className="reco-card-symbol">{r.symbol}</span>
                  <SignalBadge signal={r.action} />
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    {r.account_type} • {(r.confidence * 100).toFixed(0)}% confidence
                  </span>
                </div>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{r.date}</span>
              </div>
              {r.narrative && (
                <div className="reco-card-narrative">{r.narrative}</div>
              )}
            </div>
          ))
        ) : (
          <div className="card">
            <div className="empty-state">
              {loading ? (
                <div className="skeleton" style={{ height: 20, width: 260, margin: '0 auto' }} />
              ) : (
                'No recommendation history yet'
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

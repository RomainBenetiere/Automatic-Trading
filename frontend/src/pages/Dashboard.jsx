import { useState, useCallback } from 'react'
import {
  BarChart3, TrendingUp, TrendingDown, Wallet, PieChart,
  RefreshCw, ArrowUpRight, ArrowDownRight, Minus
} from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, AreaChart, Area
} from 'recharts'
import { usePolling } from '../hooks/usePolling'
import { scores, recommendations, portfolio, jobs } from '../api/client'

function ScoreGauge({ value, size = 44 }) {
  if (value == null) return <span className="text-muted">—</span>
  const level = value >= 62 ? 'high' : value >= 45 ? 'medium' : 'low'
  return (
    <div className={`score-gauge score-${level}`} style={{ width: size, height: size }}>
      {Math.round(value)}
    </div>
  )
}

function SignalBadge({ signal }) {
  if (!signal) return null
  const label = signal.replace('_', ' ')
  return <span className={`badge badge-${signal}`}>{label}</span>
}

function PnlValue({ value }) {
  if (value == null) return <span className="cell-number">—</span>
  const cls = value > 0 ? 'cell-positive' : value < 0 ? 'cell-negative' : ''
  return (
    <span className={`cell-number ${cls}`}>
      {value > 0 ? '+' : ''}{value.toFixed(2)} €
    </span>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'rgba(17, 24, 39, 0.95)',
      border: '1px solid rgba(6, 182, 212, 0.3)',
      borderRadius: '8px',
      padding: '10px 14px',
      fontSize: '0.8rem',
    }}>
      <p style={{ color: '#94a3b8', marginBottom: 4 }}>{label}</p>
      {payload.map((entry, i) => (
        <p key={i} style={{ color: entry.color, fontWeight: 600 }}>
          {entry.name}: {typeof entry.value === 'number' ? entry.value.toFixed(1) : entry.value}
        </p>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [syncing, setSyncing] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [actionError, setActionError] = useState(null)

  const { data: latestScores, loading: scoresLoading, refetch: refetchScores } = usePolling(
    useCallback(() => scores.getLatest(), []),
    60000
  )
  const { data: latestRecos, loading: recosLoading } = usePolling(
    useCallback(() => recommendations.getLatest(), []),
    60000
  )
  const { data: positions, loading: posLoading } = usePolling(
    useCallback(() => portfolio.getPositions(), []),
    60000
  )

  const handleSync = async () => {
    setSyncing(true)
    setActionError(null)
    try {
      await portfolio.sync()
      refetchScores()
    } catch (e) {
      console.error(e)
      setActionError(e.message)
    }
    setSyncing(false)
  }

  const handleTrigger = async () => {
    setTriggering(true)
    setActionError(null)
    try {
      await jobs.triggerStocks()
      refetchScores()
    } catch (e) {
      console.error(e)
      setActionError(e.message)
    }
    setTriggering(false)
  }

  // Aggregate portfolio by account type
  const accountSummary = {}
  if (positions && Array.isArray(positions)) {
    for (const p of positions) {
      const key = p.account_type
      if (!accountSummary[key]) accountSummary[key] = { count: 0, value: 0 }
      accountSummary[key].count++
      accountSummary[key].value += p.market_value || 0
    }
  }

  const accountLabels = {
    brokerage: 'Brokerage',
    pea: 'PEA',
    assurance_vie: 'Assurance Vie',
    per: 'PER',
    crypto: 'Crypto',
  }

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1>Portfolio Dashboard</h1>
          <p>Advisory view — scores, recommendations, and holdings overview</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary" onClick={handleSync} disabled={syncing}>
            <RefreshCw size={16} className={syncing ? 'spinning' : ''} />
            {syncing ? 'Syncing…' : 'Sync'}
          </button>
          <button className="btn btn-primary" onClick={handleTrigger} disabled={triggering}>
            <BarChart3 size={16} />
            {triggering ? 'Analysing…' : 'Run Analysis'}
          </button>
        </div>
      </div>

      {actionError && (
        <div className="card" style={{ borderColor: 'var(--color-sell)', color: 'var(--color-sell)', marginBottom: 16 }}>
          {actionError}
        </div>
      )}

      {/* Account Summary Cards */}
      <div className="summary-grid">
        {Object.entries(accountSummary).map(([key, val], i) => (
          <div key={key} className={`card animate-in animate-in-delay-${i + 1}`}>
            <div className="card-header">
              <span className="card-title">{accountLabels[key] || key}</span>
              <Wallet size={18} style={{ color: 'var(--accent-primary)', opacity: 0.7 }} />
            </div>
            <div className="card-value">
              {val.value.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
              {val.count} position{val.count > 1 ? 's' : ''}
            </div>
          </div>
        ))}

        {Object.keys(accountSummary).length === 0 && !posLoading && (
          <div className="card animate-in">
            <div className="card-header">
              <span className="card-title">Total Portfolio</span>
              <PieChart size={18} style={{ color: 'var(--accent-primary)', opacity: 0.7 }} />
            </div>
            <div className="card-value" style={{ color: 'var(--text-muted)' }}>—</div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
              Sync your portfolio to see data
            </div>
          </div>
        )}
      </div>

      {/* Scores Table */}
      <div className="section">
        <div className="section-title">
          <BarChart3 size={20} style={{ color: 'var(--accent-primary)' }} />
          Latest Scores
        </div>
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Technical</th>
                <th>Fundamental</th>
                <th>Dividend</th>
                <th>Composite</th>
                <th>Signal</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {latestScores && latestScores.length > 0 ? (
                latestScores.map((s) => (
                  <tr key={s.symbol}>
                    <td style={{ fontWeight: 600 }}>{s.symbol}</td>
                    <td><ScoreGauge value={s.technical_score} size={36} /></td>
                    <td><ScoreGauge value={s.fundamental_score} size={36} /></td>
                    <td><ScoreGauge value={s.dividend_score} size={36} /></td>
                    <td><ScoreGauge value={s.composite_score} /></td>
                    <td><SignalBadge signal={s.signal} /></td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{s.date}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="empty-state">
                    {scoresLoading ? (
                      <div className="skeleton" style={{ height: 20, width: 200, margin: '0 auto' }} />
                    ) : (
                      'No scores yet — run an analysis to generate scores'
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recommendations */}
      <div className="section">
        <div className="section-title">
          <TrendingUp size={20} style={{ color: 'var(--color-buy)' }} />
          Latest Recommendations
        </div>
        {latestRecos && latestRecos.length > 0 ? (
          latestRecos.map((r) => (
            <div key={r.id} className="reco-card animate-in">
              <div className="reco-card-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span className="reco-card-symbol">{r.symbol}</span>
                  <SignalBadge signal={r.action} />
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    {r.account_type} • confidence: {(r.confidence * 100).toFixed(0)}%
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
              {recosLoading ? (
                <div className="skeleton" style={{ height: 20, width: 260, margin: '0 auto' }} />
              ) : (
                'No recommendations yet — run the weekly analysis'
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

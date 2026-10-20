import { useState, useCallback } from 'react'
import {
  Bitcoin, Shield, ShieldAlert, ShieldCheck, ShieldX,
  TrendingUp, TrendingDown, Activity, AlertTriangle,
  Play, BarChart3, Clock, DollarSign, Wallet, Trash2
} from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts'
import { usePolling } from '../hooks/usePolling'
import { crypto, jobs } from '../api/client'

const CHART_COLORS = ['#10b981', '#f43f5e', '#f59e0b', '#06b6d4', '#8b5cf6']

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
          {entry.name}: {entry.value}
        </p>
      ))}
    </div>
  )
}

export default function CryptoExecution() {
  const [triggering, setTriggering] = useState(false)
  const [resettingPaper, setResettingPaper] = useState(false)

  const { data: positions, loading: posLoading } = usePolling(
    useCallback(() => crypto.getPositions(), []),
    15000
  )
  const { data: paperPortfolio, loading: paperLoading, refetch: refetchPaper } = usePolling(
    useCallback(() => crypto.getPaperPortfolio(), []),
    15000
  )
  const { data: orders, loading: ordersLoading, refetch: refetchOrders } = usePolling(
    useCallback(() => crypto.getOrders({ limit: '30' }), []),
    30000
  )
  const { data: guardrails, loading: guardLoading, refetch: refetchGuardrails } = usePolling(
    useCallback(() => crypto.getGuardrailStatus(), []),
    30000
  )
  const { data: performance, loading: perfLoading, refetch: refetchPerformance } = usePolling(
    useCallback(() => crypto.getPerformance(30), []),
    60000
  )
  const { data: cbEvents } = usePolling(
    useCallback(() => crypto.getCircuitBreakerEvents(), []),
    60000
  )

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      await jobs.triggerCrypto()
      refetchOrders()
      refetchPaper()
      refetchGuardrails()
      refetchPerformance()
    } catch (e) { console.error(e) }
    setTriggering(false)
  }

  const handleResetPaper = async () => {
    if (!window.confirm('Voulez-vous vraiment purger tous les Paper Trades et réinitialiser le portefeuille simulé à son budget initial ?')) {
      return
    }
    setResettingPaper(true)
    try {
      await crypto.resetPaperPortfolio()
      refetchPaper()
      refetchOrders()
      refetchGuardrails()
      refetchPerformance()
    } catch (e) {
      console.error(e)
    }
    setResettingPaper(false)
  }

  const mode = guardrails?.mode || 'paper'
  const isCircuitBreakerActive = guardrails?.circuit_breaker?.active

  // Win rate pie chart data
  const winRateData = performance ? [
    { name: 'Wins', value: performance.winning_trades || 0 },
    { name: 'Losses', value: performance.losing_trades || 0 },
  ] : []

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1>Crypto Execution</h1>
          <p>Automated trading — positions, orders, and safety guardrails</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className={`badge badge-${mode}`}>
            {mode === 'live' ? '● LIVE' : '◉ PAPER'}
          </span>
          <button
            className="btn btn-secondary"
            onClick={handleResetPaper}
            disabled={resettingPaper}
            title="Supprimer tous les ordres Paper et réinitialiser le budget virtuel"
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Trash2 size={15} />
            {resettingPaper ? 'Purge…' : 'Purger Paper Trades'}
          </button>
          <button className="btn btn-primary" onClick={handleTrigger} disabled={triggering}>
            <Play size={16} />
            {triggering ? 'Running…' : 'Run Crypto Job'}
          </button>
        </div>
      </div>

      {/* Circuit Breaker Alert */}
      {isCircuitBreakerActive && (
        <div className="alert-banner alert-danger">
          <ShieldX size={20} />
          <div>
            <strong>Circuit Breaker Active</strong> — New buys are paused (Sells &amp; Stop-Loss remain active).
            {guardrails.circuit_breaker.events?.[0]?.reason &&
              ` Reason: ${guardrails.circuit_breaker.events[0].reason}`
            }
          </div>
        </div>
      )}

      {/* Performance Summary */}
      <div className="summary-grid">
        <div className="card animate-in animate-in-delay-1">
          <div className="card-header">
            <span className="card-title">Total P&L</span>
            <DollarSign size={18} style={{ color: 'var(--accent-primary)', opacity: 0.7 }} />
          </div>
          <div className="card-value" style={{
            color: (performance?.total_pnl_eur || 0) >= 0 ? 'var(--color-buy)' : 'var(--color-sell)'
          }}>
            {performance ? `${performance.total_pnl_eur >= 0 ? '+' : ''}${(performance.total_pnl_eur ?? 0).toFixed(2)} €` : '—'}
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
            Last 30 days
          </div>
        </div>

        <div className="card animate-in animate-in-delay-2">
          <div className="card-header">
            <span className="card-title">Win Rate</span>
            <TrendingUp size={18} style={{ color: 'var(--color-buy)', opacity: 0.7 }} />
          </div>
          <div className="card-value">
            {performance ? `${((performance.win_rate ?? 0) * 100).toFixed(0)}%` : '—'}
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
            {performance?.total_trades || 0} trades
          </div>
        </div>

        <div className="card animate-in animate-in-delay-3">
          <div className="card-header">
            <span className="card-title">Max Drawdown</span>
            <TrendingDown size={18} style={{ color: 'var(--color-sell)', opacity: 0.7 }} />
          </div>
          <div className="card-value" style={{ color: 'var(--color-sell)' }}>
            {performance ? `−${(performance.max_drawdown_pct ?? 0).toFixed(1)}%` : '—'}
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
            {performance ? `€${(performance.max_drawdown_eur ?? 0).toFixed(2)}` : ''}
          </div>
        </div>

        <div className="card animate-in animate-in-delay-4">
          <div className="card-header">
            <span className="card-title">Avg P&L/Trade</span>
            <BarChart3 size={18} style={{ color: 'var(--accent-secondary)', opacity: 0.7 }} />
          </div>
          <div className="card-value" style={{
            color: (performance?.avg_pnl_per_trade || 0) >= 0 ? 'var(--color-buy)' : 'var(--color-sell)'
          }}>
            {performance ? `${performance.avg_pnl_per_trade >= 0 ? '+' : ''}${(performance.avg_pnl_per_trade ?? 0).toFixed(2)} €` : '—'}
          </div>
        </div>
      </div>

      {/* Simulated Paper Portfolio State */}
      <div className="section">
        <div className="section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Wallet size={20} style={{ color: 'var(--accent-primary)' }} />
            <span>Portefeuille Paper Trading (Simulation)</span>
          </div>
          {paperPortfolio && (
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 400 }}>
              Budget initial : €{paperPortfolio.initial_budget_eur?.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} • Frais Bitvavo : {paperPortfolio.fee_pct ?? 0.25}%/ordre (Total frais : €{(paperPortfolio.total_fees_eur ?? 0).toFixed(2)})
            </span>
          )}
        </div>

        {paperPortfolio && (
          <div className="summary-grid" style={{ marginBottom: 16 }}>
            <div className="card">
              <div className="card-header">
                <span className="card-title">Valeur Portefeuille Paper</span>
                <Wallet size={18} style={{ color: 'var(--accent-primary)', opacity: 0.7 }} />
              </div>
              <div className="card-value">
                €{(paperPortfolio.portfolio_value_eur ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{
                color: (paperPortfolio.total_return_eur || 0) >= 0 ? 'var(--color-buy)' : 'var(--color-sell)',
                fontSize: '0.8rem',
                marginTop: 4,
                fontWeight: 600,
              }}>
                {(paperPortfolio.total_return_eur || 0) >= 0 ? '+' : ''}
                {(paperPortfolio.total_return_eur ?? 0).toFixed(2)} € ({(paperPortfolio.total_return_pct || 0) >= 0 ? '+' : ''}{(paperPortfolio.total_return_pct ?? 0).toFixed(2)}%)
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span className="card-title">Cash EUR Disponible</span>
                <DollarSign size={18} style={{ color: 'var(--color-buy)', opacity: 0.7 }} />
              </div>
              <div className="card-value">
                €{(paperPortfolio.cash_eur ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
                Net des frais Bitvavo ({paperPortfolio.fee_pct ?? 0.25}%)
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span className="card-title">Positions Crypto Ouvertes</span>
                <Bitcoin size={18} style={{ color: 'var(--accent-secondary)', opacity: 0.7 }} />
              </div>
              <div className="card-value">
                €{(paperPortfolio.positions_value_eur ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
                {paperPortfolio.open_positions_count || 0} actif(s) ({paperPortfolio.open_lots_count || 0} lot(s)) • Coût : €{(paperPortfolio.invested_cost_eur ?? 0).toFixed(2)}
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span className="card-title">P&L Latent / Réalisé (Net)</span>
                <Activity size={18} style={{ color: 'var(--accent-primary)', opacity: 0.7 }} />
              </div>
              <div className="card-value" style={{
                color: (paperPortfolio.unrealised_pnl_eur || 0) >= 0 ? 'var(--color-buy)' : 'var(--color-sell)'
              }}>
                {(paperPortfolio.unrealised_pnl_eur || 0) >= 0 ? '+' : ''}{(paperPortfolio.unrealised_pnl_eur ?? 0).toFixed(2)} €
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
                Latent : {(paperPortfolio.unrealised_pnl_pct || 0) >= 0 ? '+' : ''}{(paperPortfolio.unrealised_pnl_pct ?? 0).toFixed(2)}% • Réalisé : {(paperPortfolio.realised_pnl_eur || 0) >= 0 ? '+' : ''}{(paperPortfolio.realised_pnl_eur ?? 0).toFixed(2)} €
              </div>
            </div>
          </div>
        )}

        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Actif</th>
                <th>Lots</th>
                <th>Quantité</th>
                <th>Prix Entrée Moy.</th>
                <th>Cours Actuel</th>
                <th>Coût Investi</th>
                <th>Valeur (EUR)</th>
                <th>Frais (A/V)</th>
                <th>P&L Latent (Net)</th>
                <th>Stop / Trailing</th>
                <th>Take Profit</th>
                <th>24h Change</th>
              </tr>
            </thead>
            <tbody>
              {paperPortfolio ? (
                <>
                  <tr style={{ background: 'rgba(6, 182, 212, 0.04)' }}>
                    <td style={{ fontWeight: 600 }}>EUR (Cash virtuel)</td>
                    <td className="cell-number">—</td>
                    <td className="cell-number">{paperPortfolio.cash_eur?.toFixed(2)}</td>
                    <td className="cell-number">—</td>
                    <td className="cell-number">—</td>
                    <td className="cell-number">—</td>
                    <td className="cell-number" style={{ fontWeight: 600 }}>
                      €{paperPortfolio.cash_eur?.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className="cell-number">—</td>
                    <td className="cell-number">—</td>
                    <td className="cell-number">—</td>
                    <td className="cell-number">—</td>
                    <td className="cell-number">—</td>
                  </tr>
                  {paperPortfolio.positions && paperPortfolio.positions.length > 0 ? (
                    paperPortfolio.positions.map((pos) => {
                      const effectiveStop = Math.max(pos.stop_loss_price || 0, pos.trailing_stop_price || 0)
                      const fmtPx = (px) => {
                        if (px == null || px <= 0) return '—'
                        const digits = px < 0.1 ? 6 : px < 10 ? 4 : 2
                        return `€${px.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: digits })}`
                      }
                      return (
                        <tr key={pos.symbol}>
                          <td style={{ fontWeight: 600 }}>{pos.symbol}</td>
                          <td className="cell-number">{pos.lots_count}</td>
                          <td className="cell-number">{pos.quantity?.toFixed(6)}</td>
                          <td className="cell-number">{fmtPx(pos.avg_buy_price)}</td>
                          <td className="cell-number">{fmtPx(pos.current_price)}</td>
                          <td className="cell-number">
                            €{pos.cost_eur?.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td className="cell-number" style={{ fontWeight: 600 }}>
                            €{pos.market_value_eur?.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td className="cell-number" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                            €{(pos.fees_eur ?? 0).toFixed(2)}
                          </td>
                          <td className={`cell-number ${
                            (pos.unrealised_pnl_eur || 0) > 0 ? 'cell-positive' : (pos.unrealised_pnl_eur || 0) < 0 ? 'cell-negative' : ''
                          }`}>
                            {pos.unrealised_pnl_eur >= 0 ? '+' : ''}{pos.unrealised_pnl_eur?.toFixed(2)} € ({pos.unrealised_pnl_pct >= 0 ? '+' : ''}{pos.unrealised_pnl_pct?.toFixed(2)}%)
                          </td>
                          <td className="cell-number" style={{ fontSize: '0.8rem', color: 'var(--color-sell)' }}>
                            {fmtPx(effectiveStop)}
                          </td>
                          <td className="cell-number" style={{ fontSize: '0.8rem', color: 'var(--color-buy)' }}>
                            {fmtPx(pos.take_profit_price)}
                          </td>
                          <td className={`cell-number ${
                            pos.change_24h_pct > 0 ? 'cell-positive' : pos.change_24h_pct < 0 ? 'cell-negative' : ''
                          }`}>
                            {pos.change_24h_pct != null ? `${pos.change_24h_pct > 0 ? '+' : ''}${pos.change_24h_pct}%` : '—'}
                          </td>
                        </tr>
                      )
                    })
                  ) : (
                    <tr>
                      <td colSpan={12} className="empty-state" style={{ padding: '16px' }}>
                        Aucune position crypto ouverte en simulation Paper (100% Cash EUR)
                      </td>
                    </tr>
                  )}
                </>
              ) : (
                <tr>
                  <td colSpan={12} className="empty-state">
                    {paperLoading ? 'Chargement du portefeuille Paper…' : 'Portefeuille Paper indisponible'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Live Bitvavo Positions */}
      <div className="section">
        <div className="section-title">
          <Bitcoin size={20} style={{ color: 'var(--accent-primary)' }} />
          Live Positions (Compte Bitvavo Réel)
        </div>
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Balance</th>
                <th>Price</th>
                <th>Value (EUR)</th>
                <th>24h Change</th>
              </tr>
            </thead>
            <tbody>
              {positions && positions.length > 0 ? (
                positions.map((p) => (
                  <tr key={p.symbol}>
                    <td style={{ fontWeight: 600 }}>{p.symbol}</td>
                    <td className="cell-number">{p.total?.toFixed(p.symbol === 'EUR' ? 2 : 6)}</td>
                    <td className="cell-number">
                      {p.current_price ? `€${p.current_price.toLocaleString('fr-FR', { maximumFractionDigits: 2 })}` : '—'}
                    </td>
                    <td className="cell-number" style={{ fontWeight: 600 }}>
                      {p.market_value_eur != null
                        ? `€${p.market_value_eur.toLocaleString('fr-FR', { maximumFractionDigits: 2 })}`
                        : '—'
                      }
                    </td>
                    <td className={`cell-number ${
                      p.change_24h_pct > 0 ? 'cell-positive' : p.change_24h_pct < 0 ? 'cell-negative' : ''
                    }`}>
                      {p.change_24h_pct != null ? `${p.change_24h_pct > 0 ? '+' : ''}${p.change_24h_pct}%` : '—'}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="empty-state">
                    {posLoading ? 'Loading…' : 'No crypto positions found'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Guardrails Status */}
      <div className="section">
        <div className="section-title">
          <Shield size={20} style={{ color: 'var(--accent-primary)' }} />
          Safety Guardrails
        </div>
        <div className="guardrail-grid">
          {guardrails && (
            <>
              <div className={`guardrail-item ${isCircuitBreakerActive ? 'status-danger' : 'status-ok'}`}>
                {isCircuitBreakerActive ? <ShieldX size={20} color="var(--color-danger)" /> : <ShieldCheck size={20} color="var(--color-success)" />}
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Circuit Breaker</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    {isCircuitBreakerActive ? 'TRIGGERED' : 'OK'} • {guardrails.recent_stats?.consecutive_losses || 0}/{guardrails.recent_stats?.max_consecutive_losses} losses
                  </div>
                </div>
              </div>

              <div className="guardrail-item status-ok">
                <ShieldCheck size={20} color="var(--color-success)" />
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Per-Trade Cap</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Max {guardrails.per_trade_cap?.max_pct}% per order</div>
                </div>
              </div>

              <div className="guardrail-item status-ok">
                <ShieldCheck size={20} color="var(--color-success)" />
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Stop Loss</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>−{guardrails.stop_loss?.pct}% from entry</div>
                </div>
              </div>

              <div className="guardrail-item status-ok">
                <ShieldCheck size={20} color="var(--color-success)" />
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Take Profit</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>+{guardrails.take_profit?.pct}% target</div>
                </div>
              </div>

              <div className="guardrail-item status-ok">
                <ShieldCheck size={20} color="var(--color-success)" />
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Trailing Stop</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{guardrails.trailing_stop?.pct}% trail</div>
                </div>
              </div>

              <div className="guardrail-item status-ok">
                <ShieldCheck size={20} color="var(--color-success)" />
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Global Budget</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Max €{guardrails.global_budget?.max_eur}</div>
                </div>
              </div>

              <div className="guardrail-item status-ok">
                <ShieldCheck size={20} color="var(--color-success)" />
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Execution Fee</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{guardrails.execution_fee?.pct ?? 0.25}% Bitvavo / order</div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Order Log */}
      <div className="section">
        <div className="section-title">
          <Clock size={20} style={{ color: 'var(--accent-secondary)' }} />
          Order Log
        </div>
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Value</th>
                <th>Frais (0.25%)</th>
                <th>Status</th>
                <th>P&L (Net)</th>
                <th>Raison / Clôture</th>
                <th>Mode</th>
              </tr>
            </thead>
            <tbody>
              {orders && orders.length > 0 ? (
                orders.map((o) => {
                  const fmtPrice = (px) => {
                    if (px == null) return '—'
                    if (px < 0.1) return `€${px.toFixed(6)}`
                    if (px < 10) return `€${px.toFixed(4)}`
                    return `€${px.toFixed(2)}`
                  }
                  return (
                    <tr key={o.id}>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                        <div>{o.created_at ? new Date(o.created_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—'}</div>
                        {o.closed_at && (
                          <div style={{ fontSize: '0.7rem', color: 'var(--accent-primary)' }}>
                            Clôturé : {new Date(o.closed_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}
                          </div>
                        )}
                      </td>
                      <td style={{ fontWeight: 600 }}>{o.symbol}</td>
                      <td>
                        <span className={`badge badge-${o.side === 'buy' ? 'buy' : 'sell'}`}>
                          {o.side}
                        </span>
                      </td>
                      <td className="cell-number">{o.quantity?.toFixed(6)}</td>
                      <td className="cell-number">{fmtPrice(o.price)}</td>
                      <td className="cell-number">{o.order_value_eur ? `€${o.order_value_eur.toFixed(2)}` : '—'}</td>
                      <td className="cell-number" style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {o.fee_eur != null && o.fee_eur > 0 ? `€${o.fee_eur.toFixed(2)}` : '—'}
                      </td>
                      <td>
                        <span style={{
                          fontSize: '0.75rem',
                          color: o.status === 'filled' || o.status === 'paper'
                            ? 'var(--color-success)'
                            : o.status === 'cancelled' || o.status === 'failed'
                            ? 'var(--color-sell)'
                            : 'var(--color-hold)',
                          fontWeight: 600,
                        }}>
                          {o.status}
                        </span>
                      </td>
                      <td className={`cell-number ${
                        (o.realised_pnl || 0) > 0 ? 'cell-positive' : (o.realised_pnl || 0) < 0 ? 'cell-negative' : ''
                      }`}>
                        {o.realised_pnl != null ? `${o.realised_pnl >= 0 ? '+' : ''}${o.realised_pnl.toFixed(2)} €` : '—'}
                      </td>
                      <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', maxWidth: 340 }}>
                        {o.justification || '—'}
                      </td>
                      <td>
                        <span className={`badge badge-${o.paper_mode ? 'paper' : 'live'}`}>
                          {o.paper_mode ? 'paper' : 'live'}
                        </span>
                      </td>
                    </tr>
                  )
                })
              ) : (
                <tr>
                  <td colSpan={11} className="empty-state">
                    {ordersLoading ? 'Loading…' : 'No orders yet'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

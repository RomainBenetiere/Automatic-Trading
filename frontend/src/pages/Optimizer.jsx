import { useState, useCallback, useMemo } from 'react'
import {
  Sliders, Play, RefreshCw, TrendingUp, ShieldCheck,
  CheckCircle, AlertCircle, Clock, Search, Layers, Cpu
} from 'lucide-react'
import { usePolling } from '../hooks/usePolling'
import { config, jobs } from '../api/client'

export default function Optimizer() {
  const [triggering, setTriggering] = useState(false)
  const [triggerStatus, setTriggerStatus] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')

  const { data, loading, error, refetch } = usePolling(
    useCallback(() => config.getIndicators(), []),
    30000
  )

  const handleTrigger = async () => {
    setTriggering(true)
    setTriggerStatus(null)
    try {
      await jobs.triggerOptimizer()
      setTriggerStatus({
        type: 'success',
        message: "L'optimiseur hebdomadaire a été lancé avec succès en tâche de fond.",
      })
      setTimeout(() => refetch(), 4000)
    } catch (err) {
      setTriggerStatus({
        type: 'error',
        message: err.message || "Erreur lors du lancement de l'optimiseur.",
      })
    } finally {
      setTriggering(false)
    }
  }

  const optimizedList = useMemo(() => {
    return data?.optimized || []
  }, [data])

  const filteredList = useMemo(() => {
    if (!searchQuery.trim()) return optimizedList
    const q = searchQuery.toLowerCase().trim()
    return optimizedList.filter((item) =>
      item.symbol.toLowerCase().includes(q)
    )
  }, [optimizedList, searchQuery])

  // Summary KPIs
  const stats = useMemo(() => {
    if (!optimizedList.length) return null

    const sharpes = optimizedList
      .map((item) => item.oos_sharpe)
      .filter((s) => s != null && !isNaN(s))
    const avgSharpe = sharpes.length
      ? sharpes.reduce((a, b) => a + b, 0) / sharpes.length
      : null

    const returns = optimizedList
      .map((item) => item.oos_return)
      .filter((r) => r != null && !isNaN(r))
    const avgReturn = returns.length
      ? returns.reduce((a, b) => a + b, 0) / returns.length
      : null

    const lastRun = optimizedList.reduce((latest, item) => {
      if (!item.last_optimized_at) return latest
      const d = new Date(item.last_optimized_at)
      return !latest || d > latest ? d : latest
    }, null)

    return {
      count: optimizedList.length,
      avgSharpe,
      avgReturn,
      lastRun,
    }
  }, [optimizedList])

  const formatDate = (dateStr) => {
    if (!dateStr) return '—'
    const d = new Date(dateStr)
    return d.toLocaleDateString('fr-FR', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div>
      {/* Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Sliders size={28} style={{ color: 'var(--accent-primary)' }} />
            Paramètres Optimisés
          </h1>
          <p>
            Paramètres dynamiques des indicateurs (EMA, RSI, MACD, etc.) ajustés par walk-forward optimisation.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            onClick={refetch}
            disabled={loading}
            title="Rafraîchir"
          >
            <RefreshCw size={16} className={loading ? 'spin' : ''} />
            Actualiser
          </button>

          <button
            className="btn btn-primary"
            onClick={handleTrigger}
            disabled={triggering}
            style={{ display: 'flex', alignItems: 'center', gap: 8 }}
          >
            {triggering ? (
              <>
                <RefreshCw size={16} className="spin" />
                Optimisation en cours...
              </>
            ) : (
              <>
                <Play size={16} />
                Lancer l'optimiseur
              </>
            )}
          </button>
        </div>
      </div>

      {/* Trigger Notification */}
      {triggerStatus && (
        <div
          style={{
            marginBottom: 20,
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            background: triggerStatus.type === 'success' ? 'var(--color-buy-dim)' : 'var(--color-sell-dim)',
            border: `1px solid ${triggerStatus.type === 'success' ? 'var(--color-buy)' : 'var(--color-sell)'}`,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            color: 'var(--text-primary)',
          }}
        >
          {triggerStatus.type === 'success' ? (
            <CheckCircle size={18} style={{ color: 'var(--color-buy)' }} />
          ) : (
            <AlertCircle size={18} style={{ color: 'var(--color-sell)' }} />
          )}
          <span>{triggerStatus.message}</span>
        </div>
      )}

      {/* KPI Cards */}
      <div className="summary-grid" style={{ marginBottom: 28 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-label">Actifs Optimisés</span>
            <Cpu size={18} style={{ color: 'var(--accent-primary)' }} />
          </div>
          <div className="card-value">{stats ? stats.count : 0}</div>
          <div className="card-caption">Cryptos & actions en portefeuille</div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-label">Sharpe Moyen (OOS)</span>
            <TrendingUp size={18} style={{ color: 'var(--color-buy)' }} />
          </div>
          <div className="card-value" style={{ color: stats?.avgSharpe > 1 ? 'var(--color-buy)' : 'inherit' }}>
            {stats?.avgSharpe != null ? stats.avgSharpe.toFixed(2) : '—'}
          </div>
          <div className="card-caption">Sur données hors-échantillon (30% test)</div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-label">Rendement Moyen (OOS)</span>
            <ShieldCheck size={18} style={{ color: 'var(--accent-secondary)' }} />
          </div>
          <div className="card-value">
            {stats?.avgReturn != null ? `${(stats.avgReturn * 100).toFixed(1)}%` : '—'}
          </div>
          <div className="card-caption">Performance de validation testée</div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-label">Dernière Exécution</span>
            <Clock size={18} style={{ color: 'var(--color-hold)' }} />
          </div>
          <div className="card-value" style={{ fontSize: '1.25rem', marginTop: 4 }}>
            {stats?.lastRun ? formatDate(stats.lastRun) : 'Jamais'}
          </div>
          <div className="card-caption">Planification hebdo automatique</div>
        </div>
      </div>

      {/* Main Table: Optimized Parameters per Symbol */}
      <div className="section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div className="section-title" style={{ margin: 0 }}>
            <Sliders size={20} style={{ color: 'var(--accent-primary)' }} />
            Paramètres Spécifiques par Actif
          </div>

          <div style={{ position: 'relative', minWidth: 220 }}>
            <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Filtrer par symbole..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px 8px 36px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-input)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
              }}
            />
          </div>
        </div>

        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          {filteredList.length === 0 ? (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)' }}>
              {optimizedList.length === 0 ? (
                <>
                  <Sliders size={48} style={{ marginBottom: 12, opacity: 0.4 }} />
                  <p style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                    Aucun paramètre optimisé pour le moment
                  </p>
                  <p style={{ maxWidth: 460, margin: '0 auto 16px', fontSize: '0.9rem' }}>
                    L'optimiseur teste automatiquement des combinaisons sur 70% d'historique et valide sur 30% hors-échantillon.
                    Cliquez sur le bouton ci-dessus pour lancer votre première optimisation !
                  </p>
                </>
              ) : (
                <p>Aucun actif correspondant à la recherche "{searchQuery}".</p>
              )}
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Actif</th>
                    <th>EMA (Rapide / Lente)</th>
                    <th>RSI Fenêtre</th>
                    <th>MACD (Fast / Slow / Sig)</th>
                    <th>Bollinger</th>
                    <th>Sharpe OOS</th>
                    <th>Sortino OOS</th>
                    <th>Rendement OOS</th>
                    <th>Dernière Optimisation</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredList.map((item) => {
                    const p = item.parameters || {}
                    const sharpe = item.oos_sharpe
                    const sharpeClass =
                      sharpe == null
                        ? ''
                        : sharpe >= 1.0
                        ? 'cell-positive'
                        : sharpe < 0
                        ? 'cell-negative'
                        : ''

                    return (
                      <tr key={item.id || item.symbol}>
                        <td style={{ fontWeight: 600 }}>
                          <span
                            style={{
                              background: 'var(--accent-primary-dim)',
                              color: 'var(--accent-primary)',
                              padding: '4px 8px',
                              borderRadius: 'var(--radius-sm)',
                              fontFamily: 'monospace',
                            }}
                          >
                            {item.symbol}
                          </span>
                        </td>
                        <td>
                          {p.ema_fast != null && p.ema_slow != null ? (
                            <span>{p.ema_fast} / {p.ema_slow}</span>
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>Défaut</span>
                          )}
                        </td>
                        <td>
                          {p.rsi_window != null ? (
                            <span>{p.rsi_window}</span>
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>Défaut</span>
                          )}
                        </td>
                        <td>
                          {p.macd_fast != null ? (
                            <span>{p.macd_fast} / {p.macd_slow} / {p.macd_signal}</span>
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>Défaut</span>
                          )}
                        </td>
                        <td>
                          {p.bollinger_window != null ? (
                            <span>{p.bollinger_window} (std: {p.bollinger_std || 2.0})</span>
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>Défaut</span>
                          )}
                        </td>
                        <td className={`cell-number ${sharpeClass}`}>
                          {sharpe != null ? sharpe.toFixed(2) : '—'}
                        </td>
                        <td className="cell-number">
                          {item.oos_sortino != null ? item.oos_sortino.toFixed(2) : '—'}
                        </td>
                        <td className={`cell-number ${item.oos_return > 0 ? 'cell-positive' : item.oos_return < 0 ? 'cell-negative' : ''}`}>
                          {item.oos_return != null ? `${(item.oos_return * 100).toFixed(1)}%` : '—'}
                        </td>
                        <td style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                          {formatDate(item.last_optimized_at || item.updated_at)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Reference: Default Volatility Regimes */}
      <div className="section" style={{ marginTop: 32 }}>
        <div className="section-title">
          <Layers size={20} style={{ color: 'var(--accent-secondary)' }} />
          Paramètres par Défaut selon le Régime de Volatilité (Benchmark)
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: 16 }}>
          Lorsqu'un actif n'a pas encore de paramètres optimisés sur mesure (ou si l'optimisation ne bat pas le marché hors-échantillon),
          le moteur applique automatiquement ces valeurs en fonction de la volatilité mesurée (ATR 30 jours) :
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          {data?.defaults && [
            { key: 'high_volatility', label: 'Haute Volatilité (ATR élevé)', color: 'var(--color-sell)', data: data.defaults.high_volatility },
            { key: 'medium_volatility', label: 'Moyenne Volatilité (Standard)', color: 'var(--accent-primary)', data: data.defaults.medium_volatility },
            { key: 'low_volatility', label: 'Faible Volatilité (Marché calme)', color: 'var(--color-buy)', data: data.defaults.low_volatility },
          ].map(({ key, label, color, data: reg }) => (
            <div key={key} className="card" style={{ borderTop: `3px solid ${color}` }}>
              <div style={{ fontWeight: 600, color, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>{label}</span>
              </div>
              <div style={{ fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>
                  <span style={{ color: 'var(--text-muted)' }}>EMA Rapide / Lente</span>
                  <span style={{ fontWeight: 600 }}>{reg?.ema_fast} / {reg?.ema_slow}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>
                  <span style={{ color: 'var(--text-muted)' }}>SMA Court / Long</span>
                  <span style={{ fontWeight: 600 }}>{reg?.sma_short} / {reg?.sma_long}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>
                  <span style={{ color: 'var(--text-muted)' }}>RSI Fenêtre</span>
                  <span style={{ fontWeight: 600 }}>{reg?.rsi_window}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>
                  <span style={{ color: 'var(--text-muted)' }}>MACD (Fast / Slow / Signal)</span>
                  <span style={{ fontWeight: 600 }}>{reg?.macd_fast} / {reg?.macd_slow} / {reg?.macd_signal}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Bandes de Bollinger</span>
                  <span style={{ fontWeight: 600 }}>{reg?.bollinger_window} (std: {reg?.bollinger_std || 2.0})</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

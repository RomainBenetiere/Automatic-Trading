import { useState, useCallback, useMemo } from 'react'
import {
  Compass, TrendingUp, TrendingDown, RefreshCw, Copy, Check,
  Sliders, ShoppingBag, Sparkles, Filter, Search, Eye, EyeOff
} from 'lucide-react'
import { crypto } from '../api/client'
import { usePolling } from '../hooks/usePolling'

const INDICATOR_CONFIG = [
  { key: 'sma_cross', label: 'SMA Cross', shortLabel: 'SMA', fullName: 'SMA Cross (Rapide/Lente)', envKey: 'TECH_WEIGHT_SMA_CROSS' },
  { key: 'ema_cross', label: 'EMA Cross', shortLabel: 'EMA', fullName: 'EMA Cross (Rapide/Lente)', envKey: 'TECH_WEIGHT_EMA_CROSS' },
  { key: 'macd', label: 'MACD', shortLabel: 'MACD', fullName: 'MACD (Ligne/Signal & Croisement)', envKey: 'TECH_WEIGHT_MACD' },
  { key: 'rsi', label: 'RSI', shortLabel: 'RSI', fullName: 'RSI Momentum (Survente <30 / Surachat >70)', envKey: 'TECH_WEIGHT_RSI' },
  { key: 'roc', label: 'ROC', shortLabel: 'ROC', fullName: 'Rate of Change (Accélération)', envKey: 'TECH_WEIGHT_ROC' },
  { key: 'stochastic', label: 'Stochastique', shortLabel: 'Stoch', fullName: 'Stochastique (%K / %D)', envKey: 'TECH_WEIGHT_STOCHASTIC' },
  { key: 'bollinger', label: 'Bollinger', shortLabel: 'Boll', fullName: 'Bandes de Bollinger (Position)', envKey: 'TECH_WEIGHT_BOLLINGER' },
  { key: 'obv', label: 'OBV', shortLabel: 'OBV', fullName: 'On-Balance Volume (Pente 10 bougies)', envKey: 'TECH_WEIGHT_OBV' },
]

function formatEur(val) {
  if (val == null) return '—'
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(2)} M€`
  if (val >= 1_000) return `${(val / 1_000).toFixed(1)} k€`
  return `${val.toFixed(2)} €`
}

function formatPrice(val) {
  if (val == null) return '—'
  if (val >= 100) return `${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
  if (val >= 1) return `${val.toFixed(3)} €`
  if (val >= 0.01) return `${val.toFixed(4)} €`
  return `${val.toFixed(6)} €`
}

function SignalBadge({ signal }) {
  if (!signal) return <span className="text-muted">—</span>
  const label = signal.replace('_', ' ').toUpperCase()
  return <span className={`badge badge-${signal}`}>{label}</span>
}

function AmplitudeBadge({ value, indicatorName, weight = 1.0 }) {
  if (value == null) return <span className="text-muted" style={{ fontSize: '0.75rem' }}>—</span>

  let bg = 'rgba(148, 163, 184, 0.1)'
  let color = 'var(--text-muted)'
  let border = '1px solid transparent'

  if (value >= 1.5) {
    bg = 'rgba(16, 185, 129, 0.25)'
    color = '#34d399'
    border = '1px solid rgba(16, 185, 129, 0.5)'
  } else if (value >= 1.0) {
    bg = 'rgba(16, 185, 129, 0.18)'
    color = '#10b981'
  } else if (value > 0) {
    bg = 'rgba(6, 182, 212, 0.15)'
    color = '#38bdf8'
  } else if (value <= -1.5) {
    bg = 'rgba(244, 63, 94, 0.25)'
    color = '#fb7185'
    border = '1px solid rgba(244, 63, 94, 0.5)'
  } else if (value <= -1.0) {
    bg = 'rgba(244, 63, 94, 0.18)'
    color = '#f43f5e'
  } else if (value < 0) {
    bg = 'rgba(245, 158, 11, 0.15)'
    color = '#fbbf24'
  }

  const sign = value > 0 ? '+' : ''
  const displayVal = Number.isInteger(value) ? `${sign}${value}.0` : `${sign}${value.toFixed(1)}`

  return (
    <span
      title={`${indicatorName || 'Signal'}: amplitude ${displayVal} (Poids .env: ${weight})`}
      style={{
        display: 'inline-block',
        minWidth: 36,
        textAlign: 'center',
        padding: '2px 5px',
        borderRadius: 4,
        background: bg,
        color: color,
        border: border,
        fontSize: '0.75rem',
        fontWeight: Math.abs(value) >= 1.0 ? 700 : 500,
        fontFamily: 'monospace',
      }}
    >
      {displayVal}
    </span>
  )
}

export default function CryptoScreener() {
  const [refreshing, setRefreshing] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterMode, setFilterMode] = useState('all') // 'all', 'bullish', 'basket', 'held', 'candidates'
  const [sortBy, setSortBy] = useState('volume') // 'volume', 'score', 'change', 'rsi'
  const [copied, setCopied] = useState(false)
  const [selectedMarkets, setSelectedMarkets] = useState(null)
  const [showIndicators, setShowIndicators] = useState(true)

  const { data, loading, refetch } = usePolling(
    useCallback(() => crypto.getScreener(), []),
    60000
  )

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await crypto.getScreener({ force_refresh: true })
      await refetch()
    } catch (e) {
      console.error('Failed to refresh screener:', e)
    } finally {
      setRefreshing(false)
    }
  }

  const currentBasket = data?.current_basket || []
  const activeSelected = selectedMarkets !== null ? selectedMarkets : new Set(currentBasket)

  const toggleMarket = (market) => {
    const next = new Set(activeSelected)
    if (next.has(market)) {
      next.delete(market)
    } else {
      next.add(market)
    }
    setSelectedMarkets(next)
  }

  const selectCurrentBasket = () => {
    setSelectedMarkets(new Set(currentBasket))
  }

  const selectTopVolume = (count = 5) => {
    if (!data?.markets) return
    const top = data.markets.slice(0, count).map((m) => m.market)
    setSelectedMarkets(new Set(top))
  }

  const selectTopBullish = () => {
    if (!data?.markets) return
    const bullish = data.markets
      .filter((m) => m.signal === 'strong_buy' || m.signal === 'buy')
      .map((m) => m.market)
    setSelectedMarkets(new Set(bullish))
  }

  const clearSelection = () => {
    setSelectedMarkets(new Set())
  }

  const technicalWeights = data?.technical_weights || {
    sma_cross: 1.0,
    ema_cross: 1.0,
    macd: 1.0,
    rsi: 1.0,
    roc: 1.0,
    stochastic: 1.0,
    bollinger: 1.0,
    obv: 1.0,
  }

  const totalWeight = Object.values(technicalWeights).reduce((a, b) => a + Number(b), 0)

  // Filtered and sorted markets
  const markets = useMemo(() => {
    if (!data?.markets) return []
    let list = [...data.markets]

    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase().trim()
      list = list.filter(
        (m) =>
          m.symbol.toLowerCase().includes(q) ||
          m.market.toLowerCase().includes(q)
      )
    }

    if (filterMode === 'bullish') {
      list = list.filter((m) => m.signal === 'strong_buy' || m.signal === 'buy')
    } else if (filterMode === 'basket') {
      list = list.filter((m) => m.in_basket)
    } else if (filterMode === 'held') {
      list = list.filter((m) => m.in_portfolio)
    } else if (filterMode === 'candidates') {
      list = list.filter((m) => !m.in_basket)
    }

    if (sortBy === 'volume') {
      list.sort((a, b) => (b.volume_eur || 0) - (a.volume_eur || 0))
    } else if (sortBy === 'score') {
      list.sort((a, b) => (b.technical_score || 0) - (a.technical_score || 0))
    } else if (sortBy === 'change') {
      list.sort((a, b) => (b.change_24h_pct || 0) - (a.change_24h_pct || 0))
    } else if (sortBy === 'rsi') {
      list.sort((a, b) => (a.rsi || 100) - (b.rsi || 100))
    }

    return list
  }, [data?.markets, searchTerm, filterMode, sortBy])

  // Summary statistics
  const stats = useMemo(() => {
    if (!data?.markets || data.markets.length === 0) {
      return { totalVolume: 0, topGainer: null, bullishCount: 0, total: 0 }
    }
    const totalVolume = data.markets.reduce((acc, m) => acc + (m.volume_eur || 0), 0)
    const bullishCount = data.markets.filter(
      (m) => m.signal === 'strong_buy' || m.signal === 'buy'
    ).length
    const sortedGainers = [...data.markets].sort(
      (a, b) => (b.change_24h_pct || 0) - (a.change_24h_pct || 0)
    )
    const topGainer = sortedGainers[0]
    return {
      totalVolume,
      topGainer,
      bullishCount,
      total: data.markets.length,
    }
  }, [data?.markets])

  const envLine = `CRYPTO_BASKET=${Array.from(activeSelected).join(',')}`

  const copyToClipboard = () => {
    navigator.clipboard.writeText(envLine)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div>
      {/* Page Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Compass size={28} style={{ color: 'var(--accent-primary)' }} />
            <h1>Opportunités Crypto (Top 30 Bitvavo)</h1>
          </div>
          <p>
            Les 30 paires EUR les plus liquides du marché Bitvavo, analysées en 4H pour composer votre panier de trading.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            className="btn btn-secondary"
            onClick={handleRefresh}
            disabled={refreshing || loading}
          >
            <RefreshCw size={16} className={refreshing ? 'spin' : ''} />
            {refreshing ? 'Calcul en cours…' : 'Actualiser'}
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="metrics-grid" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card metric-card">
          <div className="metric-icon" style={{ background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)' }}>
            <Sparkles size={20} />
          </div>
          <div className="metric-body">
            <span className="metric-label">Actifs Analysés</span>
            <span className="metric-value">{stats.total} Paires</span>
            <span className="metric-sub">Cotées en EUR sur Bitvavo</span>
          </div>
        </div>

        <div className="card metric-card">
          <div className="metric-icon" style={{ background: 'rgba(16, 185, 129, 0.15)', color: 'var(--color-buy)' }}>
            <TrendingUp size={20} />
          </div>
          <div className="metric-body">
            <span className="metric-label">Volume 24h Global</span>
            <span className="metric-value">{formatEur(stats.totalVolume)}</span>
            <span className="metric-sub">Cumul top 30 marchés</span>
          </div>
        </div>

        <div className="card metric-card">
          <div className="metric-icon" style={{ background: 'rgba(245, 158, 11, 0.15)', color: 'var(--color-hold)' }}>
            <ShoppingBag size={20} />
          </div>
          <div className="metric-body">
            <span className="metric-label">Signaux d'Achat</span>
            <span className="metric-value">{stats.bullishCount} / {stats.total}</span>
            <span className="metric-sub">BUY ou STRONG BUY en 4H</span>
          </div>
        </div>

        <div className="card metric-card">
          <div className="metric-icon" style={{ background: 'var(--accent-secondary-dim)', color: 'var(--accent-secondary)' }}>
            <TrendingUp size={20} />
          </div>
          <div className="metric-body">
            <span className="metric-label">Top Performance 24h</span>
            <span className="metric-value" style={{ color: (stats.topGainer?.change_24h_pct || 0) >= 0 ? 'var(--color-buy)' : 'var(--color-sell)' }}>
              {stats.topGainer ? `${stats.topGainer.change_24h_pct > 0 ? '+' : ''}${stats.topGainer.change_24h_pct}%` : '—'}
            </span>
            <span className="metric-sub">{stats.topGainer?.symbol || '—'}</span>
          </div>
        </div>
      </div>

      {/* Technical Weights Indicator Bar */}
      <div
        className="card"
        style={{
          marginBottom: 'var(--space-lg)',
          padding: '16px 20px',
          border: '1px solid var(--border-subtle)',
          background: 'rgba(17, 24, 39, 0.65)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Sliders size={18} style={{ color: 'var(--accent-primary)' }} />
              <h2 style={{ fontSize: '1.05rem', fontWeight: 600, margin: 0 }}>
                Pondération des 8 Indicateurs Techniques (.env)
              </h2>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 4 }}>
              Poids appliqués pour le calcul du Score Technique (0–100). Modifiables dans <code>.env</code> via <code>TECH_WEIGHT_*</code>.
            </p>
          </div>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setShowIndicators(!showIndicators)}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            {showIndicators ? <EyeOff size={15} /> : <Eye size={15} />}
            {showIndicators ? 'Masquer colonnes indicateurs' : 'Afficher colonnes indicateurs'}
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8 }}>
          {INDICATOR_CONFIG.map(({ key, shortLabel, fullName, envKey }) => {
            const weight = Number(technicalWeights[key] ?? 1.0)
            const pct = totalWeight > 0 ? ((weight / totalWeight) * 100).toFixed(1) : '12.5'
            return (
              <div
                key={key}
                style={{
                  background: 'rgba(10, 14, 26, 0.7)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '8px 10px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                }}
                title={`${fullName}\nVariable .env: ${envKey}=${weight}`}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.775rem', fontWeight: 700, color: 'var(--text-primary)' }}>{shortLabel}</span>
                  <span style={{ fontSize: '0.725rem', color: 'var(--accent-primary)', fontWeight: 600 }}>{pct}%</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 }}>
                  <span style={{ fontSize: '0.675rem', color: 'var(--text-muted)' }}>Poids</span>
                  <span style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: '#38bdf8', fontWeight: 600 }}>
                    {weight.toFixed(1)}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Basket Generator Card */}
      <div
        className="card"
        style={{
          marginBottom: 'var(--space-lg)',
          border: '1px solid rgba(6, 182, 212, 0.35)',
          background: 'linear-gradient(180deg, rgba(17, 24, 39, 0.9) 0%, rgba(15, 23, 42, 0.8) 100%)',
          boxShadow: '0 8px 32px rgba(6, 182, 212, 0.08)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Sliders size={20} style={{ color: 'var(--accent-primary)' }} />
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, margin: 0 }}>
                Générateur de Panier .env (CRYPTO_BASKET)
              </h2>
              <span className="badge" style={{ background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)', fontWeight: 600 }}>
                {activeSelected.size} actif{activeSelected.size > 1 ? 's' : ''} sélectionné{activeSelected.size > 1 ? 's' : ''}
              </span>
            </div>
            <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', marginTop: 4 }}>
              Cochez les cryptos souhaitées dans la liste ci-dessous, puis cliquez sur Copier pour mettre à jour votre fichier <code>.env</code>.
            </p>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-secondary btn-sm" onClick={selectCurrentBasket}>
              Panier actuel ({currentBasket.length})
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => selectTopVolume(5)}>
              Top 5 Volume
            </button>
            <button className="btn btn-secondary btn-sm" onClick={selectTopBullish}>
              Top Signaux Achat
            </button>
            <button className="btn btn-secondary btn-sm" onClick={clearSelection}>
              Vider
            </button>
          </div>
        </div>

        {/* Code display with Copy button */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'rgba(10, 14, 26, 0.9)',
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-subtle)',
            gap: 12,
            fontFamily: 'monospace',
            fontSize: '0.9rem',
          }}
        >
          <div style={{ overflowX: 'auto', whiteSpace: 'nowrap', color: '#38bdf8' }}>
            {envLine}
          </div>
          <button
            className={`btn ${copied ? 'btn-secondary' : 'btn-primary'}`}
            style={{
              padding: '8px 16px',
              flexShrink: 0,
              background: copied ? 'var(--color-buy)' : undefined,
              color: copied ? '#ffffff' : undefined,
            }}
            onClick={copyToClipboard}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? 'Copié dans le presse-papier !' : 'Copier pour .env'}
          </button>
        </div>

        {/* Selected chips preview */}
        {activeSelected.size > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
            {Array.from(activeSelected).map((m) => (
              <span
                key={m}
                onClick={() => toggleMarket(m)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '3px 10px',
                  borderRadius: '12px',
                  background: 'rgba(6, 182, 212, 0.15)',
                  border: '1px solid rgba(6, 182, 212, 0.3)',
                  color: 'var(--text-primary)',
                  fontSize: '0.775rem',
                  cursor: 'pointer',
                }}
                title="Cliquer pour retirer"
              >
                <strong>{m}</strong>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>×</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ marginBottom: 'var(--space-md)', padding: '12px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          {/* Search */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '1 1 240px', maxWidth: 360 }}>
            <Search size={16} style={{ color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Rechercher par symbole (ex: BTC, SOL, AVAX)..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{
                width: '100%',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
                outline: 'none',
              }}
            />
          </div>

          {/* Filter Chips */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button
              className={`btn btn-sm ${filterMode === 'all' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setFilterMode('all')}
            >
              Tous ({data?.markets?.length || 0})
            </button>
            <button
              className={`btn btn-sm ${filterMode === 'bullish' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setFilterMode('bullish')}
            >
              Bullish ({stats.bullishCount})
            </button>
            <button
              className={`btn btn-sm ${filterMode === 'candidates' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setFilterMode('candidates')}
            >
              Candidats hors-panier
            </button>
            <button
              className={`btn btn-sm ${filterMode === 'basket' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setFilterMode('basket')}
            >
              Panier actuel (.env)
            </button>
            <button
              className={`btn btn-sm ${filterMode === 'held' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setFilterMode('held')}
            >
              En portefeuille
            </button>
          </div>

          {/* Sort Selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Filter size={16} style={{ color: 'var(--text-muted)' }} />
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Trier :</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              style={{
                background: 'var(--bg-input)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '4px 8px',
                fontSize: '0.8rem',
                outline: 'none',
              }}
            >
              <option value="volume">Volume 24h (€)</option>
              <option value="score">Score Technique</option>
              <option value="change">Variation 24h (%)</option>
              <option value="rsi">RSI (Survente en premier)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Main Table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 40, textAlign: 'center' }}>Sélec.</th>
                <th style={{ width: 44 }}>#</th>
                <th>Actif</th>
                <th style={{ textAlign: 'right' }}>Prix</th>
                <th style={{ textAlign: 'right' }}>Var 24h</th>
                <th style={{ textAlign: 'right' }}>Volume 24h</th>
                <th style={{ textAlign: 'center' }}>RSI 4H</th>
                <th style={{ textAlign: 'center' }}>Score Tech</th>
                <th style={{ textAlign: 'center' }}>Signal</th>
                {showIndicators && (
                  <>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="SMA Cross (Poids: {technicalWeights.sma_cross})">SMA</th>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="EMA Cross (Poids: {technicalWeights.ema_cross})">EMA</th>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="MACD (Poids: {technicalWeights.macd})">MACD</th>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="RSI (Poids: {technicalWeights.rsi})">RSI</th>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="ROC (Poids: {technicalWeights.roc})">ROC</th>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="Stochastique (Poids: {technicalWeights.stochastic})">Stoch</th>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="Bollinger (Poids: {technicalWeights.bollinger})">Boll</th>
                    <th style={{ textAlign: 'center', background: 'rgba(6, 182, 212, 0.08)' }} title="OBV (Poids: {technicalWeights.obv})">OBV</th>
                  </>
                )}
                <th style={{ textAlign: 'center' }}>Statut</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data && (
                <tr>
                  <td colSpan={showIndicators ? 18 : 10} style={{ textAlign: 'center', padding: 'var(--space-2xl)' }}>
                    <RefreshCw size={24} className="spin" style={{ color: 'var(--accent-primary)', marginBottom: 8 }} />
                    <p style={{ color: 'var(--text-muted)' }}>Chargement et analyse des marchés Bitvavo en cours…</p>
                  </td>
                </tr>
              )}

              {markets.length === 0 && !loading && (
                <tr>
                  <td colSpan={showIndicators ? 18 : 10} style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-muted)' }}>
                    Aucun actif ne correspond aux critères de filtre.
                  </td>
                </tr>
              )}

              {markets.map((m, idx) => {
                const isSelected = activeSelected.has(m.market)
                const isPositive = (m.change_24h_pct || 0) >= 0
                const sigs = m.indicator_signals || {}

                return (
                  <tr
                    key={m.market}
                    style={{
                      background: isSelected ? 'rgba(6, 182, 212, 0.05)' : undefined,
                    }}
                  >
                    {/* Checkbox */}
                    <td style={{ textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleMarket(m.market)}
                        style={{ cursor: 'pointer', transform: 'scale(1.15)', accentColor: 'var(--accent-primary)' }}
                        title="Ajouter / retirer du panier"
                      />
                    </td>

                    {/* Rank */}
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                      #{idx + 1}
                    </td>

                    {/* Asset / Pair */}
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
                          {m.symbol}
                        </span>
                        <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                          {m.market}
                        </span>
                      </div>
                    </td>

                    {/* Price */}
                    <td className="cell-number" style={{ fontWeight: 600 }}>
                      {formatPrice(m.price)}
                    </td>

                    {/* 24h Change */}
                    <td className="cell-number" style={{ color: isPositive ? 'var(--color-buy)' : 'var(--color-sell)' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, justifyContent: 'flex-end' }}>
                        {isPositive ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                        {isPositive ? '+' : ''}{m.change_24h_pct?.toFixed(2)}%
                      </span>
                    </td>

                    {/* 24h EUR Volume */}
                    <td className="cell-number" style={{ fontWeight: 500 }}>
                      {formatEur(m.volume_eur)}
                    </td>

                    {/* RSI (valeur brute) */}
                    <td style={{ textAlign: 'center' }}>
                      {m.rsi != null ? (
                        <span
                          style={{
                            fontWeight: 600,
                            fontSize: '0.825rem',
                            padding: '2px 8px',
                            borderRadius: '6px',
                            background:
                              m.rsi <= 35
                                ? 'rgba(16, 185, 129, 0.15)'
                                : m.rsi >= 70
                                ? 'rgba(244, 63, 94, 0.15)'
                                : 'rgba(148, 163, 184, 0.1)',
                            color:
                              m.rsi <= 35
                                ? 'var(--color-buy)'
                                : m.rsi >= 70
                                ? 'var(--color-sell)'
                                : 'var(--text-primary)',
                          }}
                        >
                          {m.rsi}
                        </span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>

                    {/* Technical Score */}
                    <td style={{ textAlign: 'center' }}>
                      {m.technical_score != null ? (
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <div
                            style={{
                              width: 44,
                              height: 6,
                              borderRadius: 3,
                              background: 'rgba(255, 255, 255, 0.1)',
                              overflow: 'hidden',
                            }}
                          >
                            <div
                              style={{
                                width: `${Math.min(100, Math.max(0, m.technical_score))}%`,
                                height: '100%',
                                background:
                                  m.technical_score >= 60
                                    ? 'var(--color-buy)'
                                    : m.technical_score >= 40
                                    ? 'var(--color-hold)'
                                    : 'var(--color-sell)',
                              }}
                            />
                          </div>
                          <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>
                            {Math.round(m.technical_score)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>

                    {/* Signal */}
                    <td style={{ textAlign: 'center' }}>
                      <SignalBadge signal={m.signal} />
                    </td>

                    {/* 8 Technical Indicator Amplitudes */}
                    {showIndicators && (
                      <>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.sma_cross} indicatorName="SMA Cross" weight={technicalWeights.sma_cross} />
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.ema_cross} indicatorName="EMA Cross" weight={technicalWeights.ema_cross} />
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.macd} indicatorName="MACD" weight={technicalWeights.macd} />
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.rsi} indicatorName="RSI" weight={technicalWeights.rsi} />
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.roc} indicatorName="ROC" weight={technicalWeights.roc} />
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.stochastic} indicatorName="Stochastique" weight={technicalWeights.stochastic} />
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.bollinger} indicatorName="Bollinger" weight={technicalWeights.bollinger} />
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <AmplitudeBadge value={sigs.obv} indicatorName="OBV" weight={technicalWeights.obv} />
                        </td>
                      </>
                    )}

                    {/* Status */}
                    <td style={{ textAlign: 'center' }}>
                      <div style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap', justifyContent: 'center' }}>
                        {m.in_basket && (
                          <span
                            className="badge"
                            style={{
                              background: 'rgba(6, 182, 212, 0.15)',
                              color: 'var(--accent-primary)',
                              fontSize: '0.7rem',
                            }}
                          >
                            Panier .env
                          </span>
                        )}
                        {m.in_portfolio && (
                          <span
                            className="badge"
                            style={{
                              background: 'rgba(139, 92, 246, 0.15)',
                              color: 'var(--accent-secondary)',
                              fontSize: '0.7rem',
                            }}
                          >
                            Portefeuille
                          </span>
                        )}
                        {!m.in_basket && !m.in_portfolio && (
                          <span
                            className="badge"
                            style={{
                              background: 'rgba(148, 163, 184, 0.1)',
                              color: 'var(--text-muted)',
                              fontSize: '0.7rem',
                            }}
                          >
                            Candidat
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

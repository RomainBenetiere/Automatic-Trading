import { useState, useCallback } from 'react'
import {
  Settings as SettingsIcon, Shield, Clock, Wifi, WifiOff,
  Play, RefreshCw, Sliders, Globe
} from 'lucide-react'
import { usePolling } from '../hooks/usePolling'
import { config as configApi, health, jobs } from '../api/client'

export default function Settings() {
  const [triggering, setTriggering] = useState({})

  const { data: appConfig, loading: configLoading } = usePolling(
    useCallback(() => configApi.get(), []),
    60000
  )
  const { data: healthData, loading: healthLoading, refetch: refetchHealth } = usePolling(
    useCallback(() => health.check(), []),
    30000
  )
  const { data: jobsData, refetch: refetchJobs } = usePolling(
    useCallback(() => jobs.getStatus(), []),
    30000
  )

  const handleTrigger = async (jobId) => {
    setTriggering(prev => ({ ...prev, [jobId]: true }))
    try {
      if (jobId.includes('crypto')) await jobs.triggerCrypto()
      else if (jobId.includes('optimizer')) await jobs.triggerOptimizer()
      else await jobs.triggerStocks()
      refetchJobs()
    } catch (e) { console.error(e) }
    setTriggering(prev => ({ ...prev, [jobId]: false }))
  }

  const StatusDot = ({ status }) => {
    const cls = status === 'connected' ? 'connected' : status === 'degraded' ? 'degraded' : 'error'
    return <span className={`status-dot ${cls}`} />
  }

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>System configuration, guardrail thresholds, and service status</p>
      </div>

      {/* Service Connectivity */}
      <div className="section">
        <div className="section-title">
          <Wifi size={20} style={{ color: 'var(--accent-primary)' }} />
          Service Connectivity
        </div>
        <div className="summary-grid">
          {healthData?.services && Object.entries(healthData.services).map(([name, svc], i) => (
            <div key={name} className={`card animate-in animate-in-delay-${i + 1}`}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <StatusDot status={svc.status} />
                <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>{name}</span>
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 4 }}>
                {svc.status}
                {svc.url && <span> • {svc.url}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Guardrail Configuration */}
      <div className="section">
        <div className="section-title">
          <Shield size={20} style={{ color: 'var(--accent-primary)' }} />
          Guardrail Configuration
        </div>
        <div className="card">
          {appConfig?.guardrails ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 'var(--space-lg)' }}>
              {Object.entries(appConfig.guardrails).map(([key, val]) => (
                <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                    {key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                  </span>
                  <span style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                    {typeof val === 'number' ? (key.includes('pct') ? `${val}%` : key.includes('eur') ? `€${val}` : val) : val}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state">{configLoading ? 'Loading…' : 'Configuration unavailable'}</div>
          )}
          <div style={{ marginTop: 'var(--space-md)', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            To change guardrail values, edit the <code style={{ background: 'var(--bg-input)', padding: '2px 6px', borderRadius: 4 }}>.env</code> file and restart the backend.
          </div>
        </div>
      </div>

      {/* Score Weights */}
      <div className="section">
        <div className="section-title">
          <Sliders size={20} style={{ color: 'var(--accent-secondary)' }} />
          Score Weights (Technical, Fundamental, Dividend)
        </div>
        <div className="card">
          {appConfig?.weights ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-lg)' }}>
              {Object.entries(appConfig.weights).map(([type, weights]) => (
                <div key={type}>
                  <div style={{ fontWeight: 600, textTransform: 'capitalize', marginBottom: 8 }}>{type}</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {weights.split(',').map((w, i) => {
                      const labels = ['Tech', 'Fund', 'Div']
                      const colors = ['var(--accent-primary)', 'var(--accent-secondary)', 'var(--color-hold)']
                      return (
                        <div key={i} style={{
                          flex: 1,
                          textAlign: 'center',
                          padding: '8px',
                          background: `${colors[i]}15`,
                          borderRadius: 'var(--radius-sm)',
                          border: `1px solid ${colors[i]}30`,
                        }}>
                          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: colors[i] }}>{w}%</div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{labels[i]}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {/* Scheduler */}
      <div className="section">
        <div className="section-title">
          <Clock size={20} style={{ color: 'var(--color-hold)' }} />
          Scheduler
        </div>
        <div className="card">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            {jobsData?.jobs?.map((job) => (
              <div key={job.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{job.name}</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    Next run: {job.next_run ? new Date(job.next_run).toLocaleString('fr-FR') : 'Not scheduled'}
                  </div>
                </div>
                <button
                  className="btn btn-secondary"
                  onClick={() => handleTrigger(job.id)}
                  disabled={triggering[job.id]}
                >
                  <Play size={14} />
                  {triggering[job.id] ? 'Running…' : 'Trigger'}
                </button>
              </div>
            )) || <div className="empty-state">Scheduler data unavailable</div>}
          </div>
        </div>
      </div>

      {/* System Info */}
      <div className="section">
        <div className="section-title">
          <Globe size={20} style={{ color: 'var(--text-muted)' }} />
          System Info
        </div>
        <div className="card">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-md)' }}>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Mode</div>
              <div style={{ fontWeight: 600 }}>
                <span className={`badge badge-${appConfig?.mode || 'paper'}`}>
                  {appConfig?.mode || 'paper'}
                </span>
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>LLM Provider</div>
              <div style={{ fontWeight: 600 }}>{appConfig?.llm_provider || '—'} / {appConfig?.llm_model || '—'}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Language</div>
              <div style={{ fontWeight: 600 }}>{appConfig?.synthesis_language === 'fr' ? 'Français' : 'English'}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Crypto Basket</div>
              <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>
                {appConfig?.crypto_basket?.join(', ') || '—'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

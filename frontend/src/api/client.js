/**
 * API client for communicating with the FastAPI backend.
 */

const BASE_URL = '/api'

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

// ── Portfolio ──────────────────────────────────────────────────
export const portfolio = {
  getPositions: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/portfolio/positions${qs ? '?' + qs : ''}`)
  },
  getPosition: (symbol) => request(`/portfolio/positions/${symbol}`),
  sync: () => request('/portfolio/sync', { method: 'POST' }),
}

// ── Scores ─────────────────────────────────────────────────────
export const scores = {
  getLatest: () => request('/scores/latest'),
  getHistory: (symbol, params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/scores/${symbol}/history${qs ? '?' + qs : ''}`)
  },
}

// ── Recommendations ────────────────────────────────────────────
export const recommendations = {
  getLatest: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/recommendations/latest${qs ? '?' + qs : ''}`)
  },
  getHistory: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/recommendations/history${qs ? '?' + qs : ''}`)
  },
}

// ── Crypto ─────────────────────────────────────────────────────
export const crypto = {
  getPositions: () => request('/crypto/positions'),
  getOrders: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/crypto/orders${qs ? '?' + qs : ''}`)
  },
  getOrder: (id) => request(`/crypto/orders/${id}`),
  getGuardrailStatus: () => request('/crypto/guardrails/status'),
  getCircuitBreakerEvents: () => request('/crypto/circuit-breaker/events'),
  getPerformance: (days = 30) => request(`/crypto/performance?days=${days}`),
}

// ── Config ─────────────────────────────────────────────────────
export const config = {
  get: () => request('/config'),
}

// ── Health ─────────────────────────────────────────────────────
export const health = {
  check: () => request('/health'),
}

// ── Jobs ───────────────────────────────────────────────────────
export const jobs = {
  triggerCrypto: () => request('/jobs/crypto/trigger', { method: 'POST' }),
  triggerStocks: () => request('/jobs/stocks/trigger', { method: 'POST' }),
  getStatus: () => request('/jobs/status'),
}

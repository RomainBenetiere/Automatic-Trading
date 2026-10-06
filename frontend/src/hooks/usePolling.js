import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * Custom hook for polling an API endpoint at a given interval.
 * 
 * @param {Function} fetchFn - async function to call
 * @param {number} intervalMs - polling interval in milliseconds (default: 30s)
 * @param {boolean} enabled - whether polling is active
 * @returns {{ data, loading, error, refetch }}
 */
export function usePolling(fetchFn, intervalMs = 30000, enabled = true) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  const refetch = useCallback(async () => {
    try {
      setLoading(prev => prev === true ? true : false) // Don't flash loading on refetch
      const result = await fetchFn()
      setData(result)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [fetchFn])

  useEffect(() => {
    if (!enabled) return

    // Initial fetch
    refetch()

    // Set up interval
    if (intervalMs > 0) {
      intervalRef.current = setInterval(refetch, intervalMs)
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [refetch, intervalMs, enabled])

  return { data, loading, error, refetch }
}

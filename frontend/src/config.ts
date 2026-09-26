import { useEffect, useState } from 'react'

/** Display-only thresholds served from backend config.py via /api/config. */
export interface PublicConfig {
  conf_band_high: number
  conf_band_low: number
  pause_min_ms: number
  long_pause_min_ms: number
  low_conf_threshold: number
}

let cached: Promise<PublicConfig | null> | null = null

function loadConfig(): Promise<PublicConfig | null> {
  cached ??= fetch('/api/config')
    .then((r) => (r.ok ? (r.json() as Promise<PublicConfig>) : null))
    .catch(() => null)
  return cached
}

export function usePublicConfig(): PublicConfig | null {
  const [config, setConfig] = useState<PublicConfig | null>(null)
  useEffect(() => {
    let live = true
    void loadConfig().then((c) => live && setConfig(c))
    return () => {
      live = false
    }
  }, [])
  return config
}

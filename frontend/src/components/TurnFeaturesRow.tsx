import { usePublicConfig } from '../config'
import type { TurnFeatures } from '../types'

const num = (v: number | null, digits = 0) => (v == null ? '—' : v.toFixed(digits))
const pct = (v: number | null) => (v == null ? '—' : `${Math.round(v * 100)}%`)

interface Item {
  label: string
  value: string
  title: string
  flag?: boolean
}

/** Per-turn features mini-panel (PROJECT.md §4.1 / §6). */
export function TurnFeaturesRow({ f }: { f: TurnFeatures }) {
  const cfg = usePublicConfig()
  const pauseMs = cfg ? `${cfg.pause_min_ms} ms` : 'threshold'
  const longMs = cfg ? `${cfg.long_pause_min_ms} ms` : 'threshold'
  const lowConf = cfg ? cfg.low_conf_threshold.toFixed(2) : 'threshold'
  const items: Item[] = [
    {
      label: 'rate',
      value: f.speaking_rate_wpm == null ? '—' : `${num(f.speaking_rate_wpm)} wpm`,
      title: `${f.word_count} words in ${f.duration_s.toFixed(2)} s`,
    },
    {
      label: 'pauses',
      value: `${f.pause_count}${f.long_pause_count ? ` (${f.long_pause_count} long)` : ''}`,
      title: `gaps ≥ ${pauseMs}; long ≥ ${longMs}. mean ${num(f.mean_pause_ms)} ms, max ${num(f.max_pause_ms)} ms`,
      flag: f.long_pause_count > 0,
    },
    {
      label: 'fillers',
      value: String(f.filler_count),
      title: `${pct(f.filler_rate)} of words`,
      flag: f.filler_count > 0,
    },
    {
      label: 'conf',
      value: `${num(f.mean_asr_conf, 2)} / min ${num(f.min_asr_conf, 2)}`,
      title: 'mean and minimum ASR word confidence',
    },
    {
      label: 'low-conf',
      value: pct(f.low_conf_frac),
      title: `share of words with confidence < ${lowConf}`,
      flag: (f.low_conf_frac ?? 0) > 0,
    },
  ]
  if (f.repetition_overlap != null) {
    items.push({
      label: 'overlap',
      value: `${pct(f.repetition_overlap)}${f.is_repetition ? ' · repetition' : ''}`,
      title: 'token overlap (Jaccard) with the previous turn',
      flag: f.is_repetition,
    })
  }
  if (f.self_repair_markers.length) {
    items.push({
      label: 'self-repair',
      value: f.self_repair_markers.map((m) => `“${m}”`).join(', '),
      title: 'mid-turn self-repair markers',
      flag: true,
    })
  }

  return (
    <dl className="features" aria-label="Turn features">
      {items.map((it) => (
        <div key={it.label} className={it.flag ? 'feat feat-flag' : 'feat'} title={it.title}>
          <dt>{it.label}</dt>
          <dd>
            {it.flag && <span aria-hidden="true">● </span>}
            {it.value}
          </dd>
        </div>
      ))}
    </dl>
  )
}

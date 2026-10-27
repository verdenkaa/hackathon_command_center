import { useEffect, useState } from 'react'

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): [T | null, string, () => void] {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const reload = () => {
    fn()
      .then(setData)
      .catch((e) => setError((e as Error).message))
  }
  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return [data, error, reload]
}

export function fmt(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}д ${h}ч`
  if (h > 0) return `${h}ч ${m}м`
  return `${m}м`
}

/** Оценка в человеко-читаемом виде: 5400 -> "1ч 30м". */
export function secondsToHm(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h}ч ${m}м` : `${m}м`
}

/** "1:30" -> 5400; null если формат неверный. */
export function hmToSeconds(hm: string): number | null {
  const m = /^(\d{1,3}):([0-5]\d)$/.exec(hm.trim())
  if (!m) return null
  return parseInt(m[1], 10) * 3600 + parseInt(m[2], 10) * 60
}

/** Бэкенд хранит наивный UTC — дополняем 'Z', чтобы браузер считал время правильно. */
export function parseUTC(iso: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : iso + 'Z')
}

export function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return parseUTC(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span>{title}</span>
          <button className="ghost small" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
    </label>
  )
}

export function Badge({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={`badge ${kind}`}>{children}</span>
}

export function badgeForStatus(status: string): string {
  switch (status) {
    case 'green':
    case 'resolved':
    case 'done':
    case 'realised':
      return 'green'
    case 'yellow':
    case 'open':
      return 'yellow'
    case 'red':
    case 'confirmed':
      return 'red'
    case 'running':
      return 'blue'
    default:
      return 'gray'
  }
}

/** Линейный график (burn-down) на SVG. */
export function LineChart({ points }: { points: { date: string; remaining: number; completed: number }[] }) {
  const w = 640
  const h = 200
  const pad = 28
  if (points.length === 0) return <div className="muted">Нет данных для графика</div>
  const maxY = Math.max(1, ...points.map((p) => p.remaining))
  const x = (i: number) => pad + (i * (w - 2 * pad)) / Math.max(1, points.length - 1)
  const y = (v: number) => h - pad - (v * (h - 2 * pad)) / maxY
  const line = (key: 'remaining' | 'completed') =>
    points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(p[key])}`).join(' ')
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => (
    <line key={f} x1={pad} x2={w - pad} y1={y(maxY * f)} y2={y(maxY * f)} stroke="var(--border)" strokeWidth="1" />
  ))
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', maxWidth: 760 }}>
      {grid}
      <path d={line('remaining')} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <path d={line('completed')} fill="none" stroke="var(--ok)" strokeWidth="2" />
      {points.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.remaining)} r={2.5} fill="var(--accent)" />
      ))}
      {points.map((p, i) =>
        i % Math.max(1, Math.floor(points.length / 8)) === 0 || i === points.length - 1 ? (
          <text key={i} x={x(i)} y={h - 8} fill="var(--muted)" fontSize="9" textAnchor="middle">
            {p.date.slice(5)}
          </text>
        ) : null,
      )}
    </svg>
  )
}

/** Горизонтальные бары (время по участникам, прогресс модулей). */
export function BarList({ items }: { items: { label: string; value: number; max: number; display: string }[] }) {
  const max = Math.max(1, ...items.map((i) => i.max))
  return (
    <div className="grid" style={{ gap: 8 }}>
      {items.map((i, idx) => (
        <div key={idx} className="row">
          <span style={{ width: 160, flexShrink: 0 }}>{i.label}</span>
          <div className="bar-track grow">
            <div className="bar-fill" style={{ width: `${Math.min(100, (i.value / max) * 100)}%` }} />
          </div>
          <span className="mono muted" style={{ width: 90, textAlign: 'right' }}>{i.display}</span>
        </div>
      ))}
    </div>
  )
}

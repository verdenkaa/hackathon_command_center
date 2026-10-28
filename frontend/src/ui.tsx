import { useCallback, useEffect, useRef, useState } from 'react'

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): [T | null, string, () => void] {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const latest = useRef(fn)
  latest.current = fn
  const sequence = useRef(0)
  const alive = useRef(true)
  const reload = useCallback(() => {
    const request = ++sequence.current
    latest.current()
      .then(value=>{if(alive.current && request===sequence.current){setData(value);setError('')}})
      .catch((e) => {if(alive.current && request===sequence.current)setError((e as Error).message)})
  },[])
  useEffect(() => {
    alive.current = true
    reload()
    return ()=>{alive.current=false;sequence.current++}
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
  return parseUTC(iso).toLocaleString('ru-RU', { timeZone:'Europe/Moscow', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export const PRIORITIES: Record<string,string> = {low:'Низкий', medium:'Средний', high:'Высокий', critical:'Критический'}
export function toMoscowInput(iso: string | null): string {
  if (!iso) return ''
  return new Date(parseUTC(iso).getTime() + 3*3600000).toISOString().slice(0,16)
}
export function fromMoscowInput(value: string): string | null {
  return value ? new Date(value + ':00+03:00').toISOString() : null
}
export function incidentKind(i: {level:string;status:string}): string {
  return i.status === 'resolved' ? 'gray' : i.level === 'red' && i.status === 'open' ? 'purple' : i.level
}
export function incidentLabel(i: {level:string;status:string}): string {
  return i.status === 'resolved' ? 'Закрыт' : i.level === 'red' && i.status === 'open' ? 'Ожидает подтверждения' : i.status === 'confirmed' ? 'Подтверждён' : 'Открыт'
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
    case 'purple':
      return 'purple'
    default:
      return 'gray'
  }
}

/** Линейный график (burn-down) на SVG. */
export function LineChart({ points }: { points: { date: string; remaining: number; completed: number; ideal?:number }[] }) {
  const w = 640
  const h = 200
  const pad = 42
  if (points.length === 0) return <div className="muted">Нет истории создания и перемещения задач. График появится после первого изменения.</div>
  const maxY = Math.max(1, ...points.flatMap((p) => [p.remaining, p.completed, p.ideal ?? 0]))
  const times = points.map(p => parseUTC(p.date).getTime())
  const x = (i: number) => pad + ((times[i]-times[0]) * (w - 2 * pad)) / Math.max(1, times[times.length-1]-times[0])
  const y = (v: number) => h - pad - (v * (h - 2 * pad)) / maxY
  const line = (key: 'remaining' | 'completed' | 'ideal') =>
    points.map((p, i) => i===0 ? `M ${x(i)} ${y(p[key] ?? 0)}` : key==='ideal' ? `L ${x(i)} ${y(p[key] ?? 0)}` : `H ${x(i)} V ${y(p[key] ?? 0)}`).join(' ')
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => (
    <line key={f} x1={pad} x2={w - pad} y1={y(maxY * f)} y2={y(maxY * f)} stroke="var(--border)" strokeWidth="1" />
  ))
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', maxWidth: 760 }}>
      {grid}
      <text x={4} y={14} fill="var(--muted)" fontSize="10">Задачи, шт.</text>
      <text x={w/2} y={h-1} fill="var(--muted)" fontSize="10">Время (МСК)</text>
      <text x={4} y={y(maxY)} fill="var(--muted)" fontSize="10">{maxY}</text>
      <text x={20} y={y(0)} fill="var(--muted)" fontSize="10">0</text>
      <path d={line('remaining')} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <path d={line('completed')} fill="none" stroke="var(--ok)" strokeWidth="2" />
      {points.some(p => p.ideal != null) && <path d={line('ideal')} fill="none" stroke="var(--warn)" strokeWidth="2" strokeDasharray="5 4" />}
      {points.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.remaining)} r={2.5} fill="var(--accent)" />
      ))}
      {points.map((p, i) =>
        i % Math.max(1, Math.ceil((points.length - 1) / 4)) === 0 || i === points.length - 1 ? (
          <text key={i} x={x(i)} y={h - 20} fill="var(--muted)" fontSize="9" textAnchor="middle">
            {fmtDate(p.date)}
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

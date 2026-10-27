import { useEffect, useState } from 'react'
import { api, Analytics as AnalyticsData, Recommendation, Me, currentProject } from './api'
import { MockAi, AiRequestView } from './MockAi'
import { Badge, BarList, LineChart, badgeForStatus, fmt, fmtDuration, fmtDate, useLoad } from './ui'

export function Analytics({ me }: { me: Me }) {
  const [data, error, reload] = useLoad<AnalyticsData>(api.analytics)
  const [recs, , reloadRecs] = useLoad<Recommendation[]>(api.recommendations)
  const [msg, setMsg] = useState('')
  const isCaptain = me.roles.some((r) => r.role === 'admin' || (r.role === 'captain' && r.project_id === currentProject()))

  useEffect(() => {
    const id = setInterval(reload, 5000)
    return () => clearInterval(id)
  }, [reload])

  if (!data) return <div>{error || 'Загрузка…'}</div>

  const k = data.kpi
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', margin: '4px 0 12px' }}>
        <h3 style={{ margin: 0 }}>Аналитика</h3>
        <button className="small" onClick={reload}>Обновить</button>
      </div>

      <div className="row" style={{ flexWrap: 'wrap', marginBottom: 16 }}>
        <Kpi label="Прогресс" value={`${k.progress_percent}%`} />
        <Kpi label="Задач" value={k.total_tasks} />
        <Kpi label="Завершено" value={k.completed_tasks} />
        <Kpi label="В работе" value={k.in_progress_tasks} />
        <Kpi label="Просрочено" value={k.overdue_tasks} warn={k.overdue_tasks > 0} />
        <Kpi label="До дедлайна" value={k.deadline_seconds_left != null ? fmtDuration(k.deadline_seconds_left) : '—'} warn={k.deadline_seconds_left != null && k.deadline_seconds_left < 6 * 3600} />
        <Kpi label="План / Факт" value={`${fmt(k.estimate_seconds)} / ${fmt(k.actual_seconds)}`} />
        <Kpi label="Календарное" value={fmt(k.calendar_seconds)} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="section-title">Burn-down (осталось задач по дням)</div>
          <LineChart points={data.burn_down} />
          <div className="row muted" style={{ fontSize: 11, marginTop: 4 }}>
            <span style={{ color: 'var(--accent)' }}>— осталось</span>
            <span style={{ color: 'var(--ok)' }}>— завершено</span>
          </div>
        </div>
        <div className="card">
          <div className="section-title">Время по участникам</div>
          <BarList
            items={data.time_by_user.map((u) => ({
              label: u.display_name,
              value: u.seconds,
              max: data.time_by_user[0]?.seconds ?? 1,
              display: fmt(u.seconds),
            }))}
          />
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
        <div className="card">
          <div className="section-title">Модули</div>
          <BarList
            items={data.modules.map((m) => ({
              label: `${m.name} (${m.done}/${m.total})`,
              value: m.progress,
              max: 100,
              display: `${m.progress}%`,
            }))}
          />
          {data.modules.length === 0 && <div className="muted">Модулей нет</div>}
        </div>
        <div className="card">
          <div className="section-title">Риски и блокеры</div>
          <div className="grid" style={{ gap: 6 }}>
            {data.active_incidents.map((i) => (
              <div key={i.id} className="row">
                <Badge kind={badgeForStatus(i.status === 'confirmed' ? 'red' : i.level)}>{i.level}</Badge>
                <span>{i.title}</span>
              </div>
            ))}
            {data.risks.filter((r) => r.type === 'overdue').map((r, i) => (
              <div key={i} className="row">
                <Badge kind="red">overdue</Badge>
                <span>{r.title}</span>
              </div>
            ))}
            {data.active_incidents.length === 0 && data.risks.length === 0 && (
              <div className="muted">Рисков нет</div>
            )}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="section-title">Участники</div>
        <table>
          <thead>
            <tr>
              <th>Участник</th>
              <th>Светофор</th>
              <th>Активные задачи</th>
              <th>Таймер</th>
              <th>Время всего</th>
            </tr>
          </thead>
          <tbody>
            {data.participants.map((p) => {
              const time = data.time_by_user.find((t) => t.user_id === p.id)?.seconds ?? 0
              return (
                <tr key={p.id}>
                  <td>{p.display_name} <span className="muted">({p.login})</span></td>
                  <td><Badge kind={badgeForStatus(p.traffic_status)}>{p.traffic_status}</Badge></td>
                  <td>{p.active_tasks}</td>
                  <td className="mono">{fmt(p.active_timer_seconds)}</td>
                  <td className="mono">{fmt(time)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div className="section-title" style={{ margin: 0 }}>Рекомендации ИИ</div>
          <Badge kind="blue">мок · без внешних запросов</Badge>
        </div>
        <MockAi onRun={reloadRecs} />
        {msg && <div className="error" style={{ marginTop: 6 }}>{msg}</div>}
        <div className="grid" style={{ gap: 8, marginTop: 8 }}>
          {(recs ?? []).slice(0, 10).map((r) => (
            <div key={r.id} style={{ borderLeft: '2px solid var(--accent)', paddingLeft: 10 }}>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                <b>{r.summary}</b>
                <span className="muted" style={{ fontSize: 11 }}>{r.trigger} · {fmtDate(r.created_at)}</span>
              </div>
              <div style={{ fontSize: 13, marginTop: 2 }}>{r.content}</div>
              <div className="muted">{r.excluded ? 'Исключена из следующего контекста' : 'Может войти в контекст следующих запросов'}</div>
              {isCaptain && <button className="small" onClick={async () => {
                try { await api.excludeRecommendation(r.id); reloadRecs() }
                catch (e) { setMsg((e as Error).message) }
              }}>{r.excluded ? 'Вернуть в контекст' : 'Исключить из контекста'}</button>}
              {r.request_context && <details><summary>Сохранённый запрос · {r.provider} · mock</summary><AiRequestView context={r.request_context}/></details>}
            </div>
          ))}
          {(recs ?? []).length === 0 && (
            <div className="muted" style={{ fontSize: 13 }}>
              Рекомендаций пока нет. Включите ИИ в настройках и запросите анализ.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Kpi({ label, value, warn }: { label: string; value: string | number; warn?: boolean }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value" style={{ color: warn ? 'var(--error)' : 'var(--text)' }}>{value}</div>
    </div>
  )
}

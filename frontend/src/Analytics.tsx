import { useEffect, useState } from 'react'
import { api, Analytics as AnalyticsData, Recommendation, Me, currentProject } from './api'
import { MockAi, AiRequestView } from './MockAi'
import { Badge, BarList, LineChart, badgeForStatus, fmt, fmtDuration, fmtDate, useLoad, incidentKind, incidentLabel } from './ui'

export function Analytics({ me }: { me: Me }) {
  const [data, error, reload] = useLoad<AnalyticsData>(api.analytics)
  const [recs, , reloadRecs] = useLoad<Recommendation[]>(api.recommendations)
  const [msg, setMsg] = useState('')
  const isCaptain = me.roles.some((r) => r.role === 'admin' || (r.role === 'captain' && r.project_id === currentProject()))

  useEffect(() => {
    const id = setInterval(reload, 1000)
    return () => clearInterval(id)
  }, [reload])

  if (!data) return <div>{error || 'Загрузка…'}</div>

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', margin: '4px 0 12px' }}>
        <h3 style={{ margin: 0 }}>Аналитика</h3>
        <button className="small" onClick={reload}>Обновить</button>
      </div>

      <AnalyticsMetrics data={data} />
      <div className="grid analytics-grid" style={{ gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="section-title">Оставшаяся работа: количество задач во времени</div>
          <LineChart points={data.burn_down} />
          {data.burn_down[0]?.observation_only && <p className="muted">Пока доступен только текущий срез.</p>}
          <div className="row muted" style={{ fontSize: 11, marginTop: 4 }}>
            <span style={{ color: 'var(--accent)' }}>— осталось</span>
            <span style={{ color: 'var(--ok)' }}>— завершено</span>
            {data.burn_down.some(p=>p.ideal != null) && <span style={{color:'var(--warn)'}}>┄ ориентир начального объёма к дедлайну</span>}
          </div>
        </div>
        <div className="card">
          <div className="section-title">Время по исполнителям</div>
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

      <div className="grid analytics-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
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
                <Badge kind={incidentKind(i)}>{incidentLabel(i)}</Badge>
                <span>#{i.number} {i.title}</span>
              </div>
            ))}
            {data.risks.filter((r) => r.type === 'overdue').map((r, i) => (
              <div key={i} className="row">
                <Badge kind="red">Просрочена</Badge>
                <span>{r.title}</span>
              </div>
            ))}
            {data.active_incidents.length === 0 && data.risks.length === 0 && (
              <div className="muted">Рисков нет</div>
            )}
          </div>
        </div>
      </div>

      <div className="card" style={{marginTop:16}}>
        <div className="section-title">Отклонения задач</div>
        {!data.deviations.length && <p className="muted">Просрочек и отклонений от заданных оценок нет.</p>}
        {data.deviations.map(t=><div key={t.task_id} className="section">
          <b>{t.title}</b> · {t.owners.join(', ') || 'Исполнитель не назначен'}
          {t.overdue_seconds>0 && <div>Просрочена на {fmt(t.overdue_seconds)}</div>}
          {t.overrun_seconds>0 && <div>Превышение оценки: {fmt(t.overrun_seconds)}</div>}
          {t.ahead_seconds>0 && <div>Завершена быстрее оценки на {fmt(t.ahead_seconds)}</div>}
        </div>)}
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
              <th>Время закреплённых задач</th>
            </tr>
          </thead>
          <tbody>
            {data.participants.map((p) => {
              const time = data.time_by_user.find((t) => t.user_id === p.id)?.seconds ?? 0
              return (
                <tr key={p.id}>
                  <td>{p.display_name} <span className="muted">({p.login})</span></td>
                  <td><Badge kind={badgeForStatus(p.traffic_status)}>{{green:'Нет блокеров',yellow:'Жёлтый блокер',red:'Красный блокер',purple:'Ожидает подтверждения'}[p.traffic_status] ?? 'Нет данных'}</Badge></td>
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

export function spendingSummary(k: Pick<AnalyticsData['kpi'],'total_tasks'|'progress_percent'|'estimate_seconds'|'actual_seconds'>): {timePercent:number|null;gap:number|null} {
  if (!k.total_tasks || k.estimate_seconds<=0) return {timePercent:null,gap:null}
  const timePercent=Math.round(k.actual_seconds/k.estimate_seconds*1000)/10
  return {timePercent,gap:Math.round((k.progress_percent-timePercent)*10)/10}
}

export function AnalyticsMetrics({data}:{data:AnalyticsData}) {
  const k=data.kpi
  const {timePercent,gap}=spendingSummary(k)
  return <>
    <div className="analytics-metrics">
      <section className="card metric-group" aria-label="Задачи">
        <h3>Задачи</h3>
        <div className="metric-values">
          <Kpi label="Всего" value={k.total_tasks}/><Kpi label="Завершено" value={k.completed_tasks}/>
          <Kpi label="В работе" value={k.in_progress_tasks}/><Kpi label="Просрочено" value={k.overdue_tasks} warn={k.overdue_tasks>0}/>
        </div>
        <ProgressLine label="Прогресс задач" value={k.progress_percent} color="var(--ok)"/>
      </section>
      <section className="card metric-group" aria-label="Таймеры">
        <h3>Таймеры</h3>
        <div className="metric-values">
          <Kpi label="Плановая оценка" value={fmt(k.estimate_seconds)}/>
          <Kpi label="Потрачено на задачи" value={fmt(k.actual_seconds)}/>
          <Kpi label="Время в работе" value={fmt(k.calendar_seconds)}/>
          <Kpi label="Активных таймеров" value={k.active_timers}/>
          <Kpi label="Осталось работы" value={fmt(data.forecast.remaining_seconds)}/>
          <Kpi label="До дедлайна" value={k.deadline_seconds_left==null?'—':fmtDuration(k.deadline_seconds_left)} warn={k.deadline_seconds_left!=null && k.deadline_seconds_left<21600}/>
        </div>
      </section>
      <section className="card metric-group" aria-label="Сведения">
        <h3>Сведения</h3>
        <ProgressLine label="Прогресс задач" value={k.progress_percent} color="var(--ok)"/>
        <ProgressLine label="Израсходовано оценки" value={timePercent} color="var(--accent)"/>
        <div className={`budget-balance ${gap==null?'':gap>=0?'positive':'negative'}`}>
          <b>{gap==null?'Нет оценки для сравнения':`${gap>=0?'+':''}${gap} п.п.`}</b>
          <span>{gap==null?'Задайте плановые оценки задач':gap>0?'Задачи опережают расход времени':gap<0?'Расход времени опережает задачи':'Задачи и расход времени идут вровень'}</span>
        </div>
      </section>
    </div>
    <div className="card forecast-strip">
      <b>Прогноз: {{on_track:'укладываемся',risk:'риск опоздания',late:'не укладываемся',insufficient_data:'недостаточно данных'}[data.forecast.status]}</b>
      {data.forecast.margin_seconds!=null && <span>{data.forecast.margin_seconds>=0?'Запас':'Опоздание'}: {fmt(Math.abs(data.forecast.margin_seconds))}</span>}
    </div>
  </>
}

function ProgressLine({label,value,color}:{label:string;value:number|null;color:string}) {
  return <div className="metric-progress">
    <div className="row"><span>{label}</span><b>{value==null?'—':`${value}%`}</b></div>
    <div className="bar-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value==null?undefined:Math.min(100,value)}>
      <div className="bar-fill" style={{width:`${Math.min(100,Math.max(0,value??0))}%`,background:color}}/>
    </div>
  </div>
}

function Kpi({ label, value, warn }: { label: string; value: string | number; warn?: boolean }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value" style={{ color: warn ? 'var(--error)' : 'var(--text)' }}>{value}</div>
    </div>
  )
}

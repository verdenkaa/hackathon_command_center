import { useEffect, useState } from 'react'
import { api, Analytics as AnalyticsData, Recommendation, Me, currentProject, SummaryTask } from './api'
import { useProjectUpdates } from './realtime'
import { MockAi, AiRequestView } from './MockAi'
import { Badge, badgeForStatus, fmt, fmtDuration, fmtDate, useLoad, incidentKind, incidentLabel } from './ui'

export function Analytics({ me, onOpenTask, onOpenIncident, onPlanning }: {
  me: Me; onOpenTask:(id:number)=>void; onOpenIncident:(id:number)=>void; onPlanning:()=>void
}) {
  const [data, error, reload] = useLoad<AnalyticsData>(api.analytics)
  const [recs, , reloadRecs] = useLoad<Recommendation[]>(api.recommendations)
  const [msg, setMsg] = useState('')
  const isCaptain = me.roles.some((r) => r.role === 'admin' || (r.role === 'captain' && r.project_id === currentProject()))
  useProjectUpdates(reload)
  useEffect(() => {
    const id = setInterval(reload, 60000)
    return () => clearInterval(id)
  }, [reload])
  if (!data) return <div role={error?'alert':'status'}>{error || 'Загрузка…'}{error&&<button onClick={reload}>Повторить</button>}</div>
  const s=data.summary
  return (
    <div className="operational-analytics">
      <div className="row analytics-heading">
        <h3>Аналитика</h3><span className="muted">Последнее успешное обновление: {fmtDate(s.generated_at)} МСК</span>
        <button className="small" onClick={reload}>Обновить</button>
      </div>
      {error&&<div className="error" role="alert">Не удалось обновить: {error}. Показан последний успешный снимок; время и таймеры относятся к нему.</div>}
      <AnalyticsMetrics data={data}/>
      <button className="small" onClick={onPlanning}>Открыть планирование</button>
      <OperationalSections summary={s} onOpenTask={onOpenTask} onOpenIncident={onOpenIncident}/>
      <details className="card"><summary>Подробности по времени</summary>
        <p>Фактическое время таймеров задач вне корзины: {fmt(data.kpi.actual_seconds)}. Это отдельная метрика; она не уменьшает незавершённую длительность.</p>
        <h4>Время задач, закреплённых за основным исполнителем</h4>
        {data.time_by_user.map(t=><p key={t.user_id??'none'}>{t.display_name}: {fmt(t.seconds)}</p>)}
        <p className="muted">Время общих задач не делится между участниками и не отражает личное отработанное время.</p>
      </details>
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

export function OperationalSections({summary:s,onOpenTask,onOpenIncident}:{summary:AnalyticsData['summary'];onOpenTask:(id:number)=>void;onOpenIncident:(id:number)=>void}) {
  const taskList=(ids:number[]) => <TaskList tasks={ids.map(id=>s.tasks.find(t=>t.id===id)).filter((t):t is SummaryTask=>!!t)} onOpen={onOpenTask} onIncident={onOpenIncident}/>
  const nearest=(ids:number[])=>{
    const tasks=s.tasks.filter(t=>ids.includes(t.id)&&t.availability!=='done').sort((a,b)=>(a.deadline??'9999').localeCompare(b.deadline??'9999')).slice(0,2)
    return <div className="nearest-tasks"><span className="nearest-title">Ближайшие задачи · МСК</span>{tasks.length?tasks.map(t=><button className="nearest-task" key={t.id} onClick={()=>onOpenTask(t.id)}><strong>#{t.id} {t.title}</strong><span>{t.deadline?fmtDate(t.deadline):'Срок не задан'}</span></button>):<span className="muted">Нет незавершённых задач</span>}</div>
  }
  const overlaps=(pairs:number[][])=>pairs.filter(ids=>ids.length===2&&ids.every(id=>s.tasks.some(t=>t.id===id&&t.availability!=='done')))
  const incidentLinks=(ids:number[]) => ids.map(id=>{const incident=s.incidents.find(i=>i.id===id);return incident?<button className="small" key={id} onClick={()=>onOpenIncident(id)}>Инцидент #{incident.number}: {incident.title}</button>:null})
  const stat=(label:string,value:number,tone:'good'|'bad'|'warn'|'neutral'='neutral')=><div className={`scan-stat tone-${tone}`}><strong>{value}</strong><span>{label}</span></div>
  return <>
    <section className="card"><h3>Участники и нагрузка</h3>
      <p className="muted">В работе: 1 — зелёный, 2 — жёлтый, 0 или 3+ — красный. Доступны: 0 — красный, 1+ — зелёный. Ожидают: 0–3 — зелёный, 4+ — красный. Инциденты и пересечения: 0 — зелёный, 1+ — красный.</p>
      <div className="workload-scroll" role="region" aria-label="Таблица нагрузки участников" tabIndex={0}><table className="workload-table"><thead><tr><th scope="col">Участник</th><th scope="col">В работе</th><th scope="col">Доступны</th><th scope="col">Ожидают</th><th scope="col">Инциденты</th><th scope="col">Пересечения</th><th scope="col">Ближайшие задачи и сроки (МСК)</th></tr></thead><tbody>
      {s.participants.map(p=><tr key={p.id}><th scope="row">{p.display_name}<div><Badge kind={badgeForStatus(p.traffic_status)}>{{green:'Нет прямых инцидентов',yellow:'Жёлтый блокер',red:'Красный блокер',purple:'Ожидает подтверждения'}[p.traffic_status]}</Badge></div></th>
        <td><WorkloadValue label="В работе" value={p.active_ids.length} tone={p.active_ids.length===1?'good':p.active_ids.length===2?'warn':'bad'} hint={p.active_ids.length?'есть активные задачи':'нет активных задач'}/></td>
        <td><WorkloadValue label="Доступны" value={p.ready_ids.length} tone={p.ready_ids.length?'good':'bad'} hint={p.ready_ids.length?'можно взять в работу':'нет доступных задач'}/></td>
        <td><WorkloadValue label="Ожидают" value={p.waiting_ids.length} tone={p.waiting_ids.length>3?'bad':'good'} hint={p.waiting_ids.length?'ожидают зависимостей':'нет ожидания'}/></td>
        <td><WorkloadValue label="Инциденты" value={p.incident_ids.length} tone={p.incident_ids.length?'bad':'good'} hint={p.incident_ids.length?'есть инциденты':'нет инцидентов'}/></td>
        <td><WorkloadValue label="Пересечения" value={overlaps(p.overlaps).length} tone={overlaps(p.overlaps).length?'bad':'good'} hint={overlaps(p.overlaps).length?'есть пересечения':'нет пересечений'}/></td>
        <td>{nearest(p.task_ids)}</td></tr>)}
      </tbody></table></div>{!s.participants.length&&<p className="muted">Нет участников</p>}
      <div className="overlap-pairs">{s.participants.flatMap(p=>overlaps(p.overlaps).map((ids,index)=><div className="overlap-pair" key={`${p.id}-${index}`}><strong>{p.display_name}</strong>{ids.map(id=>{const task=s.tasks.find(t=>t.id===id)!;return <span key={id}> — <button className="small" onClick={()=>onOpenTask(id)}>#{id} {task.title}</button></span>})}</div>))}</div>
    </section>
    <details className="card attention-section"><summary>Что требует внимания <span className="muted">{s.attention.length}</span></summary>
      {!s.attention.length&&<p className="tone-good">Выявленных проблем нет</p>}
      {s.plan.incomplete&&<p className="muted">Данные неполны: отсутствие выявленных проблем не означает, что план полностью проверен.</p>}
      <div className="attention-grid">{s.attention.map((a,i)=><article className="attention-item" key={i}><strong>{a.reason}</strong><div className="scan-actions">{a.task_ids.map(id=><button className="small" key={id} onClick={()=>onOpenTask(id)}>Задача #{id}</button>)}{a.incident_id&&<button className="small" onClick={()=>onOpenIncident(a.incident_id!)}>Открыть инцидент</button>}</div></article>)}</div>
      <h4>Влияние открытых инцидентов ({s.incidents.length})</h4>
      <div className="scan-grid">{s.incidents.map(i=><article className={`scan-card incident-impact ${i.level==='red'?'is-red':''}`} key={i.id}>
        <div className="scan-heading"><button onClick={()=>onOpenIncident(i.id)}>#{i.number} {i.title}</button><Badge kind={i.level==='red'?'red':'yellow'}>{incidentLabel(i)} · {i.status==='confirmed'?'подтверждён':'открыт'}</Badge></div>
        <div className="scan-stats">{stat('Затронуто задач',i.affected_task_ids.length,'warn')}{stat('Прямые цели',i.direct_task_ids.length)}{stat('Жёсткое влияние',i.hard_task_ids.length,'bad')}{stat('Возможное влияние',i.potential_task_ids.length,'warn')}{stat('Треков',i.track_ids.length)}</div>
        <p className="muted">Источник: {i.source_task_id?<button className="small" onClick={()=>onOpenTask(i.source_task_id!)}>Задача #{i.source_task_id}</button>:'не сохранён'} · Глубина: {i.cascade_depth}</p>
        <div className="impact-lists"><div><b>Прямые цели</b>{taskList(i.direct_task_ids)}</div><div><b>Жёсткое влияние</b>{taskList(i.hard_task_ids)}</div><div><b>Возможное влияние</b>{taskList(i.potential_task_ids)}</div></div>
        {i.targets.filter(t=>t.target_type!=='task').map(t=><p key={`${t.target_type}-${t.target_id}`}>{t.target_type==='module'?'Трек':'Участник'}: {t.target_type==='module'?s.tracks.find(x=>x.id===t.target_id)?.name:s.participants.find(x=>x.id===t.target_id)?.display_name}</p>)}
        {i.limitations.map((l,j)=><p className="muted" key={j}>{l}</p>)}
      </article>)}</div>
    </details>
    <section className="card"><h3>Треки</h3><div className="scan-grid">{s.tracks.map(track=><article className="scan-card" key={track.id??'none'}>
      <h4>{track.name}</h4><ProgressLine label={`Прогресс трека ${track.name}`} value={track.percent} color="var(--ok)"/><p className="muted">Завершено {track.done} из {track.total} задач</p>
      <div className="scan-stats">{stat('В работе',track.active)}{stat('Ожидают',track.waiting,track.waiting?'warn':'good')}{stat('Просрочено',track.overdue,track.overdue?'bad':'good')}{stat('С препятствиями',track.blocked,track.blocked?'bad':'good')}{stat('Инциденты',track.incident_ids.length,track.incident_ids.length?'bad':'good')}{stat('Не назначен исполнитель',s.tasks.filter(t=>track.task_ids.includes(t.id)&&!t.assignees.length).length,s.tasks.some(t=>track.task_ids.includes(t.id)&&!t.assignees.length)?'bad':'good')}</div>
      {nearest(track.task_ids)}
      <div className="scan-actions">{incidentLinks(track.incident_ids)}</div><details className="track-tasks"><summary>Задачи трека ({track.task_ids.length})</summary>{taskList(track.task_ids)}</details>
    </article>)}</div></section>
  </>
}

function WorkloadValue({label,value,tone,hint}:{label:string;value:number;tone:'good'|'bad'|'warn'|'neutral';hint:string}) {
  return <span className={`workload-value tone-${tone}`} title={hint} aria-label={`${label}: ${value}, ${hint}`}>{value}</span>
}

const PLAN_LABELS:Record<string,string>={on_track:'По текущему плану укладываемся',late:'План выходит за дедлайн',incomplete:'План неполный',overdue:'Дедлайн прошёл',completed:'Проект завершён',no_deadline:'Дедлайн не задан'}

export function AnalyticsMetrics({data}:{data:AnalyticsData}) {
  const {period:p,progress,plan}=data.summary
  return <section className="card">
    <h3>Состояние проекта и прогресс</h3><h2>{PLAN_LABELS[plan.status]}</h2>
    <p>Начало: {fmtDate(p.start)} · Дедлайн: {fmtDate(p.deadline)} · МСК (UTC+3)</p>
    <p>{p.phase==='before_start'?`До старта осталось ${fmtDuration(p.until_start_seconds??0)}`:p.phase==='overdue'?`Дедлайн прошёл ${fmtDuration(p.overdue_seconds??0)} назад`:p.remaining_seconds==null?'Дедлайн не задан':`До дедлайна ${fmtDuration(p.remaining_seconds)}`}</p>
    <p>Плановое окончание: {fmtDate(plan.finish)} · Охват: {plan.covered_tasks} из {plan.total_tasks} задач</p>
    {plan.deadline_delta_seconds!=null&&<p>{plan.incomplete?'Разница частичного окончания и дедлайна':plan.deadline_delta_seconds>0?'Выход за дедлайн':'Запас до дедлайна'}: {fmtDuration(Math.abs(plan.deadline_delta_seconds))}</p>}
    <div className="analytics-progress-grid">
      <div><ProgressLine label="По количеству задач" value={progress.tasks.percent} color="var(--ok)"/><p>{progress.tasks.numerator} из {progress.tasks.denominator}</p></div>
      <div><ProgressLine label="По длительности задач" value={progress.duration.percent} color="var(--accent)"/><p>{fmt(progress.duration.numerator)} из {fmt(progress.duration.denominator)}</p>{progress.duration.incomplete&&<p className="muted">Показатель неполный. Нет длительности: {progress.duration.missing_count}</p>}</div>
      <div><ProgressLine label="По календарному времени проекта" value={p.percent} color="var(--warn)"/><p>{p.elapsed_seconds==null||p.duration_seconds==null?p.unknown_reason:`${fmt(p.elapsed_seconds)} из ${fmt(p.duration_seconds)}`}</p></div>
    </div>
    <details><summary>Как рассчитано</summary><p>Источник: текущий план Ганта ({plan.source}). Время расчёта: {fmtDate(data.summary.generated_at)}. Охват: {plan.covered_tasks} из {plan.total_tasks}.</p>{plan.limitations.map((l,i)=><p className="muted" key={i}>{l}</p>)}<p>Плановое окончание не является точным прогнозом фактического завершения.</p></details>
  </section>
}

function TaskList({tasks,onOpen,onIncident}:{tasks:SummaryTask[];onOpen:(id:number)=>void;onIncident:(id:number)=>void}) {
  if(!tasks.length)return <p className="muted">Нет задач</p>
  return <div>{[...tasks].sort((a,b)=>(a.deadline??'9999').localeCompare(b.deadline??'9999')).map(t=><div className="summary-task" key={t.id}>
    <button className="small" onClick={()=>onOpen(t.id)}>#{t.id} {t.title}</button> · {t.column_title}
    <div className="muted">{t.track_name??'Без трека'} · {t.assignees.map(a=>a.display_name).join(', ')||'Без исполнителя'}{t.assignees.length>1?' · Общее исполнение':''} · Срок: {fmtDate(t.deadline)}</div>
    {t.waiting_reasons.map((r,i)=><p key={i}>{r}</p>)}{t.missing.length>0&&<p>{t.missing.join(' · ')}</p>}
    {t.blocking_incidents.map(i=><button className="small" key={i.id} onClick={()=>onIncident(i.id)}>Препятствие: #{i.number} {i.title} · {incidentLabel(i)}</button>)}
  </div>)}</div>
}

function ProgressLine({label,value,color}:{label:string;value:number|null;color:string}) {
  return <div className="metric-progress">
    <div className="row"><span>{label}</span><b>{value==null?'Нет данных':`${value}%`}</b></div>
    <div className="bar-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value==null?undefined:Math.min(100,value)}>
      <div className="bar-fill" style={{width:`${Math.min(100,Math.max(0,value??0))}%`,background:color}}/>
    </div>
  </div>
}

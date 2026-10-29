import { useEffect, useMemo, useState } from 'react'
import { api, Cascade, Incident, Me, Module, Participant, Task } from './api'
import {useProjectUpdates} from './realtime'
import { Badge, Field, Modal, badgeForStatus, fmtDate, useLoad, incidentKind, incidentLabel, PRIORITIES } from './ui'

export function matchesSource(t:Task,assignee:string,tag:string,track:string,meId:number):boolean {
  if(assignee==='none'&&t.assignees.length)return false
  if(assignee&&assignee!=='none'&&!t.assignees.some(a=>a.user_id===(assignee==='mine'?meId:Number(assignee))))return false
  if(tag&&!t.tags?.includes(tag))return false
  if(track==='none'&&t.module_id!==null)return false
  if(track&&track!=='none'&&t.module_id!==Number(track))return false
  return true
}

const minutes=(seconds:number)=>`${Math.round(seconds/60)} мин`
export function CascadeView({cascade,depth,compact=false,tasks=[]}:{cascade:Cascade;depth:number;compact?:boolean;tasks?:Task[]}) {
  const max=Math.max(1,...cascade.levels.map(l=>l.hard_task_ids.length+l.potential_task_ids.length))
  if(compact)return <div className="cascade-compact" title="Незавершённые задачи по глубинам 1–4; жёсткие / потенциальные">Каскад: {cascade.levels.map(l=><span key={l.depth}>гл. {l.depth}: <b>{l.hard_task_ids.length}</b> / {l.potential_task_ids.length}{l.depth===depth?' ←':''}</span>)}</div>
  const names=(ids:number[])=>ids.map(id=>`#${id} ${tasks.find(t=>t.id===id)?.title??''}`).join(', ')
  return <section className="cascade-analysis"><h4>Каскад блокировки · выбрана глубина {depth}</h4>
    <p className="muted">Жёсткий каскад — blocked by. Потенциальный риск — пути с мягкими связями. Уникальные незавершённые задачи, без исходной.</p>
    <div className="cascade-table-wrap"><table className="cascade-table"><thead><tr><th>Глубина</th><th>Жёсткий каскад</th><th>Потенциальный риск</th><th>Участники / треки</th><th>Плановый интервал</th></tr></thead><tbody>
      {cascade.levels.map(l=><tr key={l.depth} className={l.depth===depth?'chosen':''}><td>{l.depth}<div className="cascade-bar"><i style={{width:`${l.hard_task_ids.length/max*100}%`}}/><i className="potential" style={{width:`${l.potential_task_ids.length/max*100}%`}}/></div></td>
        <td title={names(l.hard_task_ids)}>{l.hard_task_ids.length} <small>(+{l.new_hard_count})</small></td><td title={names(l.potential_task_ids)}>{l.potential_task_ids.length} <small>(+{l.new_potential_count})</small></td><td>{l.user_ids.length} / {l.track_ids.length}</td><td>{fmtDate(l.start)} — {fmtDate(l.end)}</td></tr>)}
    </tbody></table></div>
    {cascade.levels.map(l=><details key={l.depth}><summary>Задачи на глубине {l.depth}</summary><p>Жёсткие: {names(l.hard_task_ids)||'нет'}</p><p>Потенциальные: {names(l.potential_task_ids)||'нет'}</p></details>)}
    <h4>Если решение задержится</h4><p className="muted">Расчёт по жёстким связям и текущим плановым интервалам. Мягкие связи не принуждают к переносу.</p>
    {cascade.scenarios.map(s=><p key={s.delay_seconds}>+{minutes(s.delay_seconds)} → затронет {s.task_ids.length} задач; завершение плана +{minutes(s.finish_shift_seconds)}{s.task_ids.length>0&&<small className="cascade-tasks">{names(s.task_ids)}</small>}</p>)}
    {cascade.limitations.map((s,i)=><p key={i} className="muted">{s}</p>)}
  </section>
}

function ageStr(seconds: number): string {
  if (seconds < 60) return `${seconds}с`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}м`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}ч`
  return `${Math.floor(seconds / 86400)}д`
}

export function Incidents({ me, openIncidentId, initialIncident }: { me: Me; openIncidentId?:number|null; initialIncident?:Incident }) {
  const [incidents, error, reload] = useLoad<Incident[]>(api.incidents)
  const [participants] = useLoad<Participant[]>(api.participants)
  const [tasks,,reloadTasks] = useLoad<Task[]>(api.tasks)
  const [modules,,reloadModules] = useLoad<Module[]>(api.modules)
  useProjectUpdates(()=>{reload();reloadTasks();reloadModules()})
  const [createOpen, setCreateOpen] = useState(false)
  const [selected, setSelected] = useState<Incident | null>(initialIncident ?? null)
  const [openError,setOpenError]=useState('')
  const [filter, setFilter] = useState('')

  useEffect(()=>{
    let active=true
    if(openIncidentId && !initialIncident) api.incident(openIncidentId).then(i=>{if(active)setSelected(i)}).catch(e=>{if(active)setOpenError(`Не удалось открыть блокер: ${e.message}`)})
    return ()=>{active=false}
  },[openIncidentId,initialIncident])

  // Авто-обновление (возраст инцидентов, новые события).
  useEffect(() => {
    const id = setInterval(reload, 5000)
    return () => clearInterval(id)
  }, [reload])

  const names = new Map((participants ?? []).map((p) => [p.id, p.display_name]))
  for(const incident of [...(incidents??[]),...(selected?[selected]:[])])
    for(const id of incident.deleted_user_ids??[])names.set(id,'Удалённый пользователь')
  const taskNames = new Map((tasks ?? []).map((t) => [t.id, t.title]))
  const moduleNames = new Map((modules ?? []).map((m) => [m.id, m.name]))
  const name = (id: number | null) => (id == null ? '—' : names.get(id) ?? `#${id}`)

  const list = (incidents ?? []).filter(
    (i) => !filter || i.status === filter || i.level === filter,
  )

  return (
    <div>
      <div className="row" style={{ margin: '4px 0 12px' }}>
        <h3 style={{ margin: 0 }}>Инциденты</h3>
        <span className="grow" />
        <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ maxWidth: 180 }}>
          <option value="">Все</option>
          <option value="open">Открытые</option>
          <option value="confirmed">Подтверждённые</option>
          <option value="resolved">Закрытые</option>
          <option value="yellow">Жёлтые</option>
          <option value="red">Красные</option>
        </select>
        <button className="primary" onClick={() => setCreateOpen(true)}>+ Инцидент</button>
      </div>

      {error && <div className="error">{error}</div>}
      {openError && <div className="error" role="alert">{openError}</div>}

      <div className="grid" style={{ gap: 8 }}>
        {list.map((i) => (
          <div key={i.id} className="card" style={{ cursor: 'pointer', padding: 10 }} onClick={() => setSelected(i)}>
            <div className="row">
              <Badge kind={incidentKind(i)}>{i.level === 'red' ? 'Красный' : 'Жёлтый'}</Badge>
              <Badge kind={incidentKind(i)}>{incidentLabel(i)}</Badge>
              <b>#{i.number} {i.title}</b>
              <span className="grow" />
              <span className="muted" style={{ fontSize: 12 }}>
                {ageStr(i.age_seconds)} · ответственный {name(i.owner_id)} · автор {name(i.author_id)}
              </span>
            </div>
            {i.cascade&&<CascadeView cascade={i.cascade} depth={i.cascade_depth??1} compact/>}
          </div>
        ))}
        {list.length === 0 && <div className="muted">Инцидентов нет</div>}
      </div>

      {createOpen && (
        <IncidentForm
          me={me}
          participants={participants ?? []}
          tasks={tasks ?? []}
          modules={modules ?? []}
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false)
            reload()
          }}
        />
      )}

      {selected && (
        <>
          <div className="side-backdrop" onClick={() => setSelected(null)} />
          <div className="side-panel">
            <IncidentPanel
              incident={(incidents ?? []).find(i=>i.id===selected.id) ?? selected}
              names={names}
              taskNames={taskNames}
              moduleNames={moduleNames}
              tasks={tasks??[]}
              onChanged={() => {
                reload()
                setSelected(null)
              }}
              onClose={() => setSelected(null)}
            />
          </div>
        </>
      )}
    </div>
  )
}

export function IncidentForm({
  me, participants, tasks, modules, onClose, onCreated,
}: {
  me: Me
  participants: Participant[]
  tasks: Task[]
  modules: Module[]
  onClose: () => void
  onCreated: () => void
}) {
  const [level, setLevel] = useState('yellow')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [impact, setImpact] = useState('')
  const [urgency, setUrgency] = useState('medium')
  const [ownerId, setOwnerId] = useState<number | null>(me.id)
  const [sourceId,setSourceId] = useState<number | null>(null)
  const [depth,setDepth] = useState(1)
  const [previewBusy,setPreviewBusy] = useState(false)
  const [busy,setBusy] = useState(false)
  const [targetTasks, setTargetTasks] = useState<number[]>([])
  const [targetUsers, setTargetUsers] = useState<number[]>([])
  const [targetModules, setTargetModules] = useState<number[]>([])
  const [taskSearch, setTaskSearch] = useState('')
  const [taskColumn, setTaskColumn] = useState('')
  const [onlyMine, setOnlyMine] = useState(false)
  const [sourceAssignee,setSourceAssignee]=useState('')
  const [sourceTag,setSourceTag]=useState('')
  const [sourceTrack,setSourceTrack]=useState('')
  const [cascade,setCascade]=useState<Cascade|null>(null)
  const [error, setError] = useState('')

  const openTasks = useMemo(
    () => tasks.filter((t) => t.column_semantic !== 'trash' && t.column_key !== 'trashed'),
    [tasks],
  )
  const filteredTasks = openTasks.filter((t) => {
    if (taskSearch && !t.title.toLowerCase().includes(taskSearch.toLowerCase())) return false
    if (taskColumn && t.column_key !== taskColumn) return false
    if (onlyMine && !t.assignees.some((a) => a.user_id === me.id)) return false
    return true
  })

  useEffect(()=>{
    let active=true
    if(sourceId == null) {setTargetTasks([]);setTargetUsers([]);setCascade(null);setPreviewBusy(false);return}
    setPreviewBusy(true)
    api.incidentImpact(sourceId,depth).then(result=>{
      if(active){setTargetTasks(result.task_ids);setTargetUsers(result.user_ids);setError('')}
    }).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setPreviewBusy(false)})
    return ()=>{active=false}
  },[sourceId,depth])

  useEffect(()=>{
    let active=true
    setCascade(null)
    if(sourceId!==null)api.incidentCascade(sourceId).then(result=>{if(active)setCascade(result)}).catch(e=>{if(active)setError(e.message)})
    return ()=>{active=false}
  },[sourceId,tasks])

  async function submit() {
    if (!title.trim()) return
    setError('')
    setBusy(true)
    try {
      const targets = [
        ...targetTasks.map((id) => ({ target_type: 'task', target_id: id })),
        ...targetUsers.map((id) => ({ target_type: 'user', target_id: id })),
        ...targetModules.map((id) => ({ target_type: 'module', target_id: id })),
      ]
      await api.createIncident({
        level, title: title.trim(), description: description || null,
        impact: impact || null, urgency, owner_id: ownerId, targets,
        source_task_id:sourceId,cascade_depth:depth,
      })
      onCreated()
    } catch (e) {
      setError((e as Error).message)
    } finally {setBusy(false)}
  }

  return (
    <Modal title="Новый инцидент" onClose={onClose}>
      <Field label="Сигнал">
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="yellow">Жёлтый — локальный блокер</option>
          <option value="red">Красный — запрос эскалации</option>
        </select>
      </Field>
      <Field label="Заголовок *">
        <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
      </Field>
      <Field label="Описание">
        <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Область влияния">
        <textarea rows={2} value={impact} onChange={(e) => setImpact(e.target.value)} />
      </Field>
      <div className="row">
        <Field label="Срочность">
          <select value={urgency} onChange={(e) => setUrgency(e.target.value)}>
            {['low', 'medium', 'high', 'critical'].map((u) => <option key={u} value={u}>{PRIORITIES[u] ?? u}</option>)}
          </select>
        </Field>
        <Field label="Ответственный">
          <select value={ownerId ?? ''} onChange={(e) => setOwnerId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Автор инцидента</option>
            {participants.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Исходная задача">
        <div className="row source-filters">
          <select aria-label="Исполнитель исходной задачи" value={sourceAssignee} onChange={e=>setSourceAssignee(e.target.value)}>
            <option value="">Все исполнители</option><option value="mine">Назначенные мне</option><option value="none">Без исполнителя</option>
            {participants.filter(p=>p.id!==me.id).map(p=><option key={p.id} value={p.id}>{p.display_name}</option>)}
          </select>
          <select aria-label="Тег исходной задачи" value={sourceTag} onChange={e=>setSourceTag(e.target.value)}><option value="">Все теги</option>{[...new Set(openTasks.flatMap(t=>t.tags??[]))].sort().map(tag=><option key={tag}>{tag}</option>)}</select>
          <select aria-label="Трек исходной задачи" value={sourceTrack} onChange={e=>setSourceTrack(e.target.value)}><option value="">Все треки</option><option value="none">Без трека</option>{modules.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select>
        </div>
        <select value={sourceId ?? ''} onChange={e=>setSourceId(e.target.value ? Number(e.target.value):null)}>
          <option value="">Выберите задачу для автоматического выбора</option>
          {openTasks.filter(t=>t.id===sourceId||matchesSource(t,sourceAssignee,sourceTag,sourceTrack,me.id)).map(t=><option key={t.id} value={t.id}>#{t.id} {t.title}</option>)}
        </select>
      </Field>
      <Field label="Глубина распространения">
        <input type="number" min="1" max="100" value={depth} onChange={e=>setDepth(Math.max(1,Math.min(100,Number(e.target.value)||1)))}/>
      </Field>
      <p className="muted">Изменение исходной задачи или глубины заново выбирает задачи и их исполнителей, заменяя ручные отметки. После расчёта отметки можно изменить вручную. Таймеры продолжают работать.</p>
      {previewBusy && <p role="status">Расчёт зависимых задач…</p>}
      {cascade&&<CascadeView cascade={cascade} depth={depth} tasks={tasks}/>}
      <Field label={`Затронутые задачи (выбрано: ${targetTasks.length})`}>
        <div className="row" style={{ marginBottom: 6 }}>
          <input placeholder="Поиск по названию…" value={taskSearch} onChange={(e) => setTaskSearch(e.target.value)} />
          <select value={taskColumn} onChange={(e) => setTaskColumn(e.target.value)}>
            <option value="">Все колонки</option>
            {[...new Set(openTasks.map(t=>t.column_key))].map(k=><option key={k} value={k}>{openTasks.find(t=>t.column_key===k)?.column_title ?? 'Колонка'}</option>)}
          </select>
          <label className="row" style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
            <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
            <span style={{ fontSize: 13 }}>мои</span>
          </label>
        </div>
        <div className="check-list" style={{ maxHeight: 160, overflowY: 'auto' }}>
          {filteredTasks.map((t) => (
            <label key={t.id}>
              <input type="checkbox" checked={targetTasks.includes(t.id)} onChange={(e) => setTargetTasks((prev) => (e.target.checked ? [...prev, t.id] : prev.filter((x) => x !== t.id)))} />
              <span>{t.title}</span>
              <span className="muted" style={{ fontSize: 11 }}>{t.column_title ?? 'Колонка'}</span>
            </label>
          ))}
          {filteredTasks.length === 0 && <div className="muted" style={{ fontSize: 12, padding: 4 }}>Нет задач</div>}
        </div>
      </Field>
      <Field label="Затронутые участники">
        <div className="check-list">
          {participants.map((p) => (
            <label key={p.id}>
              <input type="checkbox" checked={targetUsers.includes(p.id)} onChange={(e) => setTargetUsers((prev) => (e.target.checked ? [...prev, p.id] : prev.filter((x) => x !== p.id)))} />
              <span>{p.display_name}</span>
              <span className="muted" style={{ fontSize: 12 }}>{p.login}</span>
            </label>
          ))}
        </div>
      </Field>
      <Field label="Затронутые треки">
        <div className="check-list">
          {modules.map((m) => (
            <label key={m.id}>
              <input type="checkbox" checked={targetModules.includes(m.id)} onChange={(e) => setTargetModules((prev) => (e.target.checked ? [...prev, m.id] : prev.filter((x) => x !== m.id)))} />
              <span>{m.name}</span>
              <span />
            </label>
          ))}
        </div>
      </Field>
      {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button onClick={onClose}>Отмена</button>
        <button className="primary" disabled={busy || previewBusy || !title.trim()} onClick={submit}>{busy ? 'Создание…' : 'Создать'}</button>
      </div>
    </Modal>
  )
}

function IncidentPanel({
  incident, names, taskNames, moduleNames, tasks, onChanged, onClose,
}: {
  incident: Incident
  names: Map<number, string>
  taskNames: Map<number, string>
  moduleNames: Map<number, string>
  tasks:Task[]
  onChanged: () => void
  onClose: () => void
}) {
  const [comment, setComment] = useState('')
  const [resolution, setResolution] = useState('')
  const [error, setError] = useState('')

  async function run(fn: () => Promise<unknown>) {
    setError('')
    try {
      await fn()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const targetName = (t: { target_type: string; target_id: number }) => {
    if (t.target_type === 'task') return taskNames.get(t.target_id) ?? `#${t.target_id}`
    if (t.target_type === 'user') return names.get(t.target_id) ?? `#${t.target_id}`
    return moduleNames.get(t.target_id) ?? `#${t.target_id}`
  }

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0 }}>#{incident.number} {incident.title}</h3>
        <button className="ghost small" onClick={onClose}>✕</button>
      </div>
      <div className="row" style={{ margin: '8px 0' }}>
        <Badge kind={incidentKind(incident)}>{incident.level === 'red' ? 'Красный' : 'Жёлтый'}</Badge>
        <Badge kind={incidentKind(incident)}>{incidentLabel(incident)}</Badge>
        <span className="muted" style={{ fontSize: 12 }}>создан {fmtDate(incident.created_at)}</span>
      </div>

      {error && <div className="error" style={{ margin: '8px 0' }}>{error}</div>}

      <div className="section">
        <div className="section-title">Детали</div>
        <div className="grid" style={{ gap: 4, fontSize: 13 }}>
          {incident.description && <div><b className="muted">Описание:</b> {incident.description}</div>}
          {incident.impact && <div><b className="muted">Влияние:</b> {incident.impact}</div>}
          <div><b className="muted">Срочность:</b> {PRIORITIES[incident.urgency ?? ''] ?? '—'}</div>
          <div><b className="muted">Автор:</b> {names.get(incident.author_id) ?? `#${incident.author_id}`}</div>
          <div><b className="muted">Ответственный:</b> {incident.owner_id != null ? (names.get(incident.owner_id) ?? `#${incident.owner_id}`) : '—'}</div>
          {incident.resolution && <div><b className="muted">Решение:</b> {incident.resolution}</div>}
        </div>
      </div>

      {incident.targets.length > 0 && (
        <div className="section">
          <div className="section-title">Затронутое</div>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {incident.targets.map((t, i) => (
              <span key={i} className="badge gray">{{task:'Задача',user:'Участник',module:'Трек'}[t.target_type] ?? 'Объект'}: {targetName(t)}</span>
            ))}
          </div>
        </div>
      )}

      {incident.cascade&&<CascadeView cascade={incident.cascade} depth={incident.cascade_depth??1} tasks={tasks}/>}
      <div className="section">
        <div className="section-title">Действия</div>
        {incident.level === 'red' && incident.status === 'open' && (
          <div className="row">
            <button className="primary small" onClick={() => run(() => api.confirmRed(incident.id, true))}>Подтвердить (глобальная)</button>
            <button className="small" onClick={() => run(() => api.confirmRed(incident.id, false, 'Отклонено капитаном'))}>Отклонить эскалацию</button>
          </div>
        )}
        {incident.status !== 'resolved' && (
          <div className="row" style={{ marginTop: 8 }}>
            <input placeholder="Итог решения…" value={resolution} onChange={(e) => setResolution(e.target.value)} />
            <button
              className="small"
              disabled={!resolution.trim()}
              onClick={() => run(() => api.resolveIncident(incident.id, resolution.trim()))}
            >
              Закрыть
            </button>
          </div>
        )}
      </div>

      <div className="section">
        <div className="section-title">Журнал</div>
        <div className="grid" style={{ gap: 6 }}>
          {incident.events.map((ev) => (
            <div key={ev.id} style={{ fontSize: 13, borderLeft: '2px solid var(--border)', paddingLeft: 8 }}>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                <b>{{created:'Создал инцидент',confirmed:'Подтвердил эскалацию',rejected:'Отклонил эскалацию',resolved:'Закрыл инцидент',comment:'Добавил комментарий',owner_reassigned:'Передал ответственность после удаления аккаунта'}[ev.event_type] ?? 'Изменение инцидента'}</b>
                {ev.actor_id != null && (
                  <span style={{ color: 'var(--accent)', fontSize: 12 }}>
                    {names.get(ev.actor_id) ?? `#${ev.actor_id}`}
                  </span>
                )}
                <span className="muted" style={{ fontSize: 11 }}>{fmtDate(ev.created_at)}</span>
              </div>
              {typeof ev.data.text === 'string' && <div>{ev.data.text}</div>}
              {typeof ev.data.resolution === 'string' && <div>{ev.data.resolution}</div>}
              {typeof ev.data.comment === 'string' && ev.data.comment && <div>{ev.data.comment}</div>}
            </div>
          ))}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <input placeholder="Комментарий…" value={comment} onChange={(e) => setComment(e.target.value)} />
          <button
            className="small"
            disabled={!comment.trim()}
            onClick={async () => {
              await run(() => api.commentIncident(incident.id, comment.trim()))
              setComment('')
            }}
          >
            →
          </button>
        </div>
      </div>
    </div>
  )
}

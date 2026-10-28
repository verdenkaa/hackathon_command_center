import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {useProjectUpdates} from './realtime'
import {taskTone,TONE_LABELS,IncidentMark} from './taskVisuals'
import { api, Column, DashboardKpi, Incident, Me, Module, Participant, Task } from './api'
import { Badge, Field, Modal, badgeForStatus, fmt, fmtDate, hmToSeconds, parseUTC, secondsToHm, useLoad, PRIORITIES, toMoscowInput, fromMoscowInput, incidentKind, incidentLabel } from './ui'

const PRIORITY_COLOR: Record<string, string> = {
  low: '#63a7f5',
  medium: '#9aaabd',
  high: '#f5c451',
  critical: '#f06464',
}

export const LINK_LABELS: Record<string, string> = {
  blocked_by: 'заблокирована',
  after: 'после',
  before: 'до',
}

const DONE_KEYS = ['done', 'realised']
const semantic = (t:Task) => t.column_semantic ?? (DONE_KEYS.includes(t.column_key) ? 'done' : t.column_key==='trashed' ? 'trash' : 'normal')

export function unfinishedBlockers(task: Task, tasks: Task[]): Task[] {
  return task.predecessors
    .filter((p) => p.link_type === 'blocked_by')
    .map((p) => tasks.find((t) => t.id === p.task_id))
    .filter((t): t is Task => !!t && !['done','trash'].includes(semantic(t)))
}

export default function Board({ me, openTaskId, onOpenIncident }: { me: Me; openTaskId?:number|null; onOpenIncident?:(id:number)=>void }) {
  const [columns, setColumns] = useState<Column[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [dash, setDash] = useState<DashboardKpi | null>(null)
  const [participants] = useLoad<Participant[]>(api.participants)
  const [modules] = useLoad<Module[]>(api.modules)
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [filterUser, setFilterUser] = useState<number | null>(null)
  const [filterTag, setFilterTag] = useState('')
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(openTaskId ?? null)
  const [draggingId, setDraggingId] = useState<number | null>(null)
  const draggedTask=useRef<Task|null>(null)
  const reloadSequence=useRef(0)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    const sequence=++reloadSequence.current
    const [c, t, d, i] = await Promise.all([api.columns(), api.tasks(), api.dashboard(), api.incidents()])
    if(sequence!==reloadSequence.current)return
    setColumns(c)
    setTasks(t)
    setDash(d)
    setIncidents(i)
  }, [])
  useProjectUpdates(()=>{reload().catch(e=>setError(e.message))})

  useEffect(() => {
    reload().catch((e) => setError(e.message))
  }, [reload])

  useEffect(() => {
    const id = setInterval(() => {reload().catch(()=>{})}, 30000)
    return () => clearInterval(id)
  }, [])

  const filtered = useMemo(() => {
    return tasks.filter((t) => {
      if (filterUser !== null && !t.assignees.some((a) => a.user_id === filterUser)) return false
      if (filterTag && !(t.tags ?? []).includes(filterTag)) return false
      if (search && !t.title.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [tasks, filterUser, filterTag, search])

  const { blockedIds, affectedIds } = useMemo(() => {
    const blocked = new Set<number>()
    for (const i of incidents ?? []) {
      if (i.status === 'resolved') continue
      for (const t of i.targets) {
        if (t.target_type === 'task') blocked.add(t.target_id)
      }
    }
    const affected = new Set<number>()
    return { blockedIds: blocked, affectedIds: affected }
  }, [incidents, tasks])

  const selected = tasks.find((t) => t.id === selectedId) ?? null

  async function handleDrop(columnKey: string) {
    if (draggingId == null) return
    const task = draggedTask.current
    if (!task || task.column_key === columnKey) return
    try {
      await api.moveTask(task.id, columnKey, task.version)
      reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDraggingId(null)
    }
  }

  return (
    <div>
      <div className="row" style={{ flexWrap: 'wrap', margin: '4px 0 12px' }}>
        <Kpi label="Прогресс" value={`${dash?.progress_percent ?? 0}%`} />
        <Kpi label="В работе" value={dash?.in_progress_tasks ?? 0} />
        <Kpi label="Завершено" value={dash?.completed_tasks ?? 0} />
        <Kpi label="Просрочено" value={dash?.overdue_tasks ?? 0} warn={(dash?.overdue_tasks ?? 0) > 0} />
        <Kpi label="Активные таймеры" value={dash?.active_timers ?? 0} />
        <Kpi label="Суммарное время задач" value={fmt(dash?.actual_seconds ?? 0)} />
        <Kpi label="Время в работе" value={fmt(dash?.calendar_seconds ?? 0)} />
        <div className="grow" />
        <button className="primary" onClick={() => setCreateOpen(true)}>+ Задача</button>
      </div>

      {/* Фильтры */}
      <div className="row" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        <div className="avatar-row">
          <div
            className={`avatar ${filterUser === null ? 'active' : ''}`}
            title="Все"
            onClick={() => setFilterUser(null)}
          >
            Все
          </div>
          {participants?.map((p) => (
            <div
              key={p.id}
              className={`avatar ${filterUser === p.id ? 'active' : ''}`}
              title={p.display_name}
              onClick={() => setFilterUser(filterUser === p.id ? null : p.id)}
            >
              {p.display_name.slice(0, 1).toUpperCase()}
            </div>
          ))}
        </div>
        <input placeholder="Поиск…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ maxWidth: 180 }} />
        <input placeholder="Тег…" value={filterTag} onChange={(e) => setFilterTag(e.target.value)} style={{ maxWidth: 120 }} />
        {filterTag && <button className="small ghost" onClick={() => setFilterTag('')}>✕</button>}
      </div>

      {error && <div className="error" style={{ margin: '8px 0' }}>{error}</div>}

      <div className="board">
        {columns.map((col) => {
          const colTasks = filtered.filter((t) => t.column_id === col.id)
          return (
            <div
              key={col.id}
              className="board-col"
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => handleDrop(col.key)}
            >
              <h4>{col.title} <span className="muted">({colTasks.length})</span></h4>
              {colTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  tasks={tasks}
                  columns={columns}
                  dragging={draggingId === task.id}
                  blocked={blockedIds.has(task.id)}
                  affected={affectedIds.has(task.id)}
                  onOpen={() => setSelectedId(task.id)}
                  onDragStart={() => {draggedTask.current=task;setDraggingId(task.id)}}
                  onDragEnd={() => {draggedTask.current=null;setDraggingId(null)}}
                  onTimer={async (action) => {
                    try {
                      await api.timer(task.id, action)
                      reload()
                    } catch (e) {
                      setError((e as Error).message)
                    }
                  }}
                  onMove={async (key) => {
                    try {
                      await api.moveTask(task.id, key, task.version)
                      reload()
                    } catch (e) {
                      setError((e as Error).message)
                    }
                  }}
                />
              ))}
              {colTasks.length === 0 && <div className="muted" style={{ fontSize: 12, padding: 4 }}>—</div>}
            </div>
          )
        })}
      </div>

      {createOpen && (
        <TaskForm
          columns={columns}
          onClose={() => setCreateOpen(false)}
          onCreated={async () => {
            setCreateOpen(false)
            reload()
          }}
        />
      )}

      {selected && (
        <>
          <div className="side-backdrop" onClick={() => setSelectedId(null)} />
          <div className="side-panel">
            <TaskPanel
              onOpenIncident={onOpenIncident}
              key={selected.id}
              task={selected}
              tasks={tasks}
              participants={participants ?? []}
              modules={modules ?? []}
              columns={columns}
              isCaptain={me.roles.some((r) => r.role === 'admin' || (r.role === 'captain' && r.project_id === selected.project_id))}
              onChange={async () => {
                reload()
              }}
              onClose={() => setSelectedId(null)}
            />
          </div>
        </>
      )}
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

export function TaskCard({ task, tasks=[task], columns, dragging, blocked, affected, onOpen, onMove, onTimer, onDragStart, onDragEnd }: {
  task: Task
  tasks?: Task[]
  columns: Column[]
  dragging: boolean
  blocked: boolean
  affected: boolean
  onOpen: () => void
  onMove: (key: string) => void
  onTimer: (action: 'start' | 'pause' | 'stop') => void
  onDragStart: () => void
  onDragEnd: () => void
}) {
  const running = task.timer?.state === 'running'
  const blockers=task.blocking_incidents ?? []
  const blockKind=blockers.some(i=>incidentKind(i)==='red')?'red':blockers.some(i=>incidentKind(i)==='purple')?'purple':'yellow'
  const overdue =
    task.deadline != null &&
    parseUTC(task.deadline) < new Date() &&
    !['done','trash'].includes(semantic(task))
  return (
    <div
      className={`task-card tone-${taskTone(task,tasks)}`}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      style={{ opacity: dragging ? 0.5 : 1 }}
    >
      <div className="task-title" style={{ fontWeight: 500, fontSize: 13 }}>{task.title}<IncidentMark incidents={blockers}/></div>
      <small className="task-readiness">{TONE_LABELS[taskTone(task,tasks)]}</small>
      <div className="row" style={{ marginTop: 6, fontSize: 12, flexWrap: 'wrap' }}>
        {blocked && <span className={`badge ${blockKind}`}>заблокирована{blockKind==='purple'?' · Ожидает подтверждения':''}</span>}
        {affected && <span className="badge yellow">затронута</span>}
        {overdue && <span className="badge red">просрочена</span>}
        <span style={{ color: PRIORITY_COLOR[task.priority] ?? 'var(--muted)' }}>{PRIORITIES[task.priority] ?? task.priority}</span>
        {task.tags?.map((t) => <span key={t} className="badge blue">{t}</span>)}
      </div>
      <div className="row" style={{ marginTop: 6, fontSize: 12, flexWrap: 'wrap' }}>
        {task.assignees.map((a) => (
          <span key={a.user_id} className="avatar" style={{ width: 22, height: 22, fontSize: 10, cursor: 'default' }}>
            {a.display_name.slice(0, 1).toUpperCase()}
          </span>
        ))}
        <span className="grow" />
        <span
          className="row"
          style={{ gap: 4 }}
          onClick={(e) => e.stopPropagation()}
        >
          {!running && (
            <button className="small" title="Запустить таймер" onClick={() => onTimer('start')}>▶</button>
          )}
          {running && (
            <>
              <button className="small" title="Пауза" onClick={() => onTimer('pause')}>⏸</button>
              <button className="small" title="Стоп" onClick={() => onTimer('stop')}>⏹</button>
            </>
          )}
          {task.timer && (
            <span className="mono" style={{ fontSize: 11, color: running ? 'var(--ok)' : 'var(--muted)' }}>
              {fmt(task.timer.total_seconds)}
            </span>
          )}
        </span>
      </div>
      <select
        value={task.column_key}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onMove(e.target.value)}
        style={{ marginTop: 6, fontSize: 11, padding: '2px 4px', width: '100%' }}
      >
        {columns.map((col) => (
          <option key={col.key} value={col.key}>{col.title}</option>
        ))}
      </select>
    </div>
  )
}

export function TaskForm({ columns, onClose, onCreated }: { columns: Column[]; onClose: () => void; onCreated: (taskId:number) => void }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('medium')
  const [moduleId, setModuleId] = useState<number | null>(null)
  const [estimateHm, setEstimateHm] = useState('')
  const [deadline, setDeadline] = useState('')
  const [tags, setTags] = useState('')
  const [columnKey, setColumnKey] = useState(columns.find(c => c.semantic !== 'trash' && c.semantic !== 'done')?.key ?? columns[0]?.key ?? '')
  const [assignees, setAssignees] = useState<Record<number, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [participants] = useLoad<Participant[]>(api.participants)
  const [modules] = useLoad<Module[]>(api.modules)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    setBusy(true)
    setError('')
    try {
      if (estimateHm.trim() && hmToSeconds(estimateHm) == null) throw new Error('Введите оценку в формате ч:мм, например 1:30')
      const assigneeList = Object.entries(assignees)
        .filter(([, v]) => v)
        .map(([uid], i) => ({ user_id: Number(uid), is_primary: i === 0 }))
      const created = await api.createTask({
        title: title.trim(),
        description: description || null,
        priority,
        module_id: moduleId,
        estimate_seconds: hmToSeconds(estimateHm),
        deadline: fromMoscowInput(deadline),
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        column_key: columnKey,
      })
      if (assigneeList.length > 0) {
        await api.setAssignees(created.id, assigneeList)
      }
      onCreated(created.id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Новая задача" onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Название *">
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
        </Field>
        <Field label="Описание">
          <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="row">
          <Field label="Приоритет">
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              {['low', 'medium', 'high', 'critical'].map((p) => (
                <option key={p} value={p}>{PRIORITIES[p] ?? p}</option>
              ))}
            </select>
          </Field>
          <Field label="Колонка">
            <select value={columnKey} onChange={(e) => setColumnKey(e.target.value)}>
              {columns.map((col) => <option key={col.key} value={col.key}>{col.title}</option>)}
            </select>
          </Field>
          <Field label="Трек">
            <select value={moduleId ?? ''} onChange={(e) => setModuleId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">—</option>
              {modules?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </Field>
        </div>
        <div className="row">
          <Field label="Оценка (ч:мм)">
            <input placeholder="1:30" value={estimateHm} onChange={(e) => setEstimateHm(e.target.value)} />
          </Field>
          <Field label="Срок (МСК)">
            <input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
          </Field>
          <Field label="Теги (через запятую)">
            <input value={tags} onChange={(e) => setTags(e.target.value)} />
          </Field>
        </div>
        <Field label="Исполнители (первый — основной)">
          <div className="check-list">
            {participants?.map((p) => (
              <label key={p.id}>
                <input
                  type="checkbox"
                  checked={!!assignees[p.id]}
                  onChange={(e) => setAssignees((prev) => ({ ...prev, [p.id]: e.target.checked }))}
                />
                <span>{p.display_name}</span>
                <span className="muted" style={{ fontSize: 12 }}>{p.login}</span>
              </label>
            ))}
          </div>
        </Field>
        {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose}>Отмена</button>
          <button className="primary" type="submit" disabled={busy}>{busy ? 'Создание…' : 'Создать'}</button>
        </div>
      </form>
    </Modal>
  )
}

export function TaskPanel({
  task, tasks, participants, modules, columns, isCaptain, onChange, onClose, onOpenIncident, readOnly=false, allowBlockingLinks=true,
}: {
  onOpenIncident?: (id:number)=>void
  readOnly?: boolean
  allowBlockingLinks?: boolean
  task: Task
  tasks: Task[]
  participants: Participant[]
  modules: Module[]
  columns: Column[]
  isCaptain: boolean
  onChange: () => void
  onClose: () => void
}) {
  const [desc, setDesc] = useState(task.description ?? '')
  const [title, setTitle] = useState(task.title)
  const [estimate, setEstimate] = useState(task.estimate_seconds == null ? '' : `${Math.floor(task.estimate_seconds/3600)}:${String(Math.floor(task.estimate_seconds%3600/60)).padStart(2,'0')}`)
  const [deadline, setDeadline] = useState(toMoscowInput(task.deadline))
  const [tags, setTags] = useState(task.tags.join(', '))
  const [saved, setSaved] = useState('')
  const [historyTick, setHistoryTick] = useState(0)
  const [checkText, setCheckText] = useState('')
  const [depId, setDepId] = useState<number | null>(null)
  const [depType, setDepType] = useState(allowBlockingLinks?'blocked_by':'after')
  const [removeLink,setRemoveLink]=useState<{owner:number;predecessor:number;title:string}|null>(null)
  const [subTitle, setSubTitle] = useState('')
  const [adjustH, setAdjustH] = useState('')
  const [error, setError] = useState('')
  const [history] = useLoad<{ text:string; action: string; actor_id: number | null; data: Record<string, unknown>; created_at: string }[]>(
    () => api.taskHistory(task.id),
    [task.id, historyTick],
  )
  const running = task.timer?.state === 'running'
  const subtasks = tasks.filter((t) => t.parent_id === task.id)
  const predecessors = task.predecessors
    .map((p) => ({ pred: tasks.find((t) => t.id === p.task_id), linkType: p.link_type }))
    .filter((x): x is { pred: Task; linkType: string } => x.pred != null)
  // Обратные связи: задачи, которые зависят от этой (показываются автоматически).
  const reverseLinks = tasks
    .map((t) => {
      const link = t.predecessors.find((p) => p.task_id === task.id)
      return link ? { dep: t, linkType: link.link_type } : null
    })
    .filter((x): x is { dep: Task; linkType: string } => x != null)

const REVERSE_LABELS: Record<string, string> = {
  blocked_by: 'блокирует',
  after: 'до',
  before: 'после',
}

  async function run(fn: () => Promise<unknown>) {
    if(readOnly)return
    setError('')
    try {
      await fn()
      setSaved('Сохранено')
      setHistoryTick(v=>v+1)
      onChange()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function saveDescription() {
    await run(() => api.patchTask(task.id, { description: desc }, task.version))
  }

  async function setAssignees(list: number[]) {
    await run(() =>
      api.setAssignees(task.id, list.map((uid, i) => ({ user_id: uid, is_primary: i === 0 }))),
    )
  }

  return (
    <div className="shared-task-panel">
      <button className="ghost small" style={{float:'right'}} onClick={onClose}>Закрыть</button>
      <fieldset disabled={readOnly} style={{border:0,padding:0,margin:0,minWidth:0}}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={async () => {
            if (title.trim() && title.trim() !== task.title) {
              await run(() => api.patchTask(task.id, { title: title.trim() }, task.version))
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          }}
          style={{ fontWeight: 600, fontSize: 16, padding: '4px 8px' }}
        />
        {!readOnly && <button className="ghost small" onClick={onClose}>✕</button>}
      </div>
      <div className="row" style={{ margin: '8px 0', flexWrap: 'wrap' }}>
        <Badge kind={badgeForStatus(semantic(task) === 'done' ? 'done' : 'open')}>
          {columns.find(c=>c.id === task.column_id)?.title ?? 'Колонка'}
        </Badge>
        <span className="muted" style={{ fontSize: 12 }}>приоритет {PRIORITIES[task.priority] ?? task.priority}</span>
        {task.deadline && <span className="muted" style={{ fontSize: 12 }}>до {fmtDate(task.deadline)}</span>}
      </div>

      {error && <div className="error" role="alert" style={{ margin: '8px 0' }}>{error}</div>}
      {saved && <div role="status" className="muted">{saved}</div>}
      {(task.blocking_incidents ?? []).map(i => <div key={i.id} className="card" style={{marginTop:8,borderColor:incidentKind(i)==='purple'?'#a478e5':incidentKind(i)==='red'?'var(--error)':'var(--warn)'}}>
        <Badge kind={incidentKind(i)}>{incidentLabel(i)}</Badge> {i.level === 'red' ? 'Красный' : 'Жёлтый'} инцидент
        <button className="ghost" onClick={()=>onOpenIncident?.(i.id)}>#{i.number} {i.title}</button>
      </div>)}

      <div className="section">
        <div className="section-title">Статус и свойства</div>
        <div className="row">
          <select
            value={task.column_key}
            onChange={(e) => {
              run(() => api.moveTask(task.id, e.target.value, task.version))
            }}
          >
            {columns.map((c) => <option key={c.id} value={c.key}>{c.title}</option>)}
          </select>
          <select value={task.priority} onChange={(e) => run(() => api.patchTask(task.id, { priority: e.target.value }, task.version))}>
            {['low', 'medium', 'high', 'critical'].map((p) => <option key={p} value={p}>{PRIORITIES[p] ?? p}</option>)}
          </select>
          <select
            value={task.module_id ?? ''}
            onChange={(e) => run(() => api.patchTask(task.id, { module_id: e.target.value ? Number(e.target.value) : null }, task.version))}
          >
            <option value="">без трека</option>
            {modules.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </div>
      </div>

      <div className="section">
        <div className="section-title">Описание</div>
        <textarea rows={5} value={desc} onChange={(e) => setDesc(e.target.value)} />
        {desc !== (task.description ?? '') && (
          <button className="primary small" style={{ marginTop: 6 }} onClick={saveDescription}>Сохранить описание</button>
        )}
      </div>

      <div className="section">
        <div className="section-title">Исполнители</div>
        <Field label="Основной исполнитель">
          <select value={task.assignees.find(a=>a.is_primary)?.user_id ?? ''} disabled={!task.assignees.length}
            onChange={e=>setAssignees([Number(e.target.value), ...task.assignees.filter(a=>a.user_id!==Number(e.target.value)).map(a=>a.user_id)])}>
            {!task.assignees.length && <option value="">Сначала выберите исполнителей</option>}
            {task.assignees.map(a=><option key={a.user_id} value={a.user_id}>{a.display_name}</option>)}
          </select>
        </Field>
        <div className="check-list">
          {participants.map((p) => {
            const checked = task.assignees.some((a) => a.user_id === p.id)
            const isPrimary = task.assignees.some((a) => a.user_id === p.id && a.is_primary)
            return (
              <label key={p.id}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => {
                    const cur = task.assignees.filter((a) => a.user_id !== p.id).map((a) => a.user_id)
                    const next = e.target.checked ? [p.id, ...cur] : cur
                    setAssignees(next)
                  }}
                />
                <span>{p.display_name}</span>
                {isPrimary ? <span className="badge blue">основной</span> : <span />}
              </label>
            )
          })}
        </div>
      </div>

      <div className="section">
        <div className="section-title">Время</div>
        <Field label="Плановая оценка (ч:мм)">
          <div className="row">
            <input aria-label="Плановая оценка" placeholder="1:30" value={estimate} onChange={e=>setEstimate(e.target.value)}/>
            <button onClick={()=>run(async()=>{
              const value=hmToSeconds(estimate)
              if (estimate.trim() && value == null) throw new Error('Введите оценку в формате ч:мм, например 1:30')
              await api.patchTask(task.id,{estimate_seconds:value},task.version)
            })}>Сохранить оценку</button>
          </div>
        </Field>
        <Field label="Срок (МСК)">
          <div className="row">
            <input type="datetime-local" value={deadline} onChange={e=>setDeadline(e.target.value)}/>
            <button onClick={()=>run(()=>api.patchTask(task.id,{deadline:fromMoscowInput(deadline)},task.version))}>Сохранить срок</button>
          </div>
        </Field>
        <Field label="Теги (через запятую)">
          <div className="row">
            <input value={tags} onChange={e=>setTags(e.target.value)}/>
            <button onClick={()=>run(()=>api.patchTask(task.id,{tags:tags.split(',').map(t=>t.trim()).filter(Boolean)},task.version))}>Сохранить теги</button>
          </div>
        </Field>
        <div className="row">
          {!running && <button className="primary small" onClick={() => run(() => api.timer(task.id, 'start'))}>▶ Старт</button>}
          {running && (
            <>
              <button className="small" onClick={() => run(() => api.timer(task.id, 'pause'))}>⏸ Пауза</button>
              <button className="small danger" onClick={() => run(() => api.timer(task.id, 'stop'))}>⏹ Стоп</button>
            </>
          )}
          <span className="mono" style={{ color: running ? 'var(--ok)' : undefined }}>
            {fmt(task.timer?.total_seconds ?? 0)}
          </span>
          {task.estimate_seconds != null && (
            <span className="muted" style={{ fontSize: 12 }}>
              план {secondsToHm(task.estimate_seconds)}
            </span>
          )}
        </div>
        {isCaptain && (
          <div className="row" style={{ marginTop: 6 }}>
            <input
              type="number"
              min="0"
              step="0.5"
              aria-label="Фактическое время, часов" placeholder="Фактическое время, часов"
              value={adjustH}
              onChange={(e) => setAdjustH(e.target.value)}
              style={{ width:'100%', minWidth:0 }}
            />
            <button
              className="small"
              disabled={adjustH === ''}
              onClick={async () => {
                await run(() => api.timeAdjust(task.id, Math.round(parseFloat(adjustH) * 3600)))
                setAdjustH('')
              }}
            >
              Задать
            </button>
          </div>
        )}
      </div>

      <div className="section">
        <div className="section-title">Чек-лист</div>
        {task.checklist.map((c) => (
          <label key={c.id} className="row" style={{ padding: '2px 0' }}>
            <input type="checkbox" checked={c.done} onChange={() => run(() => api.checklistPatch(c.id, !c.done))} />
            <span style={{ textDecoration: c.done ? 'line-through' : undefined }}>{c.text}</span>
            <span className="grow" />
            <button className="small ghost" onClick={() => run(() => api.checklistDelete(c.id))}>✕</button>
          </label>
        ))}
        <div className="row" style={{ marginTop: 6 }}>
          <input placeholder="Новый пункт…" value={checkText} onChange={(e) => setCheckText(e.target.value)} />
          <button
            className="small"
            onClick={async () => {
              if (!checkText.trim()) return
              await run(() => api.checklistAdd(task.id, checkText.trim()))
              setCheckText('')
            }}
          >
            +
          </button>
        </div>
      </div>

      <div className="section">
        <div className="section-title">Связи задач</div>
        {predecessors.map((p) => (
          <div key={p.pred.id} className="row" style={{ padding: '2px 0' }}>
            <span className="badge blue">{LINK_LABELS[p.linkType] ?? p.linkType}</span>
            <span>{p.pred.title}</span>
            <Badge kind={semantic(p.pred)==='done' ? 'green' : 'yellow'}>
              {p.pred.column_semantic === 'trash' ? 'в корзине' : p.pred.column_semantic === 'done' ? 'готово' : 'не завершено'}
            </Badge>
            <span className="grow" />
            <button className="small ghost" aria-label={`Удалить связь с ${p.pred.title}`} onClick={() => setRemoveLink({owner:task.id,predecessor:p.pred.id,title:p.pred.title})}>✕</button>
          </div>
        ))}
        {predecessors.length === 0 && reverseLinks.length === 0 && (
          <div className="muted" style={{ fontSize: 12 }}>Связей нет</div>
        )}
        {reverseLinks.map((r) => (
          <div key={r.dep.id} className="row" style={{ padding: '2px 0' }}>
            <span className="badge gray">{REVERSE_LABELS[r.linkType] ?? r.linkType}</span>
            <span className="muted">{r.dep.title}</span>
            <Badge kind={semantic(r.dep)==='done' ? 'green' : 'yellow'}>
              {semantic(r.dep)==='done' ? 'готово' : 'не завершено'}
            </Badge>
            <button className="small ghost" aria-label={`Удалить связь с ${r.dep.title}`} onClick={() => setRemoveLink({owner:r.dep.id,predecessor:task.id,title:r.dep.title})}>✕</button>
          </div>
        ))}
        <div className="row" style={{ marginTop: 6 }}>
          <select value={depType} onChange={(e) => setDepType(e.target.value)} style={{ maxWidth: 170 }}>
            {allowBlockingLinks&&<option value="blocked_by">заблокирована (blocked by)</option>}
            <option value="after">после</option>
            <option value="before">до</option>
          </select>
          <select value={depId ?? ''} onChange={(e) => setDepId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">+ задача…</option>
            {tasks.filter((t) => t.project_id === task.project_id && t.column_semantic !== 'trash' && t.id !== task.id && !task.predecessors.some((x) => x.task_id === t.id)).map((t) => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </select>
          <button
            className="small"
            disabled={depId == null}
            onClick={async () => {
              if (depId != null) {
                await run(() => api.addDependency(task.id, depId, depType))
                setDepId(null)
              }
            }}
          >
            +
          </button>
        </div>
      </div>

      <div className="section">
        <div className="section-title">Подзадачи</div>
        <Field label="Родительская задача">
          <select value={task.parent_id ?? ''} onChange={e=>run(()=>api.patchTask(task.id,{parent_id:e.target.value?Number(e.target.value):null},task.version))}>
            <option value="">Без родителя</option>
            {tasks.filter(t=>t.id!==task.id && t.project_id===task.project_id && semantic(t)!=='trash').map(t=><option key={t.id} value={t.id}>{t.title}</option>)}
          </select>
        </Field>
        {subtasks.map((s) => (
          <div key={s.id} className="row" style={{ padding: '2px 0' }}>
            <span>{s.title}</span>
            <Badge kind={semantic(s)==='done' ? 'green' : 'gray'}>{columns.find(c=>c.id===s.column_id)?.title ?? 'Колонка'}</Badge>
          </div>
        ))}
        <div className="row" style={{ marginTop: 6 }}>
          <input placeholder="Новая подзадача…" value={subTitle} onChange={(e) => setSubTitle(e.target.value)} />
          <button
            className="small"
            onClick={async () => {
              if (!subTitle.trim()) return
              await run(() => api.createTask({ title: subTitle.trim(), parent_id: task.id, column_key: columns.find(c=>c.semantic === 'normal')?.key ?? columns[0]?.key }))
              setSubTitle('')
            }}
          >
            +
          </button>
        </div>
      </div>

      </fieldset>
      {removeLink&&!readOnly&&<Modal title="Удалить связь?" onClose={()=>setRemoveLink(null)}><p>Удалить связь с «{removeLink.title}»?</p><div className="row"><button onClick={()=>setRemoveLink(null)}>Отмена</button><button className="primary" onClick={async()=>{await run(()=>api.removeDependency(removeLink.owner,removeLink.predecessor));setRemoveLink(null)}}>ОК</button></div></Modal>}
      <div className="section">
        <div className="section-title">История изменений</div>
        <div className="grid" style={{ gap: 6 }}>
          {(history ?? []).map((h, i) => (
            <div key={i} style={{ fontSize: 12, borderLeft: '2px solid var(--border)', paddingLeft: 8 }}>
              <div className="row">
                <span>{h.text ?? 'Изменение задачи'}</span>
                <span className="muted" style={{ fontSize: 11 }}>{fmtDate(h.created_at)}</span>
              </div>

            </div>
          ))}
          {(history ?? []).length === 0 && <div className="muted" style={{ fontSize: 12 }}>Изменений нет</div>}
        </div>
      </div>
    </div>
  )
}

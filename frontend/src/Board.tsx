import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, Column, DashboardKpi, Incident, Me, Module, Participant, Task } from './api'
import { Badge, Field, Modal, badgeForStatus, fmt, fmtDate, hmToSeconds, parseUTC, secondsToHm, useLoad } from './ui'

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

export function unfinishedBlockers(task: Task, tasks: Task[]): Task[] {
  return task.predecessors
    .filter((p) => p.link_type === 'blocked_by' || p.link_type === 'after')
    .map((p) => tasks.find((t) => t.id === p.task_id))
    .filter((t): t is Task => !!t && !DONE_KEYS.includes(t.column_key))
}

function warnIfBlocked(task: Task, tasks: Task[], columnKey: string): boolean {
  if (!['in_progress', 'testing', 'review'].includes(columnKey)) return true
  const blockers = unfinishedBlockers(task, tasks)
  if (blockers.length === 0) return true
  const titles = blockers.map((b) => `«${b.title}»`).join(', ')
  return window.confirm(
    `Перед этой задачей нужно выполнить: ${titles}.\nОни ещё не завершены. Приступить всё равно?`,
  )
}

export default function Board({ me }: { me: Me }) {
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
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draggingId, setDraggingId] = useState<number | null>(null)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    const [c, t, d, i] = await Promise.all([api.columns(), api.tasks(), api.dashboard(), api.incidents()])
    setColumns(c)
    setTasks(t)
    setDash(d)
    setIncidents(i)
    setError('')
  }, [])

  useEffect(() => {
    reload().catch((e) => setError(e.message))
  }, [reload])

  useEffect(() => {
    const id = setInterval(() => {
      Promise.all([api.tasks(), api.dashboard(), api.incidents()])
        .then(([t, d, i]) => {
          setTasks(t)
          setDash(d)
          setIncidents(i)
        })
        .catch(() => {})
    }, 1000)
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
    let changed = true
    while (changed) {
      changed = false
      for (const task of tasks) {
        if (blocked.has(task.id) || affected.has(task.id)) continue
        if (task.predecessors.some((p) => blocked.has(p.task_id) || affected.has(p.task_id))) {
          affected.add(task.id)
          changed = true
        }
      }
    }
    return { blockedIds: blocked, affectedIds: affected }
  }, [incidents, tasks])

  const selected = tasks.find((t) => t.id === selectedId) ?? null

  async function handleDrop(columnKey: string) {
    if (draggingId == null) return
    const task = tasks.find((t) => t.id === draggingId)
    if (!task || task.column_key === columnKey) return
    if (!warnIfBlocked(task, tasks, columnKey)) return
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
        <Kpi label="Факт / Календарь" value={`${fmt(dash?.actual_seconds ?? 0)} / ${fmt(dash?.calendar_seconds ?? 0)}`} />
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
                  columns={columns}
                  dragging={draggingId === task.id}
                  blocked={blockedIds.has(task.id)}
                  affected={affectedIds.has(task.id)}
                  onOpen={() => setSelectedId(task.id)}
                  onDragStart={() => setDraggingId(task.id)}
                  onDragEnd={() => setDraggingId(null)}
                  onTimer={async (action) => {
                    try {
                      await api.timer(task.id, action)
                      reload()
                    } catch (e) {
                      setError((e as Error).message)
                    }
                  }}
                  onMove={async (key) => {
                    if (!warnIfBlocked(task, tasks, key)) return
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

export function TaskCard({ task, columns, dragging, blocked, affected, onOpen, onMove, onTimer, onDragStart, onDragEnd }: {
  task: Task
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
  const overdue =
    task.deadline != null &&
    parseUTC(task.deadline) < new Date() &&
    !['done', 'realised', 'trashed'].includes(task.column_key)
  return (
    <div
      className={`task-card ${overdue ? 'overdue' : ''}`}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      style={{ opacity: dragging ? 0.5 : 1, ...(blocked ? { borderColor: 'var(--error)' } : affected ? { borderColor: 'var(--warn)' } : {}) }}
    >
      <div style={{ fontWeight: 500, fontSize: 13 }}>{task.title}</div>
      <div className="row" style={{ marginTop: 6, fontSize: 12, flexWrap: 'wrap' }}>
        {blocked && <span className="badge red">заблокирована</span>}
        {affected && <span className="badge yellow">затронута</span>}
        {overdue && <span className="badge red">просрочена</span>}
        <span style={{ color: PRIORITY_COLOR[task.priority] ?? 'var(--muted)' }}>{task.priority}</span>
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

export function TaskForm({ columns, onClose, onCreated }: { columns: Column[]; onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('medium')
  const [moduleId, setModuleId] = useState<number | null>(null)
  const [estimateHm, setEstimateHm] = useState('')
  const [deadline, setDeadline] = useState('')
  const [tags, setTags] = useState('')
  const [columnKey, setColumnKey] = useState('backlog')
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
      const assigneeList = Object.entries(assignees)
        .filter(([, v]) => v)
        .map(([uid], i) => ({ user_id: Number(uid), is_primary: i === 0 }))
      const created = await api.createTask({
        title: title.trim(),
        description: description || null,
        priority,
        module_id: moduleId,
        estimate_seconds: hmToSeconds(estimateHm),
        deadline: deadline ? new Date(deadline).toISOString() : null,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        column_key: columnKey,
      })
      if (assigneeList.length > 0) {
        await api.setAssignees(created.id, assigneeList)
      }
      onCreated()
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
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </Field>
          <Field label="Колонка">
            <select value={columnKey} onChange={(e) => setColumnKey(e.target.value)}>
              {columns.map((col) => <option key={col.key} value={col.key}>{col.title}</option>)}
            </select>
          </Field>
          <Field label="Модуль">
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
          <Field label="Дедлайн">
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

function TaskPanel({
  task, tasks, participants, modules, columns, isCaptain, onChange, onClose,
}: {
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
  const [checkText, setCheckText] = useState('')
  const [depId, setDepId] = useState<number | null>(null)
  const [depType, setDepType] = useState('blocked_by')
  const [subTitle, setSubTitle] = useState('')
  const [adjustH, setAdjustH] = useState('')
  const [error, setError] = useState('')
  const [history] = useLoad<{ action: string; actor_id: number | null; data: Record<string, unknown>; created_at: string }[]>(
    () => api.taskHistory(task.id),
    [task.id],
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
  after: 'перед',
  before: 'после',
}

  async function run(fn: () => Promise<unknown>) {
    setError('')
    try {
      await fn()
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
    <div>
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
        <button className="ghost small" onClick={onClose}>✕</button>
      </div>
      <div className="row" style={{ margin: '8px 0', flexWrap: 'wrap' }}>
        <Badge kind={badgeForStatus(task.column_key === 'done' || task.column_key === 'realised' ? 'done' : 'open')}>
          {task.column_key.replace(/_/g, ' ')}
        </Badge>
        <span className="muted" style={{ fontSize: 12 }}>приоритет {task.priority}</span>
        {task.deadline && <span className="muted" style={{ fontSize: 12 }}>до {fmtDate(task.deadline)}</span>}
      </div>

      {error && <div className="error" style={{ margin: '8px 0' }}>{error}</div>}

      <div className="section">
        <div className="section-title">Статус и свойства</div>
        <div className="row">
          <select
            value={task.column_key}
            onChange={(e) => {
              if (!warnIfBlocked(task, tasks, e.target.value)) return
              run(() => api.moveTask(task.id, e.target.value, task.version))
            }}
          >
            {columns.map((c) => <option key={c.id} value={c.key}>{c.title}</option>)}
          </select>
          <select value={task.priority} onChange={(e) => run(() => api.patchTask(task.id, { priority: e.target.value }, task.version))}>
            {['low', 'medium', 'high', 'critical'].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <select
            value={task.module_id ?? ''}
            onChange={(e) => run(() => api.patchTask(task.id, { module_id: e.target.value ? Number(e.target.value) : null }, task.version))}
          >
            <option value="">без модуля</option>
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
              placeholder="Скорректировать время (часов)"
              value={adjustH}
              onChange={(e) => setAdjustH(e.target.value)}
              style={{ maxWidth: 220 }}
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
            <Badge kind={DONE_KEYS.includes(p.pred.column_key) ? 'green' : 'yellow'}>
              {DONE_KEYS.includes(p.pred.column_key) ? 'готово' : 'не завершено'}
            </Badge>
            <span className="grow" />
            <button className="small ghost" onClick={() => run(() => api.removeDependency(task.id, p.pred.id))}>✕</button>
          </div>
        ))}
        {predecessors.length === 0 && reverseLinks.length === 0 && (
          <div className="muted" style={{ fontSize: 12 }}>Связей нет</div>
        )}
        {reverseLinks.map((r) => (
          <div key={r.dep.id} className="row" style={{ padding: '2px 0' }}>
            <span className="badge gray">{REVERSE_LABELS[r.linkType] ?? r.linkType}</span>
            <span className="muted">{r.dep.title}</span>
            <Badge kind={DONE_KEYS.includes(r.dep.column_key) ? 'green' : 'yellow'}>
              {DONE_KEYS.includes(r.dep.column_key) ? 'готово' : 'не завершено'}
            </Badge>
          </div>
        ))}
        <div className="row" style={{ marginTop: 6 }}>
          <select value={depType} onChange={(e) => setDepType(e.target.value)} style={{ maxWidth: 170 }}>
            <option value="blocked_by">заблокирована</option>
            <option value="after">после</option>
            <option value="before">до</option>
          </select>
          <select value={depId ?? ''} onChange={(e) => setDepId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">+ задача…</option>
            {tasks.filter((t) => t.id !== task.id && !task.predecessors.some((x) => x.task_id === t.id)).map((t) => (
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
        {subtasks.map((s) => (
          <div key={s.id} className="row" style={{ padding: '2px 0' }}>
            <span>{s.title}</span>
            <Badge kind={['done', 'realised'].includes(s.column_key) ? 'green' : 'gray'}>{s.column_key.replace(/_/g, ' ')}</Badge>
          </div>
        ))}
        <div className="row" style={{ marginTop: 6 }}>
          <input placeholder="Новая подзадача…" value={subTitle} onChange={(e) => setSubTitle(e.target.value)} />
          <button
            className="small"
            onClick={async () => {
              if (!subTitle.trim()) return
              await run(() => api.createTask({ title: subTitle.trim(), parent_id: task.id, column_key: 'backlog' }))
              setSubTitle('')
            }}
          >
            +
          </button>
        </div>
      </div>

      <div className="section">
        <div className="section-title">История изменений</div>
        <div className="grid" style={{ gap: 6 }}>
          {(history ?? []).map((h, i) => (
            <div key={i} style={{ fontSize: 12, borderLeft: '2px solid var(--border)', paddingLeft: 8 }}>
              <div className="row">
                <b>{h.action}</b>
                <span className="muted" style={{ fontSize: 11 }}>{fmtDate(h.created_at)}</span>
              </div>
              {h.data && Object.keys(h.data).length > 0 && (
                <div className="muted mono" style={{ fontSize: 11 }}>
                  {JSON.stringify(h.data)}
                </div>
              )}
            </div>
          ))}
          {(history ?? []).length === 0 && <div className="muted" style={{ fontSize: 12 }}>Изменений нет</div>}
        </div>
      </div>
    </div>
  )
}

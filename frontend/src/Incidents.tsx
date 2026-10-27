import { useEffect, useMemo, useState } from 'react'
import { api, Incident, Me, Module, Participant, Task } from './api'
import { Badge, Field, Modal, badgeForStatus, fmtDate, useLoad } from './ui'

function ageStr(seconds: number): string {
  if (seconds < 60) return `${seconds}с`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}м`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}ч`
  return `${Math.floor(seconds / 86400)}д`
}

export function Incidents({ me }: { me: Me }) {
  const [incidents, error, reload] = useLoad<Incident[]>(api.incidents)
  const [participants] = useLoad<Participant[]>(api.participants)
  const [tasks] = useLoad<Task[]>(api.tasks)
  const [modules] = useLoad<Module[]>(api.modules)
  const [createOpen, setCreateOpen] = useState(false)
  const [selected, setSelected] = useState<Incident | null>(null)
  const [filter, setFilter] = useState('')

  // Авто-обновление (возраст инцидентов, новые события).
  useEffect(() => {
    const id = setInterval(reload, 5000)
    return () => clearInterval(id)
  }, [reload])

  const names = new Map((participants ?? []).map((p) => [p.id, p.display_name]))
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

      <div className="grid" style={{ gap: 8 }}>
        {list.map((i) => (
          <div key={i.id} className="card" style={{ cursor: 'pointer', padding: 10 }} onClick={() => setSelected(i)}>
            <div className="row">
              <Badge kind={badgeForStatus(i.level === 'red' && i.status === 'confirmed' ? 'red' : i.level === 'red' ? 'open' : i.level)}>
                {i.level}
              </Badge>
              <Badge kind={badgeForStatus(i.status)}>{i.status}</Badge>
              <b>{i.title}</b>
              <span className="grow" />
              <span className="muted" style={{ fontSize: 12 }}>
                {ageStr(i.age_seconds)} · ответственный {name(i.owner_id)} · автор {name(i.author_id)}
              </span>
            </div>
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
              incident={selected}
              names={names}
              taskNames={taskNames}
              moduleNames={moduleNames}
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
  const [ownerId, setOwnerId] = useState<number | null>(null)
  const [targetTasks, setTargetTasks] = useState<number[]>([])
  const [targetUsers, setTargetUsers] = useState<number[]>([])
  const [targetModules, setTargetModules] = useState<number[]>([])
  const [taskSearch, setTaskSearch] = useState('')
  const [taskColumn, setTaskColumn] = useState('')
  const [onlyMine, setOnlyMine] = useState(false)
  const [error, setError] = useState('')

  const openTasks = useMemo(
    () => tasks.filter((t) => !['done', 'realised', 'trashed'].includes(t.column_key)),
    [tasks],
  )
  const filteredTasks = openTasks.filter((t) => {
    if (taskSearch && !t.title.toLowerCase().includes(taskSearch.toLowerCase())) return false
    if (taskColumn && t.column_key !== taskColumn) return false
    if (onlyMine && !t.assignees.some((a) => a.user_id === me.id)) return false
    return true
  })

  async function submit() {
    if (!title.trim()) return
    setError('')
    try {
      const targets = [
        ...targetTasks.map((id) => ({ target_type: 'task', target_id: id })),
        ...targetUsers.map((id) => ({ target_type: 'user', target_id: id })),
        ...targetModules.map((id) => ({ target_type: 'module', target_id: id })),
      ]
      await api.createIncident({
        level, title: title.trim(), description: description || null,
        impact: impact || null, urgency, owner_id: ownerId, targets,
      })
      onCreated()
    } catch (e) {
      setError((e as Error).message)
    }
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
            {['low', 'medium', 'high', 'critical'].map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </Field>
        <Field label="Ответственный">
          <select value={ownerId ?? ''} onChange={(e) => setOwnerId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>
            {participants.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
          </select>
        </Field>
      </div>
      <Field label={`Затронутые задачи (выбрано: ${targetTasks.length})`}>
        <div className="row" style={{ marginBottom: 6 }}>
          <input placeholder="Поиск по названию…" value={taskSearch} onChange={(e) => setTaskSearch(e.target.value)} />
          <select value={taskColumn} onChange={(e) => setTaskColumn(e.target.value)}>
            <option value="">Все колонки</option>
            {['backlog', 'todo', 'specification_review', 'in_progress', 'testing', 'review'].map((k) => (
              <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>
            ))}
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
              <span className="muted" style={{ fontSize: 11 }}>{t.column_key.replace(/_/g, ' ')}</span>
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
      <Field label="Затронутые модули">
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
        <button className="primary" onClick={submit}>Создать</button>
      </div>
    </Modal>
  )
}

function IncidentPanel({
  incident, names, taskNames, moduleNames, onChanged, onClose,
}: {
  incident: Incident
  names: Map<number, string>
  taskNames: Map<number, string>
  moduleNames: Map<number, string>
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
        <h3 style={{ margin: 0 }}>#{incident.id} {incident.title}</h3>
        <button className="ghost small" onClick={onClose}>✕</button>
      </div>
      <div className="row" style={{ margin: '8px 0' }}>
        <Badge kind={badgeForStatus(incident.level === 'red' && incident.status === 'confirmed' ? 'red' : incident.level)}>{incident.level}</Badge>
        <Badge kind={badgeForStatus(incident.status)}>{incident.status}</Badge>
        <span className="muted" style={{ fontSize: 12 }}>создан {fmtDate(incident.created_at)}</span>
      </div>

      {error && <div className="error" style={{ margin: '8px 0' }}>{error}</div>}

      <div className="section">
        <div className="section-title">Детали</div>
        <div className="grid" style={{ gap: 4, fontSize: 13 }}>
          {incident.description && <div><b className="muted">Описание:</b> {incident.description}</div>}
          {incident.impact && <div><b className="muted">Влияние:</b> {incident.impact}</div>}
          <div><b className="muted">Срочность:</b> {incident.urgency ?? '—'}</div>
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
              <span key={i} className="badge gray">{t.target_type}: {targetName(t)}</span>
            ))}
          </div>
        </div>
      )}

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
                <b>{ev.event_type}</b>
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

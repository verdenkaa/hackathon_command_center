import { useEffect, useState } from 'react'
import { api, AiSettings, Me } from './api'
import { Badge, Field, fmtDate, useLoad } from './ui'

export function Settings({ me, onProjectsChanged }: { me: Me; onProjectsChanged: () => void }) {
  const isAdmin = me.roles.some((r) => r.role === 'admin')
  const isCaptain = me.roles.some((r) => r.role === 'captain' || r.role === 'admin')
  const [msg, setMsg] = useState('')

  return (
    <div style={{ maxWidth: 720 }}>
      <h3 style={{ margin: '4px 0 12px' }}>Настройки</h3>
      {msg && <div className="card" style={{ marginBottom: 12, borderColor: 'var(--ok)' }}>{msg}</div>}

      <ProjectSection isAdmin={isAdmin} isCaptain={isCaptain} setMsg={setMsg} onProjectsChanged={onProjectsChanged} />
      <ColumnsSection setMsg={setMsg} />
      <ModulesSection setMsg={setMsg} />
      <CompletionSection isCaptain={isCaptain} setMsg={setMsg} />
      <AiSection isCaptain={isCaptain} setMsg={setMsg} />
    </div>
  )
}

function ProjectSection({ isAdmin, isCaptain, setMsg, onProjectsChanged }: {
  isAdmin: boolean
  isCaptain: boolean
  setMsg: (s: string) => void
  onProjectsChanged: () => void
}) {
  const [projects, , reloadProjects] = useLoad(api.projects)
  const current = (projects ?? []).find((p) => p.id === Number(localStorage.getItem('hcc-project') ?? 1)) ?? projects?.[0]
  const [name, setName] = useState('')
  const [deadline, setDeadline] = useState('')
  const [newName, setNewName] = useState('')

  useEffect(() => {
    if (current) setName(current.name)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id])

  return (
    <div className="card section">
      <div className="section-title">Проект</div>
      <div className="row" style={{ marginBottom: 8 }}>
        <Badge kind={current?.state === 'completed' ? 'gray' : current?.state === 'active' ? 'green' : 'blue'}>
          {current?.state ?? '—'}
        </Badge>
        {current?.deadline_msk && (
          <span className="muted" style={{ fontSize: 13 }}>дедлайн: {fmtDate(current.deadline_msk)}</span>
        )}
      </div>
      <div className="row">
        <Field label="Название">
          <input value={name} onChange={(e) => setName(e.target.value)} disabled={!isCaptain} />
        </Field>
        <button
          className="small"
          disabled={!isCaptain || !name.trim()}
          onClick={async () => {
            await api.patchProject({ name: name.trim() })
            onProjectsChanged()
            setMsg('Название обновлено')
          }}
        >
          Сохранить
        </button>
      </div>
      <div className="row">
        <Field label="Дедлайн (только администратор)">
          <input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} disabled={!isAdmin} />
        </Field>
        <button
          className="small"
          disabled={!isAdmin || !deadline}
          onClick={async () => {
            await api.patchProject({ deadline_msk: new Date(deadline).toISOString() })
            onProjectsChanged()
            setMsg('Дедлайн обновлён')
          }}
        >
          Сохранить
        </button>
      </div>
      {isAdmin && (
        <div className="row" style={{ marginTop: 8 }}>
          <Field label="Создать новый проект">
            <input placeholder="Название проекта" value={newName} onChange={(e) => setNewName(e.target.value)} />
          </Field>
          <button
            className="small primary"
            disabled={!newName.trim()}
            onClick={async () => {
              await api.createProject(newName.trim())
              setNewName('')
              onProjectsChanged()
              reloadProjects()
              setMsg(`Проект «${newName.trim()}» создан. Выберите его в списке сверху.`)
            }}
          >
            Создать
          </button>
        </div>
      )}
    </div>
  )
}

function ColumnsSection({ setMsg }: { setMsg: (s: string) => void }) {
  const [columns, error, reload] = useLoad(api.columns)
  const [title, setTitle] = useState('')
  const [autoStart, setAutoStart] = useState(false)
  const [autoStop, setAutoStop] = useState(false)

  return (
    <div className="card section">
      <div className="section-title">Колонки доски</div>
      {error && <div className="error">{error}</div>}
      <p className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>
        Можно добавлять и удалять свои колонки, задавать правила: авто-старт таймера при попадании задачи в колонку
        и авто-остановка. Стартовые 9 колонок удалять нельзя.
      </p>
      <table>
        <thead>
          <tr><th>Колонка</th><th>Авто-старт таймера</th><th>Авто-стоп таймера</th><th></th></tr>
        </thead>
        <tbody>
          {(columns ?? []).map((c) => (
            <tr key={c.id}>
              <td>
                <input
                  defaultValue={c.title}
                  onBlur={async (e) => {
                    if (e.target.value.trim() && e.target.value !== c.title) {
                      await api.patchColumn(c.id, { title: e.target.value.trim() })
                      reload()
                      setMsg('Колонка переименована')
                    }
                  }}
                  style={{ border: 'none', background: 'transparent', padding: 0 }}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  defaultChecked={c.auto_start_timer}
                  onChange={async (e) => {
                    await api.patchColumn(c.id, { auto_start_timer: e.target.checked })
                    reload()
                    setMsg('Правило колонки обновлено')
                  }}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  defaultChecked={c.auto_stop_timer}
                  onChange={async (e) => {
                    await api.patchColumn(c.id, { auto_stop_timer: e.target.checked })
                    reload()
                    setMsg('Правило колонки обновлено')
                  }}
                />
              </td>
              <td>
                <button
                  className="small danger"
                  onClick={async () => {
                    if (confirm(`Удалить колонку «${c.title}»? Её задачи перейдут в Backlog.`)) {
                      try {
                        await api.deleteColumn(c.id)
                        reload()
                        setMsg('Колонка удалена')
                      } catch (e) {
                        setMsg((e as Error).message)
                      }
                    }
                  }}
                >
                  удалить
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 10 }}>
        <input placeholder="Новая колонка…" value={title} onChange={(e) => setTitle(e.target.value)} style={{ maxWidth: 220 }} />
        <label className="row" style={{ cursor: 'pointer', fontSize: 13 }}>
          <input type="checkbox" checked={autoStart} onChange={(e) => setAutoStart(e.target.checked)} />
          <span>авто-старт</span>
        </label>
        <label className="row" style={{ cursor: 'pointer', fontSize: 13 }}>
          <input type="checkbox" checked={autoStop} onChange={(e) => setAutoStop(e.target.checked)} />
          <span>авто-стоп</span>
        </label>
        <button
          className="primary small"
          disabled={!title.trim()}
          onClick={async () => {
            await api.createColumn(title.trim(), autoStart, autoStop)
            setTitle(''); setAutoStart(false); setAutoStop(false)
            reload()
            setMsg('Колонка добавлена')
          }}
        >
          + Колонка
        </button>
      </div>
    </div>
  )
}

function ModulesSection({ setMsg }: { setMsg: (s: string) => void }) {
  const [modules, error, reload] = useLoad(api.modules)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')

  return (
    <div className="card section">
      <div className="section-title">Модули</div>
      {error && <div className="error">{error}</div>}
      <div className="row" style={{ marginBottom: 8 }}>
        <input placeholder="Название модуля" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 220 }} />
        <input placeholder="Описание (необязательно)" value={desc} onChange={(e) => setDesc(e.target.value)} />
        <button
          className="primary small"
          disabled={!name.trim()}
          onClick={async () => {
            await api.createModule(name.trim(), desc)
            setName(''); setDesc('')
            reload()
            setMsg('Модуль создан')
          }}
        >
          + Модуль
        </button>
      </div>
      <table>
        <thead>
          <tr><th>Название</th><th>Описание</th><th>Светофор</th><th></th></tr>
        </thead>
        <tbody>
          {(modules ?? []).map((m) => (
            <tr key={m.id}>
              <td>
                <input
                  defaultValue={m.name}
                  onBlur={async (e) => {
                    if (e.target.value.trim() && e.target.value !== m.name) {
                      await api.patchModule(m.id, { name: e.target.value.trim() })
                      reload()
                      setMsg('Модуль переименован')
                    }
                  }}
                  style={{ border: 'none', background: 'transparent', padding: 0 }}
                />
              </td>
              <td className="muted">{m.description ?? '—'}</td>
              <td><Badge kind={m.traffic_status === 'green' ? 'green' : m.traffic_status === 'yellow' ? 'yellow' : 'red'}>{m.traffic_status}</Badge></td>
              <td>
                <button
                  className="small danger"
                  onClick={async () => {
                    if (confirm(`Удалить модуль «${m.name}»? Задачи останутся без модуля.`)) {
                      await api.deleteModule(m.id)
                      reload()
                      setMsg('Модуль удалён')
                    }
                  }}
                >
                  удалить
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CompletionSection({ isCaptain, setMsg }: { isCaptain: boolean; setMsg: (s: string) => void }) {
  const [projects] = useLoad(api.projects)
  const current = (projects ?? []).find((p) => p.id === Number(localStorage.getItem('hcc-project') ?? 1)) ?? projects?.[0]
  const completed = current?.state === 'completed'
  return (
    <div className="card section">
      <div className="section-title">Завершение хакатона</div>
      <p className="muted" style={{ fontSize: 13, margin: '0 0 8px' }}>
        Завершение и повторное открытие требуют единогласного голосования всех активных капитанов.
        В завершённом режиме данные доступны только для чтения.
      </p>
      <div className="row">
        {!completed && (
          <button
            className="danger"
            disabled={!isCaptain}
            onClick={async () => {
              if (confirm('Проголосовать за завершение проекта? Потребуется голос всех капитанов.')) {
                const r = await api.completionVote('complete')
                setMsg(`Голос учтён. Голосов: ${(r as { votes: number }).votes} из ${(r as { required: number }).required}. Статус: ${(r as { state: string }).state}`)
              }
            }}
          >
            Голосовать за завершение
          </button>
        )}
        {completed && (
          <button
            disabled={!isCaptain}
            onClick={async () => {
              const r = await api.completionVote('reopen')
              setMsg(`Голос за повторное открытие учтён. Статус: ${(r as { state: string }).state}`)
            }}
          >
            Голосовать за повторное открытие
          </button>
        )}
      </div>
    </div>
  )
}

function AiSection({ isCaptain, setMsg }: { isCaptain: boolean; setMsg: (s: string) => void }) {
  const [settings, , reload] = useLoad<AiSettings>(api.aiSettings)
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [provider, setProvider] = useState('')
  const [interval, setIntervalMin] = useState('')

  if (!settings) return null
  const effEnabled = enabled ?? settings.enabled
  const effProvider = provider || settings.priority_provider
  const effInterval = interval || String(settings.interval_minutes)

  return (
    <div className="card section">
      <div className="section-title">ИИ-советник</div>
      <div className="row" style={{ marginBottom: 8 }}>
        <label className="row" style={{ cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={effEnabled}
            disabled={!isCaptain}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span>Включить ИИ-рекомендации</span>
        </label>
        <Badge kind={effEnabled ? 'green' : 'gray'}>{effEnabled ? 'включён' : 'выключен'}</Badge>
      </div>
      <div className="row">
        <Field label="Приоритетный провайдер">
          <select value={effProvider} disabled={!isCaptain} onChange={(e) => setProvider(e.target.value)}>
            <option value="gemini">Gemini (бесплатный)</option>
            <option value="deepseek">DeepSeek (платный)</option>
          </select>
        </Field>
        <Field label="Интервал (минут)">
          <input type="number" min="5" value={effInterval} disabled={!isCaptain} onChange={(e) => setIntervalMin(e.target.value)} />
        </Field>
      </div>
      {isCaptain && (enabled !== null || provider !== '' || interval !== '') && (
        <button
          className="primary small"
          onClick={async () => {
            await api.patchAiSettings({
              enabled: effEnabled,
              priority_provider: effProvider,
              interval_minutes: Number(effInterval),
            })
            setEnabled(null)
            setProvider('')
            setIntervalMin('')
            reload()
            setMsg('Настройки ИИ сохранены')
          }}
        >
          Сохранить настройки ИИ
        </button>
      )}
    </div>
  )
}

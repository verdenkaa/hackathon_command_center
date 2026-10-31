import { useEffect, useState } from 'react'
import { api, AiSettings, Me, currentProject } from './api'
import { Badge, Field, fmtDate, useLoad, Modal, toMoscowInput, fromMoscowInput } from './ui'
import { AdvisorProviderSettings } from './Advisor'
import { Sandbox } from './Sandbox'
import { TelegramSettings } from './TelegramSettings'

export function Settings({ me, onProjectsChanged, onOpenProject }: {
  me: Me; onProjectsChanged: () => void
  onOpenProject: (id:number,view:'board'|'incidents'|'analytics')=>void
}) {
  const isAdmin = me.roles.some((r) => r.role === 'admin')
  const isCaptain = me.roles.some((r) => r.role === 'admin' || (r.role === 'captain' && r.project_id === currentProject()))
  const [msg, setMsg] = useState('')

  return (
    <><div className="settings-page" style={{ maxWidth: 720 }}>
      <h3 style={{ margin: '4px 0 12px' }}>Настройки</h3>
      {msg && <div className="card" style={{ marginBottom: 12, borderColor: 'var(--ok)' }}>{msg}</div>}

      <ProjectSection isAdmin={isAdmin} isCaptain={isCaptain} setMsg={setMsg} onProjectsChanged={onProjectsChanged} />
      <ColumnsSection setMsg={setMsg} />
      <ModulesSection setMsg={setMsg} />
      <CompletionSection isCaptain={isCaptain} setMsg={setMsg} />
      <AiSection isCaptain={isCaptain} setMsg={setMsg} />
      {isCaptain && <TelegramSettings isAdmin={isAdmin}/>}
      {isAdmin && <AdvisorProviderSettings/>}
    </div>
    {isAdmin && !me.managed && <details className="card" style={{maxWidth:1100,marginTop:24}}>
      <summary style={{cursor:'pointer',fontWeight:600}}>Песочница · тестирование и очистка</summary>
      <Sandbox onProjectsChanged={onProjectsChanged} onOpenProject={onOpenProject}/>
    </details>}</>
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
  const [start, setStart] = useState('')
  const [periodError, setPeriodError] = useState('')
  useEffect(()=>{setStart(toMoscowInput(current?.start_msk ?? null))},[current?.start_msk])
  useEffect(()=>{setDeadline(toMoscowInput(current?.deadline_msk ?? null))},[current?.deadline_msk])

  useEffect(() => {
    if (current) setName(current.name)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id])

  return (
    <div className="card section">
      <div className="section-title">Проект</div>
      <div className="row" style={{ marginBottom: 8 }}>
        <Badge kind={current?.state === 'completed' ? 'gray' : current?.state === 'active' ? 'green' : 'blue'}>
          {{preparation:'Подготовка',active:'В работе',completed:'Завершён'}[current?.state ?? ''] ?? '—'}
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
        <Field label="Начало проекта (МСК, UTC+3, только администратор)">
          <input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)} disabled={!isAdmin}/>
        </Field>
        <Field label="Дедлайн (МСК, только администратор)">
          <input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} disabled={!isAdmin} />
        </Field>
        <button
          className="small"
          disabled={!isAdmin}
          onClick={async () => {
            setPeriodError('')
            if(start && deadline && start>=deadline){setPeriodError('Начало проекта должно быть строго раньше дедлайна');return}
            try {
              await api.patchProject({ start_msk: start?fromMoscowInput(start):null, deadline_msk: deadline?fromMoscowInput(deadline):null })
              onProjectsChanged();reloadProjects()
              setMsg('Сроки проекта обновлены. План задач сохранён.')
            } catch(e){setPeriodError((e as Error).message)}
          }}
        >
          Сохранить
        </button>
      </div>
      {periodError&&<p className="error" role="alert">{periodError}</p>}
      <p className="muted">Проекты создаются и запускаются в Ouroboros Daemon.</p>
    </div>
  )
}

function ColumnsSection({ setMsg }: { setMsg: (s: string) => void }) {
  const [columns, error, reload] = useLoad(api.columns)
  const [title, setTitle] = useState('')
  const [deleting,setDeleting] = useState<{id:number;title:string;count:number}|null>(null)
  const [destination,setDestination] = useState<number|null>(null)
  const [autoStart, setAutoStart] = useState(false)
  const [autoStop, setAutoStop] = useState(false)

  return (
    <div className="card section">
      <div className="section-title">Колонки доски</div>
      {error && <div className="error">{error}</div>}
      <p className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>
        Можно добавлять и удалять свои колонки, задавать правила: авто-старт таймера при попадании задачи в колонку
        и авто-остановка. Все колонки принадлежат только этому проекту. Назначение колонки определяет завершённость, корзину и аналитику независимо от её названия.
      </p>
      <table>
        <thead>
          <tr><th>Колонка</th><th>Авто-старт таймера</th><th>Авто-стоп таймера</th><th>Назначение и порядок</th></tr>
        </thead>
        <tbody>
          {(columns ?? []).map((c,index) => (
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
                    try {
                      if((columns?.length ?? 0)<=1){setMsg('Нельзя удалить последнюю колонку: задачам нужна колонка для хранения');return}
                      const tasks=await api.tasks()
                      const count=tasks.filter(t=>t.column_id===c.id).length
                      setDestination(null)
                      setDeleting({id:c.id,title:c.title,count})
                    }catch(e){setMsg((e as Error).message)}
                  }}
                >
                  удалить
                </button>
                <select aria-label={`Назначение ${c.title}`} value={c.semantic} onChange={async e=>{try{await api.patchColumn(c.id,{semantic:e.target.value});reload()}catch(e){setMsg((e as Error).message)}}}>
                  <option value="normal">Очередь</option><option value="active">В работе</option><option value="done">Завершено</option><option value="trash">Корзина</option>
                </select>
                <button className="small" disabled={index===0} onClick={async()=>{await api.patchColumn(c.id,{position:index-1});reload()}}>↑</button>
                <button className="small" disabled={index===(columns?.length ?? 0)-1} onClick={async()=>{await api.patchColumn(c.id,{position:index+1});reload()}}>↓</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {deleting && <Modal title={`Удалить колонку «${deleting.title}»?`} onClose={()=>setDeleting(null)}>
        <p>{deleting.count ? `В колонке ${deleting.count} задач. Выберите другую колонку проекта для переноса. Задачи сохранятся.` : 'Колонка пуста. Подтвердите удаление.'}</p>
        {deleting.count>0 && <select aria-label="Перенести задачи в" value={destination ?? ''} onChange={e=>setDestination(Number(e.target.value)||null)}>
          <option value="">Выберите колонку</option>
          {columns?.filter(c=>c.id!==deleting.id).map(c=><option key={c.id} value={c.id}>{c.title}</option>)}
        </select>}
        <div className="row"><button onClick={()=>setDeleting(null)}>Отмена</button>
          <button className="danger" disabled={deleting.count>0 && destination==null} onClick={async()=>{
            try{await api.deleteColumn(deleting.id,destination ?? undefined);setDeleting(null);reload();setMsg('Колонка удалена, задачи сохранены')}
            catch(e){setMsg((e as Error).message);setDeleting(null)}
          }}>Удалить колонку</button>
        </div>
      </Modal>}
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
      <div className="section-title">Треки</div>
      {error && <div className="error">{error}</div>}
      <div className="row" style={{ marginBottom: 8 }}>
        <input placeholder="Название трека" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 220 }} />
        <input placeholder="Описание (необязательно)" value={desc} onChange={(e) => setDesc(e.target.value)} />
        <button
          className="primary small"
          disabled={!name.trim()}
          onClick={async () => {
            await api.createModule(name.trim(), desc)
            setName(''); setDesc('')
            reload()
            setMsg('Трек создан')
          }}
        >
          + Трек
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
                      setMsg('Трек переименован')
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
                    if (confirm(`Удалить трек «${m.name}»? Задачи останутся без трека.`)) {
                      await api.deleteModule(m.id)
                      reload()
                      setMsg('Трек удалён')
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
  const [settings, error, reload] = useLoad<AiSettings>(api.aiSettings)
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [autoEnabled, setAutoEnabled] = useState<boolean | null>(null)
  const [interval, setIntervalMin] = useState('')
  const [prompt, setPrompt] = useState<string | null>(null)
  const [saveError, setSaveError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!settings) return <p role={error?'alert':'status'}>{error||'Загрузка настроек ИИ…'}</p>
  const effEnabled = enabled ?? settings.enabled
  const effAutoEnabled = autoEnabled ?? settings.auto_enabled
  const effInterval = interval || String(settings.interval_minutes)

  return (
    <div className="card section">
      <div className="section-title">Argus · ИИ-наблюдатель</div>
      <p className="muted">Gemini анализирует снимок проекта и отвечает на вопросы. Советы не изменяют задачи автоматически.</p>
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
        <label className="row"><input type="checkbox" style={{width:'auto'}} checked={effAutoEnabled} disabled={!isCaptain} onChange={e=>setAutoEnabled(e.target.checked)}/>Автоматический анализ</label>
        <Field label="Интервал (минут)">
          <input type="number" min="5" value={effInterval} disabled={!isCaptain} onChange={(e) => setIntervalMin(e.target.value)} />
        </Field>
      </div>
      <p className="muted">Следующий запуск: {fmtDate(settings.next_run_at)}. Только во время проекта; после перезапуска — не более одного актуального анализа.</p>
      <Field label="Контекст команды для советника">
        <textarea rows={5} value={prompt ?? settings.prompt} disabled={!isCaptain} onChange={(e) => setPrompt(e.target.value)} />
      </Field>
      <p className="muted">Ручные запросы и решения доступны капитану и администратору. Историю видят все участники.</p>
      {saveError&&<p className="error" role="alert">{saveError}</p>}
      {isCaptain && (enabled !== null || autoEnabled !== null || interval !== '' || prompt !== null) && (
        <button
          className="primary small"
          disabled={busy}
          onClick={async () => {
            setBusy(true);setSaveError('')
            try {
            await api.patchAiSettings({
              enabled: effEnabled,
              auto_enabled: effAutoEnabled,
              interval_minutes: Number(effInterval),
              prompt: prompt ?? settings.prompt,
            })
            setEnabled(null)
            setAutoEnabled(null)
            setIntervalMin('')
            setPrompt(null)
            reload()
            setMsg('Настройки ИИ сохранены')
            } catch(e){setSaveError((e as Error).message)} finally{setBusy(false)}
          }}
        >
          Сохранить настройки ИИ
        </button>
      )}
    </div>
  )
}

import { useState } from 'react'
import { api, TelegramMessage, SandboxRun, SandboxWorkspace, SandboxCheck, currentProject } from './api'
import { Badge, fmtDate, useLoad } from './ui'


type SandboxView = 'board' | 'incidents' | 'analytics'
type Message = {kind:'ok'|'error'; text:string}

export function Sandbox({ onProjectsChanged, onOpenProject }: {
  onProjectsChanged: () => void
  onOpenProject: (id:number, view:SandboxView) => void
}) {
  const [scenarios, scenariosError] = useLoad<Record<string,string>>(api.sandboxScenarios)
  const [catalog, checksError] = useLoad<Record<string,string>>(api.sandboxChecks)
  const [workspace, workspaceError, reloadWorkspace] = useLoad<SandboxWorkspace>(api.sandboxWorkspace)
  const [runs, runsError, reloadRuns] = useLoad<SandboxRun[]>(api.sandboxRuns)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState<Message | null>(null)
  const [latest, setLatest] = useState<SandboxRun | null>(null)
  const [messages, setMessages] = useState<TelegramMessage[]>([])
  const [telegramError, setTelegramError] = useState('')
  const [telegramScope, setTelegramScope] = useState<'sandbox'|'current'>('sandbox')
  const lastChecks = new Map<string,SandboxCheck>()
  for (const run of [latest, ...(runs ?? [])]) {
    for (const check of run?.checks ?? []) if (!lastChecks.has(check.name)) lastChecks.set(check.name,check)
  }

  function refresh() {
    reloadWorkspace()
    reloadRuns()
    onProjectsChanged()
  }

  async function run(scenario:string) {
    setBusy(scenario)
    setMessage(null)
    try {
      const result = await api.sandboxRun(scenario)
      setLatest(result)
      const passed = result.checks.filter((c) => c.status === 'passed').length
      setMessage({kind:result.status === 'ok' ? 'ok' : 'error',
        text: result.checks.length
          ? 'Автопроверки: ' + passed + '/' + result.checks.length + ' пройдено · ' + (result.duration_ms/1000).toFixed(1) + ' с.'
          : result.logs.join(' ')})
      refresh()
    } catch (e) {
      setMessage({kind:'error',text:(e as Error).message})
    } finally {
      setBusy('')
    }
  }

  async function reset():Promise<boolean> {
    if (!workspace?.project_id) return false
    setBusy('reset')
    setMessage(null)
    try {
      const result = await api.sandboxReset(workspace.project_id)
      setLatest(null)
      setMessages([])
      setMessage({kind:'ok',text:'Песочница очищена. Резервная копия: ' + result.archive_path})
      refresh()
      return true
    } catch (e) {
      setMessage({kind:'error',text:(e as Error).message})
      return false
    } finally {
      setBusy('')
    }
  }

  async function loadTelegram() {
    const id = telegramScope === 'sandbox' ? workspace?.project_id : currentProject()
    if (!id) {setMessages([]); return}
    setTelegramError('')
    try {setMessages(await api.sandboxTelegram(id))}
    catch (e) {setTelegramError((e as Error).message)}
  }

  const error = scenariosError || checksError || workspaceError || runsError
  return <section style={{paddingTop:16}}>
    <p className="muted" style={{marginTop:0}}>
      Демо-данные создаются только в выделенном проекте. Автопроверки выполняют реальные запросы API
      в отдельной временной SQLite и не меняют рабочие проекты. ИИ и Telegram остаются моками.
    </p>
    <div className="row" style={{flexWrap:'wrap',marginBottom:12}}>
      <button className="primary" disabled={!!busy} onClick={() => run('full_check')}>
        {busy === 'full_check' ? 'Проверка проекта…' : 'Запустить все автопроверки'}
      </button>
      <button disabled={!!busy} onClick={() => run('prepare_demo')}>
        {busy === 'prepare_demo' ? 'Подготовка…' : 'Подготовить демо-данные'}
      </button>
      <button disabled={!!busy} onClick={refresh}>Обновить состояние</button>
    </div>
    {error && <div className="error" role="alert">{error}</div>}
    {message && <div className={message.kind === 'error' ? 'error' : 'card'} role="status" style={{marginBottom:12}}>
      {message.text}
    </div>}

    <div className="card" style={{marginBottom:16}}>
      <div className="row" style={{flexWrap:'wrap',marginBottom:8}}>
        <b>{workspace?.project_name ?? 'Демо-проект ещё не создан'}</b>
        {workspace?.project_id && <Badge kind="blue">проект #{workspace.project_id}</Badge>}
        {workspace?.state && <Badge kind="gray">{workspace.state}</Badge>}
      </div>
      <div className="row" style={{flexWrap:'wrap',fontSize:13,marginBottom:8}}>
        {Object.entries({tasks:'Задачи',modules:'Модули',incidents:'Инциденты',running_timers:'Таймеры',
          recommendations:'Рекомендации',telegram:'Мок-сообщения'}).map(([key,label]) =>
          <span key={key}>{label}: <b>{workspace?.counts[key] ?? 0}</b></span>)}
      </div>
      {workspace?.project_id && <div className="row" style={{flexWrap:'wrap'}}>
        <button onClick={() => onOpenProject(workspace.project_id!, 'board')}>Открыть демо-доску</button>
        <button onClick={() => onOpenProject(workspace.project_id!, 'incidents')}>Открыть инциденты</button>
        <button onClick={() => onOpenProject(workspace.project_id!, 'analytics')}>Открыть ИИ и аналитику</button>
      </div>}
      {(workspace?.team.length ?? 0)>0 && <details style={{marginTop:12}}>
        <summary style={{cursor:'pointer'}}>Тестовые аккаунты и ручной вход</summary>
        <p className="muted">Для всех перечисленных тестовых аккаунтов пароль: <code>sandbox-pass</code>.
          Выйдите из текущего аккаунта и войдите под нужной ролью. Администратором остаётся ваш текущий аккаунт.</p>
        <table><thead><tr><th>Логин</th><th>Роль в песочнице</th><th>Состояние</th></tr></thead>
          <tbody>{workspace?.team.map((u) => <tr key={u.user_id}><td className="mono">{u.login}</td>
            <td>{u.role === 'captain' ? 'Капитан' : 'Участник'}</td><td>{u.active ? 'Активен' : 'Отключён'}</td></tr>)}</tbody>
        </table>
      </details>}
    </div>

    <h4>Автопроверки API</h4>
    <p className="muted">Можно запустить весь набор или одну группу. Ошибки выделяются отдельно; результаты сохраняются в журнале.
      Backup/restore API проверяется в отдельном процессе со своей базой и файлами. Рабочий архив не восстанавливается.</p>
    <div className="grid" style={{gridTemplateColumns:'repeat(auto-fit,minmax(270px,1fr))',gap:8,marginBottom:16}}>
      {Object.entries(catalog ?? {}).map(([key,title]) => {
        const result=lastChecks.get(key)
        return <div className="card" key={key}>
          <div className="row" style={{justifyContent:'space-between'}}><b>{title}</b>
            <Badge kind={!result ? 'gray' : result.status === 'passed' ? 'green' : 'red'}>
              {!result ? 'не запускалась' : result.status === 'passed' ? 'пройдено' : 'ошибка'}
            </Badge>
          </div>
          {result && <p style={{fontSize:12,margin:'8px 0'}}>{result.detail} · {result.duration_ms} мс</p>}
          <button className="small" disabled={!!busy} style={{marginTop:8}} onClick={() => run('check:' + key)}>
            {busy === 'check:' + key ? 'Проверка…' : 'Проверить группу'}
          </button>
        </div>
      })}
    </div>

    <details className="card" style={{marginBottom:16}}>
      <summary style={{cursor:'pointer'}}>Дополнительные сценарии для ручного прохода</summary>
      <p className="muted">Сценарии подготовки добавляют события в демо-проект; проверка ошибок ИИ выполняется в изолированной базе. Для чистого старта используйте очистку ниже.</p>
      <div className="grid" style={{gap:8}}>
        {Object.entries(scenarios ?? {}).filter(([key]) => key !== 'prepare_demo').map(([key,desc]) =>
          <div className="row" key={key}><span className="grow">{desc}</span>
            <button className="small" disabled={!!busy} onClick={() => run(key)}>{busy === key ? 'Выполняю…' : 'Запустить'}</button></div>)}
      </div>
    </details>

    <details className="card" style={{marginBottom:16}}>
      <summary style={{cursor:'pointer'}}>Telegram · посмотреть, что отправил бы бот</summary>
      <div className="row" style={{margin:'12px 0'}}>
        <select aria-label="Источник сообщений Telegram" value={telegramScope} onChange={(e) => {setTelegramScope(e.target.value as 'sandbox'|'current');setMessages([])}}>
          <option value="sandbox">Только демо-проект</option><option value="current">Выбранный рабочий проект</option>
        </select>
        <button onClick={loadTelegram}>Загрузить сообщения</button>
      </div>
      {telegramError && <div className="error">{telegramError}</div>}
      <div className="grid" style={{gap:6,maxHeight:340,overflowY:'auto'}}>
        {messages.map((m) => <div className="card" key={m.id} style={{padding:8}}>
          <div className="row"><Badge kind="blue">{m.mode}</Badge><b>{m.event_type}</b><span className="muted">{fmtDate(m.created_at)} · #{m.project_id}</span></div>
          <div style={{whiteSpace:'pre-wrap'}}>{m.text}</div>
          {m.mentions.length>0 && <div>{m.mentions.map((u) => '@'+u).join(' ')}</div>}
        </div>)}
        {messages.length===0 && <span className="muted">Выберите источник и загрузите сообщения.</span>}
      </div>
    </details>

    <ManualChecklist />

    <details className="card" style={{margin:'16px 0'}}>
      <summary style={{cursor:'pointer'}}>Журнал запусков · {runs?.length ?? 0}</summary>
      {(runs ?? []).slice(0,20).map((r) => <details className="card" key={r.id} style={{marginTop:8,padding:8}}>
        <summary style={{cursor:'pointer'}}><Badge kind={r.status==='ok' ? 'green':'red'}>{r.status==='ok' ? 'успешно':'ошибка'}</Badge>
          {' '}{r.scenario} · {fmtDate(r.created_at)} · {(r.duration_ms/1000).toFixed(1)} с</summary>
        {r.logs.map((log,index) => <div key={index} style={{fontSize:12,overflowWrap:'anywhere'}}>{log}</div>)}
        {(r.checks ?? []).map((c) => <div key={c.name} style={{fontSize:12}}>
          <b>{c.status==='passed' ? '✓' : '✕'} {c.title}</b>: {c.detail}
        </div>)}
      </details>)}
      {!runs?.length && <p className="muted">Запусков пока нет.</p>}
    </details>
    <ResetSandbox workspace={workspace} busy={!!busy} onReset={reset}/>
  </section>
}

export function ResetSandbox({workspace,busy,onReset}:{
  workspace:SandboxWorkspace|null
  busy:boolean
  onReset:()=>Promise<boolean>
}) {
  const [confirmation,setConfirmation]=useState('')
  return <details className="card" style={{borderColor:'var(--error)',marginTop:16}}>
    <summary style={{cursor:'pointer',color:'var(--error)'}}>Очистка песочницы</summary>
    <p>Будут очищены задачи, таймеры, модули, инциденты, контекст ИИ, уведомления и журналы тестового проекта
      {' '}<b>{workspace?.project_name ?? 'не создан'} {workspace?.project_id ? '#' + workspace.project_id : ''}</b>.
      Колонки и настройки вернутся к начальному состоянию.</p>
    <p>Общие аккаунты, их роли и рабочие проекты сохраняются. Перед очисткой создаётся резервная копия базы,
      файлы документов демо-проекта переносятся в архив.</p>
    <label className="field"><span className="field-label">Для подтверждения введите ОЧИСТИТЬ</span>
      <input aria-label="Подтверждение очистки" value={confirmation} disabled={busy || !workspace?.project_id}
        onChange={(e)=>setConfirmation(e.target.value)} autoComplete="off" placeholder="ОЧИСТИТЬ"/>
    </label>
    <button className="danger" disabled={busy || !workspace?.project_id || confirmation!=='ОЧИСТИТЬ'} onClick={async()=>{
      if(await onReset()) setConfirmation('')
    }}>Очистить песочницу</button>
  </details>
}

function ManualChecklist() {
  const [done,setDone]=useState<string[]>([])
  const cases=[
    'Открыть демо-доску: поиск, фильтр, перенос мышью и через список колонок',
    'Изменить описание, исполнителей, чек-лист и подзадачи в боковой панели',
    'Проверить видимое обновление таймера, жёлтый и красный сигналы',
    'В аналитике изменить вопрос, просмотреть контекст ИИ и исключить рекомендацию',
    'Войти участником и капитаном: проверить доступные проекты и действия',
    'Проверить UI резервных копий на отдельной копии приложения (API проверяется автоматически)',
  ]
  return <details className="card" style={{marginBottom:16}}>
    <summary style={{cursor:'pointer'}}>Ручная проверка интерфейса · {done.length}/{cases.length}</summary>
    <p className="muted">Автопроверки проверяют API, а этот список — удобство и поведение UI.
      Отметки действуют пока открыт этот экран; реальные интеграции здесь не проверяются.</p>
    {cases.map((text,index)=><label className="row" key={index} style={{marginBottom:8}}>
      <input type="checkbox" style={{width:'auto'}} checked={done.includes(text)}
        onChange={(e)=>setDone(e.target.checked ? [...done,text] : done.filter((x)=>x!==text))}/>{text}
    </label>)}
  </details>
}

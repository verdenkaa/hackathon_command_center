import { useCallback, useEffect, useState, useRef } from 'react'
import { api, ApiError, Me, Notification, Incident, Project, currentProject, setCurrentProject } from './api'
import { fmtDate } from './ui'
import Board from './Board'
import { Incidents } from './Incidents'
import { Analytics } from './Analytics'
import { Admin } from './Admin'
import { Settings } from './Settings'
import Planning from './Planning'
import {PlanningPreviewHost} from './PlanningPreview'
import {parseRoute,writeRoute,Tab} from './navigation'
import {QuickStart} from './QuickStart'

const TABS: { key: Tab; label: string }[] = [
  { key: 'board', label: 'Доска' },
  { key: 'planning', label: 'Планирование' },
  { key: 'incidents', label: 'Инциденты' },
  { key: 'analytics', label: 'Аналитика' },
  { key: 'admin', label: 'Админ' },
  { key: 'settings', label: 'Настройки' },
]

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTabState] = useState<Tab>(()=>parseRoute(window.location.search).tab)
  const setTab=(next:Tab)=>{setTabState(next);writeRoute({tab:next})}
  const [projectId, setProjectId] = useState(()=>{const id=parseRoute(window.location.search).project??currentProject();setCurrentProject(id);return id})
  const [projects, setProjects] = useState<Project[]>([])
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [notifOpen, setNotifOpen] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)
  type Target={type:'task'|'incident';id:number;incident?:Incident}|null
  const [navigation, setNavigationState] = useState<Target>(null)
  const setNavigation=(next:Target)=>{setNavigationState(next);writeRoute({project:currentProject(),task:next?.type==='task'?next.id:null,incident:next?.type==='incident'?next.id:null})}
  const [navigationKey, setNavigationKey] = useState(0)
  const [message, setMessage] = useState('')
  const [authError,setAuthError]=useState(''),[projectsError,setProjectsError]=useState(''),[globalError,setGlobalError]=useState(''),[saving,setSaving]=useState(0)
  const [locationVersion,setLocationVersion]=useState(0)
  const deepLinkOpened = useRef(false)
  const loadSession=useCallback(()=>{setLoading(true);setAuthError('');api.me().then(setMe).catch(e=>{if(e instanceof ApiError&&[401,403].includes(e.status))setMe(null);else setAuthError(e.message)}).finally(()=>setLoading(false))},[])
  useEffect(()=>{
    const rejected=(event:PromiseRejectionEvent)=>{event.preventDefault();setGlobalError(event.reason instanceof Error?event.reason.message:'Не удалось выполнить действие. Попробуйте снова.')}
    const progress=(event:Event)=>setSaving((event as CustomEvent<number>).detail)
    const pop=()=>{deepLinkOpened.current=false;const route=parseRoute(window.location.search);setTabState(route.tab);setNavigationState(null);if(route.project){setCurrentProject(route.project);setProjectId(route.project)};setLocationVersion(v=>v+1)}
    window.addEventListener('unhandledrejection',rejected);window.addEventListener('aion-saving',progress);window.addEventListener('popstate',pop)
    return()=>{window.removeEventListener('unhandledrejection',rejected);window.removeEventListener('aion-saving',progress);window.removeEventListener('popstate',pop)}
  },[])
  useEffect(()=>{
    const close=(e:PointerEvent)=>{if(!notifRef.current?.contains(e.target as Node))setNotifOpen(false)}
    const escape=(e:KeyboardEvent)=>{if(e.key==='Escape')setNotifOpen(false)}
    document.addEventListener('pointerdown',close)
    document.addEventListener('keydown',escape)
    return ()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',escape)}
  },[])

  useEffect(() => {
    loadSession()
  }, [loadSession])

  const reloadProjects = useCallback(() => {
    setProjectsError('')
    api.projects().then((items) => {
      setProjects(items)
      setProjectId((previous) => {
        const next = items.some((p) => p.id === previous) ? previous : items[0]?.id ?? 0
        setCurrentProject(next)
        return next
      })
      setProjectsLoaded(true)
    }).catch(e=>setProjectsError(e.message))
  }, [])

  useEffect(() => {
    if (!me) return
    reloadProjects()
  }, [me, reloadProjects])

  useEffect(()=>{
    if(!me||!projectsLoaded||deepLinkOpened.current)return
    deepLinkOpened.current=true
    const params=new URLSearchParams(window.location.search)
    const project=Number(params.get('project'))
    const task=Number(params.get('task'))
    const incident=Number(params.get('incident'))
    if(!project)return
    if(!projects.some(p=>p.id===project)){setMessage('Нет доступа к проекту из ссылки');return}
    setCurrentProject(project);setProjectId(project)
    if(Number.isSafeInteger(task)&&task>0){
      api.task(task).then(value=>{if(value.project_id!==project)throw new Error('Объект не принадлежит проекту');setNavigationState({type:'task',id:task});setNavigationKey(v=>v+1);setTabState(parseRoute(window.location.search).tab==='planning'?'planning':'board')}).catch(e=>setMessage(e.message))
    }else if(Number.isSafeInteger(incident)&&incident>0){
      api.incident(incident).then(value=>{if(value.project_id!==project)throw new Error('Объект не принадлежит проекту');setNavigationState({type:'incident',id:incident,incident:value});setNavigationKey(v=>v+1);setTabState('incidents')}).catch(e=>setMessage(e.message))
    }
  },[me,projectsLoaded,projects,locationVersion])

  useEffect(() => {
    if (!me) return
    const load = () => api.notifications().then(setNotifications).catch(() => {})
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [me])

  if (loading) return <div style={{ padding: 24 }}>Загрузка…</div>
  if(authError)return <div role="alert" className="card">{authError} <button onClick={loadSession}>Повторить вход</button></div>
  if (!me) return <Login onLogin={(user) => {
    setTab('board')
    setProjects([])
    setProjectsLoaded(false)
    setMe(user)
  }} />
  if (!projectsLoaded) return <div style={{ padding: 24 }} role={projectsError?'alert':'status'}>{projectsError||'Загрузка проекта Aion…'}{projectsError&&<button onClick={reloadProjects}>Повторить загрузку</button>}</div>

  const isAdmin = me.roles.some((r) => r.role === 'admin')
  const unread = notifications.filter((n) => !n.read_at).length

  if (projectsLoaded && projects.length === 0 && (!isAdmin || me.managed)) return (
    <div className="card" style={{margin:24}}>
      Нет доступных проектов. Попросите администратора назначить роль в проекте.
      <button onClick={async () => { await api.logout(); setMe(null); setProjectsLoaded(false) }}>Выйти</button>
    </div>
  )

  function switchProject(id: number) {
    setNavigation(null)
    setMessage('')
    setCurrentProject(id)
    setProjectId(id)
    setTab('board')
    writeRoute({project:id,tab:'board',task:null,incident:null})
  }

  return (
    <div style={{ padding: '0 16px 24px' }}>
      <PlanningPreviewHost/>
      <div className="topbar" style={{ paddingTop: 12 }}>
        <span className="brand" style={{ color: 'var(--accent)' }}><img src="/aion.png" alt="" style={{width:32,height:32,objectFit:"contain",verticalAlign:"middle",marginRight:8}}/>Aion</span>
        <select className="project-select" value={projectId} onChange={(e) => switchProject(Number(e.target.value))}>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <nav className="tabs" style={{ margin: 0, borderBottom: 'none', flex: 1 }}>
          {TABS.filter((t) => t.key !== 'admin' || isAdmin).map((t) => (
            <button key={t.key} className={tab === t.key ? 'active' : ''} onClick={() => {setNavigation(null);setTab(t.key)}}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="dropdown" ref={notifRef}>
          <button onClick={() => setNotifOpen(!notifOpen)}>
            🔔 {unread > 0 && <BadgeCount n={unread} />}
          </button>
          {notifOpen && (
            <div className="dropdown-menu">
              <div className="dropdown-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>непрочитано: {unread}</span>
                <div className="row" style={{ gap: 4 }}>
                  <button
                    className="small"
                    disabled={unread === 0}
                    onClick={async () => {
                      await api.readAllNotifications()
                      setNotifications((prev) => prev.map((x) => ({ ...x, read_at: x.read_at ?? 'now' })))
                    }}
                  >
                    Прочитать все
                  </button>
                  <button
                    className="small"
                    disabled={notifications.length === 0}
                    onClick={async () => {
                      await api.clearNotifications()
                      setNotifications([])
                    }}
                  >
                    Очистить все
                  </button>
                </div>
              </div>
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                {notifications.length === 0 && <div className="dropdown-item muted">Уведомлений нет</div>}
                {notifications.map((n) => (
                  <NotificationItem key={n.id} notification={n} onOpen={async()=>{
                    try {
                      const result=await api.openNotification(n.id)
                      setNotifications(prev=>prev.map(x=>x.id===n.id ? {...x,read_at:'now'}:x))
                      if(!result.target){setMessage(result.message);setNotifOpen(false);return}
                      const target=result.target
                      const incident=target.type==='incident' ? await api.incident(target.id) : undefined
                      switchProject(target.project_id)
                      setNavigation({...target,incident})
                      setNavigationKey(v=>v+1)
                      setTab(target.type==='task'?'board':'incidents')
                      setNotifOpen(false)
                    }catch(e){setMessage((e as Error).message);setNotifOpen(false)}
                  }} onRead={async()=>{
                    try{await api.readNotification(n.id);setNotifications(prev=>prev.map(x=>x.id===n.id?{...x,read_at:'now'}:x))}
                    catch(e){setMessage((e as Error).message)}
                  }} onDelete={async()=>{
                    try{await api.deleteNotification(n.id);setNotifications(prev=>prev.filter(x=>x.id!==n.id))}
                    catch(e){setMessage((e as Error).message)}
                  }}/>

                ))}
              </div>
            </div>
          )}
        </div>
        <button
          onClick={async () => {
            await api.logout()
            setMe(null)
          }}
        >
          {me.display_name} · Выйти
        </button>
      </div>

      <div style={{ marginTop: 12 }}>
        {saving>0&&<div role="status" className="saving-status">Сохранение…</div>}
        {globalError&&<div role="alert" className="error-toast">{globalError} <button onClick={()=>setGlobalError('')}>Закрыть сообщение</button></div>}
        {projectsError&&<div role="alert" className="error">{projectsError} <button onClick={reloadProjects}>Повторить загрузку</button></div>}
        {message && <div role="status" className="card">{message}</div>}
        {tab==='board'&&isAdmin&&<QuickStart key={projectId} project={projects.find(p=>p.id===projectId)} onNavigate={setTab} onCreate={()=>{writeRoute({newtask:'1'});setNavigationKey(v=>v+1)}}/>}
        {tab === 'board' && <Board key={`${projectId}-${navigationKey}`} me={me} openTaskId={navigation?.type==='task'?navigation.id:null}
          onOpenIncident={id=>{setNavigation({type:'incident',id});setNavigationKey(v=>v+1);setTab('incidents')}}/>}
        {tab === 'incidents' && <Incidents key={`${projectId}-${navigationKey}`} me={me} initialIncident={navigation?.incident} openIncidentId={navigation?.type==='incident'?navigation.id:null} />}
        {tab === 'analytics' && <Analytics key={projectId} me={me}
          onOpenTask={id=>{setNavigation({type:'task',id});setNavigationKey(v=>v+1);setTab('board')}}
          onOpenIncident={id=>{setNavigation({type:'incident',id});setNavigationKey(v=>v+1);setTab('incidents')}}
          onPlanning={()=>setTab('planning')}/>}
        {tab === 'planning' && <Planning key={`${projectId}-${navigationKey}`} me={me} openTaskId={navigation?.type==='task'?navigation.id:null}/>}
        {tab === 'admin' && isAdmin && <Admin key={projectId} />}
        {tab === 'settings' && <Settings key={projectId} me={me} onProjectsChanged={reloadProjects}
          onOpenProject={(id, view) => {switchProject(id);setTab(view)}} />}
      </div>
    </div>
  )
}

export function NotificationItem({notification:n,onOpen,onRead,onDelete}:{notification:Notification;onOpen:()=>void;onRead:()=>void;onDelete:()=>void}) {
  const kind=n.type.startsWith('incident_')?'блокер':n.type.startsWith('task_')?'задачу':'уведомление'
  return <div className={`dropdown-item ${n.read_at?'':'unread'}`}>
    <button className="notification-open" aria-label={`Открыть ${kind}: ${String(n.payload.title??'')}`} onClick={onOpen}>
      <span><TypeLabel type={n.type}/> {String(n.payload.title??'')}</span>
      {typeof n.payload.resolution==='string' && <span className="muted">Решение: {n.payload.resolution}</span>}
      <span className="muted">{fmtDate(n.created_at)} · Открыть →</span>
    </button>
    <div className="row notification-actions">
      {!n.read_at && <button className="small" onClick={onRead}>Прочитано</button>}
      <button className="small ghost" aria-label="Удалить уведомление" onClick={onDelete}>✕</button>
    </div>
  </div>
}

function BadgeCount({ n }: { n: number }) {
  return (
    <span
      style={{
        background: 'var(--accent)',
        color: '#111820',
        borderRadius: 10,
        padding: '0 6px',
        fontSize: 11,
        fontWeight: 700,
        marginLeft: 2,
      }}
    >
      {n}
    </span>
  )
}

function TypeLabel({ type }: { type: string }) {
  const map: Record<string, string> = {
    incident_yellow_created: '🟡 Блокер',
    incident_red_created: '🔴 Запрос эскалации',
    incident_red_confirmed: '🔴 Глобальная проблема',
    incident_resolved: '✅ Инцидент закрыт',
    task_assigned: '📌 Назначена задача',
    task_overdue: '⏰ Просрочена задача',
    situation_appeared: '🔎 Новая ситуация',
    situation_changed: '🔎 Изменение ситуации',
    situation_resolved: '✅ Ситуация разрешена',
    situation_reappeared: '🔎 Ситуация появилась снова',
    situation_reminder: '🔎 Напоминание о ситуации',
  }
  return <b>{map[type] ?? 'Уведомление'}</b>
}

function Login({ onLogin }: { onLogin: (me: Me) => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.login(login, password)
      const me = await api.me()
      onLogin(me)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Ошибка входа')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ maxWidth: 380, margin: '10vh auto', padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>
        <span style={{ color: 'var(--accent)' }}><img src="/aion.png" alt="" style={{width:32,height:32,objectFit:"contain",verticalAlign:"middle",marginRight:8}}/>Aion</span>
      </h2>
      <form onSubmit={submit} className="grid">
        <input placeholder="Логин" value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" />
        <input
          placeholder="Пароль"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
        {error && <div className="error">{error}</div>}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? 'Вход…' : 'Войти'}
        </button>
      </form>
    </div>
  )
}

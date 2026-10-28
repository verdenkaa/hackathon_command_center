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

type Tab = 'board' | 'planning' | 'incidents' | 'analytics' | 'admin' | 'settings'

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
  const [tab, setTab] = useState<Tab>('board')
  const [projectId, setProjectId] = useState(currentProject())
  const [projects, setProjects] = useState<Project[]>([])
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [notifOpen, setNotifOpen] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)
  const [navigation, setNavigation] = useState<{type:'task'|'incident';id:number;incident?:Incident}|null>(null)
  const [navigationKey, setNavigationKey] = useState(0)
  const [message, setMessage] = useState('')
  useEffect(()=>{
    const close=(e:PointerEvent)=>{if(!notifRef.current?.contains(e.target as Node))setNotifOpen(false)}
    const escape=(e:KeyboardEvent)=>{if(e.key==='Escape')setNotifOpen(false)}
    document.addEventListener('pointerdown',close)
    document.addEventListener('keydown',escape)
    return ()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',escape)}
  },[])

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null)).finally(() => setLoading(false))
  }, [])

  const reloadProjects = useCallback(() => {
    api.projects().then((items) => {
      setProjects(items)
      setProjectId((previous) => {
        const next = items.some((p) => p.id === previous) ? previous : items[0]?.id ?? 0
        setCurrentProject(next)
        return next
      })
      setProjectsLoaded(true)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!me) return
    reloadProjects()
  }, [me, reloadProjects])

  useEffect(() => {
    if (!me) return
    const load = () => api.notifications().then(setNotifications).catch(() => {})
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [me])

  if (loading) return <div style={{ padding: 24 }}>Загрузка…</div>
  if (!me) return <Login onLogin={(user) => {
    setTab('board')
    setProjects([])
    setProjectsLoaded(false)
    setMe(user)
  }} />

  const isAdmin = me.roles.some((r) => r.role === 'admin')
  const unread = notifications.filter((n) => !n.read_at).length

  if (projectsLoaded && projects.length === 0 && !isAdmin) return (
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
  }

  return (
    <div style={{ padding: '0 16px 24px' }}>
      <PlanningPreviewHost/>
      <div className="topbar" style={{ paddingTop: 12 }}>
        <span className="brand" style={{ color: 'var(--accent)' }}>Hackathon Command Center</span>
        <select className="project-select" value={projectId} onChange={(e) => switchProject(Number(e.target.value))}>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <nav className="tabs" style={{ margin: 0, borderBottom: 'none', flex: 1 }}>
          {TABS.filter((t) => t.key !== 'admin' || isAdmin).map((t) => (
            <button key={t.key} className={tab === t.key ? 'active' : ''} onClick={() => setTab(t.key)}>
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
        {message && <div role="status" className="card">{message}</div>}
        {tab === 'board' && <Board key={`${projectId}-${navigationKey}`} me={me} openTaskId={navigation?.type==='task'?navigation.id:null}
          onOpenIncident={id=>{setNavigation({type:'incident',id});setNavigationKey(v=>v+1);setTab('incidents')}}/>}
        {tab === 'incidents' && <Incidents key={`${projectId}-${navigationKey}`} me={me} initialIncident={navigation?.incident} openIncidentId={navigation?.type==='incident'?navigation.id:null} />}
        {tab === 'analytics' && <Analytics key={projectId} me={me}
          onOpenTask={id=>{setNavigation({type:'task',id});setNavigationKey(v=>v+1);setTab('board')}}
          onOpenIncident={id=>{setNavigation({type:'incident',id});setNavigationKey(v=>v+1);setTab('incidents')}}
          onPlanning={()=>setTab('planning')}/>}
        {tab === 'planning' && <Planning key={projectId} me={me}/>}
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
        <span style={{ color: 'var(--accent)' }}>Hackathon Command Center</span>
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

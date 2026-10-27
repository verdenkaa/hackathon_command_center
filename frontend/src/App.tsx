import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, Me, Notification, Project, currentProject, setCurrentProject } from './api'
import { fmtDate } from './ui'
import Board from './Board'
import { Incidents } from './Incidents'
import { Analytics } from './Analytics'
import { Admin } from './Admin'
import { Settings } from './Settings'

type Tab = 'board' | 'incidents' | 'analytics' | 'admin' | 'settings'

const TABS: { key: Tab; label: string }[] = [
  { key: 'board', label: 'Доска' },
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
    setCurrentProject(id)
    setProjectId(id)
    setTab('board')
  }

  return (
    <div style={{ padding: '0 16px 24px' }}>
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
        <div className="dropdown">
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
                  <div key={n.id} className={`dropdown-item ${n.read_at ? '' : 'unread'}`}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <div style={{ fontSize: 13 }}>
                        <TypeLabel type={n.type} /> {String(n.payload.title ?? '')}
                      </div>
                      <button
                        className="small ghost"
                        title="Удалить"
                        onClick={async () => {
                          await api.deleteNotification(n.id)
                          setNotifications((prev) => prev.filter((x) => x.id !== n.id))
                        }}
                      >
                        ✕
                      </button>
                    </div>
                    {typeof n.payload.resolution === 'string' && n.payload.resolution && (
                      <div className="muted" style={{ fontSize: 12 }}>Решение: {n.payload.resolution}</div>
                    )}
                    <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>{fmtDate(n.created_at)}</div>
                    {!n.read_at && (
                      <button
                        className="small"
                        style={{ marginTop: 4 }}
                        onClick={async () => {
                          await api.readNotification(n.id)
                          setNotifications((prev) =>
                            prev.map((x) => (x.id === n.id ? { ...x, read_at: 'now' } : x)),
                          )
                        }}
                      >
                        Прочитано
                      </button>
                    )}
                  </div>
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
        {tab === 'board' && <Board key={projectId} me={me} />}
        {tab === 'incidents' && <Incidents key={projectId} me={me} />}
        {tab === 'analytics' && <Analytics key={projectId} me={me} />}
        {tab === 'admin' && isAdmin && <Admin key={projectId} />}
        {tab === 'settings' && <Settings key={projectId} me={me} onProjectsChanged={reloadProjects}
          onOpenProject={(id, view) => {switchProject(id);setTab(view)}} />}
      </div>
    </div>
  )
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
  return <b>{map[type] ?? type}</b>
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

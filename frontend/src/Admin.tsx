import { useState } from 'react'
import { api, UserInfo } from './api'
import { Badge, Field, Modal, fmtDate, useLoad } from './ui'

type Section = 'users' | 'logins' | 'ip' | 'backups'

export function Admin() {
  const [section, setSection] = useState<Section>('users')

  return (
    <div>
      <div className="row" style={{ margin: '4px 0 12px' }}>
        <h3 style={{ margin: 0 }}>Администрирование</h3>
        <span className="grow" />
        {(['users', 'logins', 'ip', 'backups'] as Section[]).map((s) => (
          <button key={s} className={section === s ? 'primary' : ''} onClick={() => setSection(s)}>
            {{ users: 'Пользователи', logins: 'Журнал входов', ip: 'IP-ограничения', backups: 'Резервные копии' }[s]}
          </button>
        ))}
      </div>
      {section === 'users' && <Users />}
      {section === 'logins' && <Logins />}
      {section === 'ip' && <IpRules />}
      {section === 'backups' && <Backups />}
    </div>
  )
}

function Users() {
  const [users, error, reload] = useLoad<UserInfo[]>(api.users)
  const [roles, , reloadRoles] = useLoad<{ id: number; user_id: number; role: string; project_id: number | null }[]>(api.roles)
  const [createOpen, setCreateOpen] = useState(false)

  const rolesOf = (id: number) => (roles ?? []).filter((r) => r.user_id === id)

  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}>
        <button className="primary" onClick={() => setCreateOpen(true)}>+ Пользователь</button>
      </div>
      {error && <div className="error">{error}</div>}
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Логин</th><th>Имя</th><th>Telegram</th><th>Роли</th><th>Статус</th><th>Действия</th>
          </tr>
        </thead>
        <tbody>
          {(users ?? []).map((u) => (
            <tr key={u.id}>
              <td>{u.id}</td>
              <td>{u.login}</td>
              <td>{u.display_name}</td>
              <td>{u.telegram_username ?? '—'}</td>
              <td>
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  {rolesOf(u.id).map((r) => (
                    <span key={r.id} className="row" style={{ gap: 4 }}>
                      <Badge kind={r.role === 'admin' ? 'red' : r.role === 'captain' ? 'yellow' : 'blue'}>{r.role}</Badge>
                      <button
                        className="small ghost"
                        title="Отозвать роль"
                        onClick={async () => {
                          if (confirm(`Отозвать роль ${r.role} у ${u.login}?`)) {
                            await api.revokeRole(r.id)
                            reloadRoles()
                          }
                        }}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              </td>
              <td>
                <Badge kind={u.active ? 'green' : 'gray'}>{u.active ? 'активен' : 'отключён'}</Badge>
              </td>
              <td>
                <div className="row">
                  {!rolesOf(u.id).some((r) => r.role === 'participant') && (
                    <button className="small" onClick={async () => { await api.assignRole(u.id, 'participant'); reloadRoles() }}>участник</button>
                  )}
                  {!rolesOf(u.id).some((r) => r.role === 'captain') && (
                    <button className="small" onClick={async () => { await api.assignRole(u.id, 'captain'); reloadRoles() }}>капитан</button>
                  )}
                  {!rolesOf(u.id).some((r) => r.role === 'admin') && (
                    <button className="small" onClick={async () => { await api.assignRole(u.id, 'admin'); reloadRoles() }}>админ</button>
                  )}
                  {u.active && (
                    <button
                      className="small"
                      onClick={async () => {
                        const pw = prompt('Новый пароль (или Отмена):')
                        if (pw) {
                          await api.resetPassword(u.id, pw)
                          reload()
                        }
                      }}
                    >
                      пароль
                    </button>
                  )}
                  {u.active && (
                    <button
                      className="small danger"
                      onClick={async () => {
                        if (confirm(`Деактивировать ${u.login}? Сессии и роли будут отозваны.`)) {
                          await api.deactivateUser(u.id)
                          reload()
                        }
                      }}
                    >
                      отключить
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {createOpen && (
        <CreateUser
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false)
            reload()
          }}
        />
      )}
    </div>
  )
}

function CreateUser({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [telegram, setTelegram] = useState('')
  const [error, setError] = useState('')

  async function submit() {
    setError('')
    try {
      await api.createUser({
        login, password, display_name: name, telegram_username: telegram || null,
      })
      onCreated()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Modal title="Новый пользователь" onClose={onClose}>
      <Field label="Логин *"><input value={login} onChange={(e) => setLogin(e.target.value)} /></Field>
      <Field label="Пароль *"><input value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
      <Field label="Имя"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Telegram username"><input value={telegram} onChange={(e) => setTelegram(e.target.value)} /></Field>
      {error && <div className="error">{error}</div>}
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
        <button onClick={onClose}>Отмена</button>
        <button className="primary" onClick={submit} disabled={!login || !password}>Создать</button>
      </div>
    </Modal>
  )
}

function Logins() {
  const [events] = useLoad(api.loginEvents)
  return (
    <table>
      <thead>
        <tr><th>Время</th><th>Логин</th><th>IP</th><th>Результат</th><th>Причина</th></tr>
      </thead>
      <tbody>
        {(events ?? []).slice(0, 100).map((e) => (
          <tr key={e.id}>
            <td>{fmtDate(e.created_at)}</td>
            <td>{e.login}</td>
            <td className="mono">{e.ip ?? '—'}</td>
            <td><Badge kind={e.success ? 'green' : 'red'}>{e.success ? 'успех' : 'отказ'}</Badge></td>
            <td className="muted">{e.reason ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function IpRules() {
  const [ip, setIp] = useState('')
  const [msg, setMsg] = useState('')
  return (
    <div className="card" style={{ maxWidth: 480 }}>
      <div className="section-title">Чёрный список и сброс лимитов</div>
      <div className="row">
        <input placeholder="IP-адрес" value={ip} onChange={(e) => setIp(e.target.value)} />
        <button onClick={async () => { await api.blockIp(ip); setMsg(`IP ${ip} заблокирован`); setIp('') }}>Заблокировать</button>
        <button onClick={async () => { await api.resetIpLimit(ip); setMsg(`Лимит для ${ip} сброшен`); setIp('') }}>Сбросить лимит</button>
      </div>
      {msg && <div style={{ marginTop: 8 }}>{msg}</div>}
    </div>
  )
}

function Backups() {
  const [backups, error, reload] = useLoad(api.backups)
  const [msg, setMsg] = useState('')
  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}>
        <button className="primary" onClick={async () => { await api.createBackup(); reload(); setMsg('Бэкап создан') }}>Создать бэкап</button>
        <button onClick={async () => { await api.runJobs(); setMsg('Фоновые задачи запущены') }}>Запустить фоновые задачи</button>
      </div>
      {msg && <div style={{ marginBottom: 8 }}>{msg}</div>}
      {error && <div className="error">{error}</div>}
      <table>
        <thead>
          <tr><th>ID</th><th>Создан</th><th>Тип</th><th>Действие</th></tr>
        </thead>
        <tbody>
          {(backups ?? []).map((b) => (
            <tr key={b.id}>
              <td>{b.id}</td>
              <td>{fmtDate(b.created_at)}</td>
              <td><Badge kind={b.kind === 'safety' ? 'yellow' : b.kind === 'manual' ? 'blue' : 'gray'}>{b.kind}</Badge></td>
              <td>
                <button
                  className="small danger"
                  onClick={async () => {
                    if (confirm('Восстановить из этой копии? Текущее состояние будет сохранено в защитную копию.')) {
                      await api.restoreBackup(b.id)
                      setMsg('Восстановление выполнено. Данные возвращены к выбранной копии.')
                    }
                  }}
                >
                  Восстановить
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

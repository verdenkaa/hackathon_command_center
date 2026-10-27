import { useState } from 'react'
import { api } from './api'
import { Badge, fmtDate, useLoad } from './ui'

interface Run {
  id: number
  scenario: string
  status: string
  logs: string[]
  created_at: string
}

export function Sandbox({ onProjectsChanged }: { onProjectsChanged: () => void }) {
  const [scenarios, error] = useLoad<Record<string, string>>(api.sandboxScenarios)
  const [runs, , reloadRuns] = useLoad<Run[]>(api.sandboxRuns)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')

  async function run(scenario: string) {
    setBusy(scenario)
    setMsg('')
    try {
      const r = await api.sandboxRun(scenario)
      setMsg(`Сценарий «${scenario}» выполнен: ${(r as { logs?: string[] }).logs?.join('; ') ?? ''}`)
      onProjectsChanged()
      reloadRuns()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div>
      <div className="row" style={{ margin: '4px 0 12px' }}>
        <h3 style={{ margin: 0 }}>Песочница</h3>
        <Badge kind="blue">тестовый режим</Badge>
      </div>

      <div className="card" style={{ marginBottom: 16, maxWidth: 760 }}>
        <div className="section-title">Как это работает</div>
        <p style={{ fontSize: 13, margin: 0 }}>
          Песочница работает в <b>отдельном проекте «Sandbox»</b> и не затрагивает рабочий проект.
          Сценарии создают аккаунты <span className="mono">alice</span>, <span className="mono">bob</span>,{' '}
          <span className="mono">cap</span> (пароль <span className="mono">sandbox-pass</span>) и выполняют
          действия от их имени. Чтобы увидеть результат — <b>переключись на проект «Sandbox» в списке сверху</b>.
          Внешние сервисы (Telegram/ИИ) не вызываются.
        </p>
      </div>

      {error && <div className="error">{error}</div>}
      {msg && <div className="card" style={{ marginBottom: 12, borderColor: 'var(--ok)' }}>{msg}</div>}

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12, marginBottom: 16 }}>
        {Object.entries(scenarios ?? {}).map(([name, desc]) => (
          <div key={name} className="card">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <b className="mono" style={{ fontSize: 13 }}>{name}</b>
              <button className="primary small" disabled={busy !== ''} onClick={() => run(name)}>
                {busy === name ? 'Выполняю…' : 'Запустить'}
              </button>
            </div>
            <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>{desc}</div>
          </div>
        ))}
      </div>

      <div className="section-title">Журнал запусков</div>
      <div className="grid" style={{ gap: 6 }}>
        {(runs ?? []).slice(0, 30).map((r) => (
          <div key={r.id} className="card" style={{ padding: 8 }}>
            <div className="row">
              <b className="mono" style={{ fontSize: 12 }}>{r.scenario}</b>
              <Badge kind={r.status === 'ok' ? 'green' : 'red'}>{r.status}</Badge>
              <span className="muted" style={{ fontSize: 11 }}>{fmtDate(r.created_at)}</span>
            </div>
            {r.logs.map((l, i) => (
              <div key={i} style={{ fontSize: 12, marginTop: 2 }}>· {l}</div>
            ))}
          </div>
        ))}
        {(runs ?? []).length === 0 && <div className="muted">Запусков ещё не было</div>}
      </div>
    </div>
  )
}

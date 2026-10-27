import { useState } from 'react'
import { api, AiPreview } from './api'
import { Field } from './ui'

export const AI_TRIGGERS: Record<string, string> = {
  red_confirmed: 'Подтверждена красная эскалация',
  blocker_created: 'Создан блокер',
  blocker_closed: 'Закрыт блокер',
  overdue: 'Задача просрочена',
  deadline_6h: 'До дедлайна не больше 6 часов',
}

export function AiRequestView({ context }: { context: AiPreview }) {
  return <pre style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere', maxHeight:360, overflowY:'auto', fontSize:12}}>
    {JSON.stringify(context, null, 2)}
  </pre>
}

export function MockAi({ onRun }: { onRun: () => void }) {
  const [question, setQuestion] = useState('')
  const [trigger, setTrigger] = useState('manual')
  const [context, setContext] = useState<AiPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run(save: boolean) {
    setBusy(true)
    setError('')
    try {
      const preview = await api.previewAi(question, trigger)
      setContext(preview)
      if (save) {
        await api.runAi(question, trigger)
        onRun()
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <div style={{marginTop:12}}>
    <p className="muted">Мок ИИ: внешних запросов нет. Ответ формируется по правилам и не интерпретирует промпт.
      Здесь можно проверить полный запрос; промпт и события меняются в настройках ИИ.</p>
    <Field label="Вопрос / дополнительный контекст">
      <textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={5000} />
    </Field>
    <Field label="Причина запуска">
      <select value={trigger} onChange={(e) => setTrigger(e.target.value)}>
        <option value="manual">Ручной запрос</option>
        {Object.entries(AI_TRIGGERS).map(([key,label]) => <option key={key} value={key}>{label}</option>)}
      </select>
    </Field>
    <div className="row">
      <button disabled={busy} onClick={() => run(false)}>Показать контекст запроса</button>
      <button className="primary" disabled={busy} onClick={() => run(true)}>{busy ? 'Подготовка…' : 'Запросить мок-анализ'}</button>
    </div>
    {error && <div className="error" role="alert">{error}</div>}
    {context && <details open><summary>Запрос, который получил бы ИИ · mock</summary><AiRequestView context={context}/></details>}
  </div>
}

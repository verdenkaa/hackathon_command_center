import {useEffect, useState} from 'react'
import {api, AdvisorJob, AdvisorQuota, Recommendation, RelatedObjects, ProviderSettings} from './api'
import {Badge, Field, fmtDate, useLoad} from './ui'

const STATUS:Record<string,string>={unreviewed:'Не рассмотрена',accepted:'Принята',rejected:'Отклонена',deferred:'Отложена'}
const ERRORS:Record<string,string>={AI_DISABLED:'ИИ выключен или проект завершён',KEY_MISSING:'Ключ не задан',KEY_UNAVAILABLE:'Не удалось открыть ключ Windows',CONTEXT_TOO_LARGE:'Минимальный контекст превышает лимит',DAILY_LIMIT:'Дневной бюджет исчерпан',MINUTE_LIMIT:'Ожидание минутного окна',INVALID_RESPONSE:'Ответ не прошёл проверку структуры или связанных объектов',PROVIDER_AUTH:'Проверьте ключ и права Google',PROVIDER_CONFIG:'Проверьте модель и настройки запроса',PROVIDER_DAILY_LIMIT:'Google сообщил об исчерпании дневной квоты',PROVIDER_RATE_LIMIT:'Google ограничил частоту запросов',TEMPORARY:'Временная ошибка сервиса или сети',INTERRUPTED:'Запрос прерван; результат неизвестен, попытка учтена',SDK_MISSING:'SDK Gemini не установлен'}
const STATE:Record<string,string>={queued:'В очереди',waiting:'Ожидание',running:'Анализ…',succeeded:'Готово',failed:'Ошибка',cancelled:'Отменён'}
type LinksProps={onOpenTask:(id:number)=>void;onOpenIncident:(id:number)=>void;onPlanning:()=>void}

function ObjectLinks({related,...links}:{related:RelatedObjects}&LinksProps) {
  return <div className="scan-actions">
    {related.task_ids.map(id=><button className="small" key={`t${id}`} onClick={()=>links.onOpenTask(id)}>Задача #{id}</button>)}
    {related.incident_ids.map(id=><button className="small" key={`i${id}`} onClick={()=>links.onOpenIncident(id)}>Инцидент #{id}</button>)}
    {related.track_ids.map(id=><a key={`l${id}`} href={`#advisor-track-${id}`}>Трек #{id}</a>)}
    {related.user_ids.map(id=><a key={`u${id}`} href={`#advisor-user-${id}`}>Участник #{id}</a>)}
    <button className="small" onClick={links.onPlanning}>Планирование</button>
  </div>
}

export function AdviceCard({rec:r,canManage,onChange,...links}:{rec:Recommendation;canManage:boolean;onChange:()=>void}&LinksProps) {
  const [decision,setDecision]=useState(r.status)
  const [comment,setComment]=useState(r.comment)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const a=r.structured
  const stale=!!r.snapshot_at && Date.now()-new Date(r.snapshot_at+'Z').getTime()>30*60000
  async function change(action:()=>Promise<unknown>) {
    setBusy(true);setError('')
    try{await action();onChange()}catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <article className={`advisor-advice significance-${a?.significance??'info'}`}>
    <div className="scan-heading"><strong>{r.summary}</strong><Badge kind={r.status==='accepted'?'green':r.status==='rejected'?'gray':'blue'}>{STATUS[r.status]??r.status}</Badge></div>
    <p className="muted">{r.trigger==='automatic'?'Автоматически':'Вручную'} · {fmtDate(r.created_at)} · {a?{info:'Информация',warning:'Требует внимания',critical:'Высокая значимость'}[a.significance]:'Старая мок-рекомендация'}</p>
    {a?<dl><dt>Ситуация</dt><dd>{a.situation}</dd><dt>Основания</dt><dd>{a.grounds.join(' · ')}</dd><dt>Возможное последствие</dt><dd>{a.consequence}</dd><dt>Действие</dt><dd>{a.action}</dd><dt>Ограничения</dt><dd>{a.limitations.join(' · ')}</dd></dl>:<p>{r.content}</p>}
    {a&&<ObjectLinks related={a.related} {...links}/>}
    {r.snapshot_at&&<p className="muted" title={`Версия: ${r.snapshot_version}`}>Снимок: {fmtDate(r.snapshot_at)}</p>}
    {(stale||a?.freshness==='uncertain')&&<p className="advisor-warning">Данные могли устареть или имеют неполный охват. Проверьте текущее состояние.</p>}
    {r.comment&&<p>Решение команды: {r.comment}{r.status_by?` · ${r.status_by_name??`участник #${r.status_by}`}`:''}{r.status_at?` · ${fmtDate(r.status_at)}`:''}</p>}
    {r.status==='accepted'&&<p className="muted">Принятие совета не означает, что действие выполнено.</p>}
    <p className="muted">{r.excluded?'Исключена из контекста':'Учитывается при следующем анализе'}</p>
    {canManage&&<details><summary>Изменить решение</summary><div className="advisor-controls">
      <Field label="Статус"><select value={decision} onChange={e=>setDecision(e.target.value)}>{Object.entries(STATUS).map(([k,v])=><option value={k} key={k}>{v}</option>)}</select></Field>
      <Field label="Комментарий команды (необязательно)"><textarea value={comment} maxLength={2000} rows={2} onChange={e=>setComment(e.target.value)}/></Field>
      <button disabled={busy} onClick={()=>change(()=>api.decideAdvice(r.id,decision,comment))}>Сохранить решение</button>
      <button disabled={busy} onClick={()=>change(()=>api.excludeRecommendation(r.id))}>{r.excluded?'Вернуть в контекст':'Исключить из контекста'}</button>
    </div></details>}
    {error&&<p role="alert" className="error">{error}</p>}
  </article>
}

export function Advisor({canManage,...links}:{canManage:boolean}&LinksProps) {
  const [settings,settingsError,reloadSettings]=useLoad(api.aiSettings)
  const [quota,quotaError,reloadQuota]=useLoad<AdvisorQuota>(api.advisorQuota)
  const [jobs,jobsError,reloadJobs]=useLoad<AdvisorJob[]>(api.advisorJobs)
  const [recs,recsError,reloadRecs]=useLoad<Recommendation[]>(api.recommendations)
  const [question,setQuestion]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  function refresh(){reloadQuota();reloadJobs();reloadRecs();reloadSettings()}
  useEffect(()=>{const timer=setInterval(()=>{reloadQuota();reloadJobs();reloadRecs();reloadSettings()},3000);return()=>clearInterval(timer)},[reloadQuota,reloadJobs,reloadRecs,reloadSettings])
  const pending=(jobs??[]).some(j=>['queued','waiting','running'].includes(j.state))
  const disabled=busy||!settings?.enabled||!quota?.key_saved||!quota?.vault_available||!quota.day_remaining
  async function run(kind:'analysis'|'question'){
    setBusy(true);setError('')
    try{await api.askAdvisor(kind,kind==='question'?question:'');if(kind==='question')setQuestion('');refresh()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const lastAnalysis=(jobs??[]).find(j=>j.kind==='analysis')
  return <section className="card advisor-panel">
    <div className="scan-heading"><h3>Argus</h3><Badge kind={settings?.enabled?'blue':'gray'}>{settings?.enabled?'Gemini':'Выключен'}</Badge></div>
    {quota&&<div className={`advisor-budget ${quota.day_remaining<Math.max(10,quota.day_limit*.1)?'advisor-warning':''}`}>
      Примерный дневной остаток платформы: <strong>{quota.day_remaining} / {quota.day_limit}</strong>
      <span>До сброса: {Math.ceil(quota.reset_seconds/60)} мин · {fmtDate(quota.reset_at)} МСК</span>
      <span>Минутное окно: {quota.minute_used} / {quota.minute_limit} запросов · {quota.minute_tokens} / {quota.token_limit} входных токенов</span>
      <small>Счётчик общий для платформы; доступность и квоты Google могут отличаться.</small>
    </div>}
    {!settings?.enabled&&<p className="muted">ИИ выключен. Капитан или администратор может включить его в настройках.</p>}
    {quota&&!quota.vault_available&&<p role="alert">Защищённое хранилище Windows недоступно.</p>}
    {quota&&!quota.key_saved&&<p className="advisor-warning">Argus: ключ Gemini задаётся, заменяется и удаляется в Ouroboros Daemon. После изменения перезапустите Aion.</p>}
    {quota?.day_remaining===0&&<p className="advisor-warning">Дневной бюджет исчерпан. Дождитесь сброса.</p>}
    {!canManage&&<p className="muted">Рекомендации доступны всей команде. Запросы и решения доступны капитану и администратору.</p>}
    {canManage&&<button className="primary" disabled={disabled} onClick={()=>run('analysis')}>{busy?'Отправка…':'Запросить рекомендации'}</button>}
    <p className="muted">Последний анализ: {lastAnalysis?`${fmtDate(lastAnalysis.created_at)} · ${STATE[lastAnalysis.state]}`:'ещё не запускался'}</p>
    {lastAnalysis?.answer?.result==='no_new_recommendations'&&<p role="status">Новых значимых рекомендаций нет. Это не гарантирует завершение проекта в срок.</p>}
    {settings?.auto_enabled&&<p className="muted">Следующий автоанализ: {fmtDate(settings.next_run_at)} · только во время проекта</p>}
    {pending&&<p role="status">Запросы ожидают выполнения. Ручные вопросы имеют приоритет перед автоанализом.</p>}
    {(jobs??[]).filter(j=>j.state!=='succeeded').slice(0,5).map(j=><div role={j.state==='failed'?'alert':'status'} key={j.id}>#{j.id} · {j.kind==='question'?'Вопрос':'Анализ'} · {STATE[j.state]}{j.error_code?` · ${ERRORS[j.error_code]??'Не удалось выполнить запрос'}`:''}{j.state==='waiting'?` · повтор не раньше ${fmtDate(j.next_attempt_at)}`:''}{canManage&&j.state==='failed'&&<button className="small" disabled={disabled} onClick={async()=>{try{await api.askAdvisor(j.kind as 'analysis'|'question',j.question);refresh()}catch(e){setError((e as Error).message)}}}>Повторить запрос</button>}</div>)}
    {(error||settingsError||quotaError||jobsError||recsError)&&<p className="error" role="alert">{error||settingsError||quotaError||jobsError||recsError}<button onClick={refresh}>Обновить</button></p>}
    <div className="advisor-list">{(recs??[]).map(r=><AdviceCard key={`${r.id}-${r.status_at}-${r.excluded}`} rec={r} canManage={canManage} onChange={refresh} {...links}/>)}</div>
    {recs?.length===0&&<p className="muted">Рекомендаций пока нет.</p>}
    <section className="advisor-question"><h4>Вопрос по проекту</h4>
      {canManage&&<><Field label="Ваш вопрос"><textarea value={question} onChange={e=>setQuestion(e.target.value)} maxLength={5000} rows={3}/></Field><button disabled={disabled||!question.trim()} onClick={()=>run('question')}>Спросить помощника</button></>}
      {(jobs??[]).filter(j=>j.kind==='question'&&j.state==='succeeded'&&j.answer).slice(0,10).map(j=><article className="advisor-answer" key={j.id}><strong>{j.question}</strong><p style={{whiteSpace:'pre-wrap'}}>{j.answer?.answer}</p><p>Основания: {j.answer?.grounds?.join(' · ')}</p><p className="muted">Ограничения: {j.answer?.limitations?.join(' · ')}</p>{j.answer?.related&&<ObjectLinks related={j.answer.related} {...links}/>}<small title={`Версия: ${j.snapshot_version}`}>Снимок: {fmtDate(j.snapshot_at)}</small></article>)}
    </section>
  </section>
}

export function AdvisorProviderSettings() {
  const [saved,error,reload]=useLoad<ProviderSettings>(api.providerSettings)
  const [draft,setDraft]=useState<Partial<ProviderSettings>>({})
  const [msg,setMsg]=useState('')
  if(!saved)return <p role={error?'alert':'status'}>{error||'Загрузка настроек Gemini…'}</p>
  async function save(){try{await api.patchProvider(draft);setDraft({});reload();setMsg('Настройки Gemini сохранены')}catch(e){setMsg((e as Error).message)}}
  return <section className="card section"><h4>Argus · Gemini и лимиты</h4><p>{saved.key_saved?'Ключ сохранён':'Ключ не задан'} · {saved.vault_available?'Хранилище Windows доступно':'Хранилище недоступно'}</p>
    <p className="muted">Argus: ключ Gemini задаётся, заменяется и удаляется в Ouroboros Daemon. После изменения перезапустите Aion.</p>
    <Field label="Модель"><input value={draft.model??saved.model} onChange={e=>setDraft({...draft,model:e.target.value})}/></Field>
    {(['rpm','rpd','tpm','max_attempts','max_input_tokens'] as const).map(key=><Field key={key} label={{rpm:'Запросов в минуту',rpd:'Запросов в день',tpm:'Входных токенов в минуту',max_attempts:'Максимум попыток',max_input_tokens:'Максимум входных токенов запроса'}[key]}><input type="number" min={1} value={draft[key]??saved[key]} onChange={e=>setDraft({...draft,[key]:Number(e.target.value)})}/></Field>)}
    <p className="muted">Проверьте значения в Google AI Studio. Порог 90% применяется к сумме входных токенов минутного окна.</p>
    <button disabled={!Object.keys(draft).length} onClick={save}>Сохранить общие лимиты</button>{msg&&<p role="status">{msg}</p>}
  </section>
}

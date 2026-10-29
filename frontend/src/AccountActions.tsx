import {useEffect,useState} from 'react'
import {api,DeletionPreview,UserInfo} from './api'
import {Field,Modal} from './ui'

export function EditTelegram({user,onClose,onSaved}:{user:UserInfo;onClose:()=>void;onSaved:()=>void}) {
  const [value,setValue]=useState(user.telegram_username||'')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  return <Modal title={`Telegram · ${user.display_name}`} onClose={onClose}>
    <form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await api.patchUser(user.id,{telegram_username:value.trim()||null});onSaved()}catch(err){setError((err as Error).message)}finally{setBusy(false)}}}>
      <Field label="Telegram username"><input autoFocus value={value} onChange={e=>setValue(e.target.value)} placeholder="@username или username"/></Field>
      <p className="muted">5–32 латинских символа, цифры и подчёркивание, начало с буквы. Пустое поле очищает значение. Это не подтверждённая привязка аккаунта.</p>
      {error&&<p className="error" role="alert">{error}</p>}
      <div className="row"><button type="button" disabled={busy} onClick={()=>setValue('')}>Очистить</button><button className="primary" disabled={busy}>Сохранить</button></div>
    </form>
  </Modal>
}

const LINK_LABELS:Record<string,string>={role_assignments:'Роли',sessions:'Сессии входа',notifications:'Личные уведомления',
  document_locks:'Блокировки документов',completion_votes:'Голоса за завершение',incident_events:'История инцидентов',
  incidents:'Авторство и ответственность инцидентов',documents:'Авторство документов',audit_entries:'Журнал действий',
  audit_revisions:'Правки журнала',planning_baselines:'Снимки планирования',advisor_jobs:'Запросы ИИ',
  ai_recommendations:'Решения по рекомендациям ИИ',ip_rules:'Правила IP',login_events:'История входов',
  task_assignees:'Назначения задач',sandbox_runs:'История проверок'}

export function DeleteAccount({user,onClose,onDeleted}:{user:UserInfo;onClose:()=>void;onDeleted:()=>void}) {
  const [preview,setPreview]=useState<DeletionPreview|null>(null)
  const [captains,setCaptains]=useState<Record<number,number>>({})
  const [primaries,setPrimaries]=useState<Record<number,number>>({})
  const [confirmed,setConfirmed]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  async function load(){
    setBusy(true);setError('');setConfirmed(false)
    try{const p=await api.deletionPreview(user.id);setPreview(p);setCaptains(Object.fromEntries(p.projects.filter(v=>v.captains.length).map(v=>[v.id,v.captains[0].id])));setPrimaries({})}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[user.id])
  const ready=preview&&!preview.blocked&&preview.tasks.filter(t=>t.needs_primary).every(t=>primaries[t.id])&&preview.projects.every(p=>captains[p.id])
  const counts:Record<string,number>={}
  Object.entries(preview?.links||{}).forEach(([key,n])=>{const label=LINK_LABELS[key.split('.')[0]]||'Другие исторические ссылки';counts[label]=(counts[label]||0)+n})
  return <Modal title={`Полное удаление · ${user.display_name}`} onClose={onClose}>
    <p className="error">Удаление аккаунта #{user.id} необратимо. Задачи и инциденты сохранятся во всех проектах.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    {!preview?<p>Загрузка обзора…</p>:<>
      <h4>Назначения задач ({preview.tasks.length})</h4>
      {!preview.tasks.length&&<p className="muted">Назначений нет.</p>}
      {preview.tasks.map(task=><div className="telegram-delivery" key={task.id}>
        <strong>{task.project} · задача #{task.id}: {task.title}</strong>
        <p>{task.remaining.length?`Останутся: ${task.remaining.map(a=>a.name).join(', ')}.`:'Останется без исполнителя.'} Новые участники не назначаются. Таймеры и сроки сохраняются.</p>
        {task.needs_primary&&<Field label="Выберите основного из оставшихся исполнителей"><select value={primaries[task.id]||''} onChange={e=>{setPrimaries({...primaries,[task.id]:Number(e.target.value)});setConfirmed(false)}}><option value="">Выберите исполнителя</option>{task.remaining.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>}
      </div>)}
      <h4>Открытые инциденты</h4>
      {!preview.projects.length&&<p className="muted">Открытых инцидентов под ответственностью аккаунта нет.</p>}
      {preview.projects.map(project=><div className="telegram-delivery" key={project.id}>
        <strong>{project.name}</strong>
        <ul>{project.incidents.map(i=><li key={i.id}>#{i.number}: {i.title}</li>)}</ul>
        {!project.captains.length?<p className="error">Удаление заблокировано: сначала назначьте активного капитана этого проекта.</p>:<Field label="Новый ответственный за перечисленные инциденты"><select value={captains[project.id]||''} onChange={e=>{setCaptains({...captains,[project.id]:Number(e.target.value)});setConfirmed(false)}}>{project.captains.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>}
      </div>)}
      <h4>Другие связи</h4>
      <ul>{Object.entries(counts).map(([label,n])=><li key={label}>{label}: {n}</li>)}</ul>
      <p className="muted">Роли, сессии, личные уведомления, блокировки и голоса удаляются. Авторство, закрытые инциденты и история сохраняются с обозначением «Удалённый пользователь».</p>
      <p className="muted">{preview.deletion_limits}</p>
      <label className="row"><input type="checkbox" style={{width:'auto'}} checked={confirmed} disabled={busy||!ready} onChange={e=>setConfirmed(e.target.checked)}/>Подтверждаю необратимое удаление аккаунта и выбранные замены</label>
      <div className="row" style={{marginTop:16}}>
        <button disabled={busy} onClick={load}>Обновить обзор</button>
        <button className="danger" disabled={busy||!ready||!confirmed} onClick={async()=>{
          setBusy(true);setError('')
          try{await api.deleteUser(user.id,{confirm:true,preview_version:preview.version,incident_captains:captains,task_primaries:primaries});onDeleted()}
          catch(e){setError((e as Error).message);setConfirmed(false)}finally{setBusy(false)}
        }}>Удалить аккаунт навсегда</button>
      </div>
    </>}
  </Modal>
}

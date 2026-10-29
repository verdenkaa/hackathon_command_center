import {useEffect,useState} from 'react'
import {api, TelegramSettingsData, Delivery, currentProject} from './api'
import {Badge,Field,fmtDate} from './ui'

const STATES:Record<string,string>={pending:'ожидает',sending:'отправляется',sent:'отправлено',error:'ошибка',uncertain:'результат неизвестен'}

export function TelegramSettings({isAdmin}:{isAdmin:boolean}) {
  const [saved,setSaved]=useState<TelegramSettingsData|null>(null)
  const [chat,setChat]=useState('')
  const [url,setUrl]=useState('')
  const [routes,setRoutes]=useState<Record<string,number|null>>({})
  const [deliveries,setDeliveries]=useState<Delivery[]>([])
  const [testThread,setTestThread]=useState('')
  const [error,setError]=useState('')
  const [message,setMessage]=useState('')
  const [busy,setBusy]=useState(false)
  const project=currentProject()
  useEffect(()=>{
    let live=true
    api.telegramSettings().then(value=>{if(live){setSaved(value);setChat(value.chat_id||'');setRoutes(value.routes);setUrl(value.public_url)}}).catch(e=>{if(live)setError(e.message)})
    const history=()=>api.telegramDeliveries().then(v=>{if(live)setDeliveries(v)}).catch(e=>{if(live)setError(e.message)})
    history()
    const interval=window.setInterval(history,4000)
    return ()=>{live=false;window.clearInterval(interval)}
  },[project])
  async function act(action:()=>Promise<unknown>,success:string) {
    setBusy(true);setError('');setMessage('')
    try {await action();setMessage(success);setDeliveries(await api.telegramDeliveries())}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const dirty=!!saved&&(chat.trim()!==(saved.chat_id||'')||url!==saved.public_url||JSON.stringify(routes)!==JSON.stringify(saved.routes))
  return <section className="card section telegram-settings">
    <div className="section-title">Telegram · проект #{project}</div>
    {error&&<p className="error" role="alert">{error}</p>}
    {message&&<p role="status">{message}</p>}
    {!saved?<p>Загрузка настроек…</p>:<>
      <div className="row"><Badge kind={saved.bot_connected?'green':'gray'}>Бот {saved.bot_connected?'подключён':'не подключён'}</Badge><Badge kind={saved.chat_id?'blue':'gray'}>{saved.chat_id?`Чат ${saved.chat_id}`:'Чат не выбран'}</Badge></div>
      {isAdmin&&<details style={{margin:'12px 0'}}><summary>Подключение одного бота платформы</summary>
        <p>Создайте бота через @BotFather. На компьютере сервера запустите <code>telegram-key.bat</code>, войдите как администратор и введите токен скрытым вводом. Повторный запуск заменяет токен. Не вводите токен в чат или настройки проекта.</p>
        <p className="muted">Защита Windows DPAPI под учётной записью сервера. Токен не включается в резервные копии платформы.</p>
        <button className="small danger" disabled={busy||!saved.bot_connected} onClick={()=>{
          if(confirm('Удалить токен общего бота? Отправка для всех проектов остановится. Очередь сохранится.'))act(async()=>{await api.deleteTelegramKey();setSaved({...saved,bot_connected:false})},'Токен удалён')
        }}>Удалить токен бота</button>
        <button className="small" disabled={busy} onClick={()=>act(async()=>{setSaved(await api.telegramSettings())},'Состояние обновлено')}>Обновить состояние</button>
      </details>}
      <p className="muted">Добавьте бота в тестовый чат и разрешите отправку. Введите числовой ID чата и ID нужных тем вручную. Чат без тем: выберите «Общий чат». Автоматического списка всех тем Telegram нет.</p>
      <Field label="ID чата текущего проекта"><input value={chat} placeholder="-100…" onChange={e=>setChat(e.target.value)}/></Field>
      <Field label="Адрес платформы для команды (необязательно)"><input value={url} placeholder="https://… или сетевой адрес" onChange={e=>setUrl(e.target.value)}/></Field>
      <p className="muted">{saved.queue_policy} Ожидает при последней загрузке: {saved.pending}.</p>
      <div className="telegram-routes">{Object.entries(saved.events).map(([key,label])=>{
        const route=routes[key]
        return <div className="telegram-route" key={key}><label htmlFor={`route-${key}`}>{label}</label><select id={`route-${key}`} value={route==null?'off':route===0?'general':'topic'} onChange={e=>setRoutes({...routes,[key]:e.target.value==='off'?null:e.target.value==='general'?0:1})}>
          <option value="off">Выключено</option><option value="general">Общий чат</option><option value="topic">Тема по ID</option>
        </select>{route!=null&&route>0&&<input aria-label={`ID темы: ${label}`} type="number" min="1" max="2147483647" value={route} onChange={e=>setRoutes({...routes,[key]:Number(e.target.value)})}/>}</div>
      })}</div>
      <p className="muted">Отдельные рекомендации ИИ могут дублировать полный отчёт, если включены оба маршрута. Без выбранного маршрута отправки нет.</p>
      <button className="primary" disabled={busy||!dirty} onClick={()=>{
        const changed=chat.trim()!==(saved.chat_id||'')
        if(changed&&!confirm(`Подтвердить чат ${chat||'не выбран'} для проекта #${project}? Ожидающие сообщения сохранят старые направления.`))return
        act(async()=>{const value=await api.saveTelegram({chat_id:chat.trim()||null,routes,public_url:url,confirm_chat:changed});setSaved(value);setRoutes(value.routes);setUrl(value.public_url);setChat(value.chat_id||'')},'Настройки Telegram сохранены')
      }}>Сохранить Telegram</button>
      <hr/>
      <Field label="ID темы для теста (пусто — общий чат)"><input type="number" min="1" value={testThread} onChange={e=>setTestThread(e.target.value)}/></Field>
      <button disabled={busy||dirty||!saved.chat_id||!saved.bot_connected} onClick={()=>{
        if(confirm(`Отправить ТЕСТОВОЕ сообщение проекта #${project} в чат ${saved.chat_id}, ${testThread?`тема ${testThread}`:'общий чат'}? Убедитесь, что это согласованный тестовый чат.`))act(()=>api.testTelegram(saved.chat_id!,testThread?Number(testThread):null),'Тест поставлен в очередь. Результат появится в истории ниже.')
      }}>Отправить тестовое сообщение</button>
      {dirty&&<p className="muted">Сохраните изменения перед тестом.</p>}
      <p className="muted">Username не подтверждает членство в чате или получение сообщения человеком.</p>
      {saved.missing_usernames.length>0&&<p className="muted">Без корректного Telegram username: {saved.missing_usernames.map(u=>u.name).join(', ')}. Администратор может заполнить их в аккаунтах.</p>}
      <h4>Последние отправки и ошибки</h4>
      {!deliveries.length&&<p className="muted">Отправок ещё нет.</p>}
      {deliveries.map(row=><article className="telegram-delivery" key={row.id}>
        <div className="row"><strong>#{row.id} · {saved.events[row.event_type]||'Тестовое сообщение'}</strong><Badge kind={row.state==='sent'?'green':['error','uncertain'].includes(row.state)?'red':'gray'}>{STATES[row.state]||row.state}</Badge></div>
        <p className="muted">Чат {row.chat_id} · {row.thread_id?`тема ${row.thread_id}`:'общий чат'} · попыток: {row.attempts} · частей отправлено: {row.parts_sent}</p>
        <p className="muted">Создано: {fmtDate(row.created_at)} · попытка: {fmtDate(row.attempted_at)}{row.sent_at?` · отправлено: ${fmtDate(row.sent_at)}`:''}</p>
        {row.error&&<p className="error">{row.error}</p>}
        {['error','uncertain'].includes(row.state)&&<button className="small" disabled={busy} onClick={()=>{
          if(confirm(`Повторить в исходный чат ${row.chat_id}, ${row.thread_id?`тема ${row.thread_id}`:'общий чат'}? ${row.state==='uncertain'?'Возможен дубль уже отправленной части.':'Подтверждённые части повторно не отправляются.'}`))act(()=>api.retryTelegram(row.id,row.state==='uncertain'),'Повтор поставлен в очередь')
        }}>Повторить в исходное направление</button>}
      </article>)}
    </>}
  </section>
}

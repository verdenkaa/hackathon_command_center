import {IncidentSummary, Task} from './api'
import {parseUTC} from './ui'

export const TONE_LABELS:Record<string,string>={waiting:'В ожидании',active:'В работе',done:'Выполнена',soft:'Ожидает предшественника',hard:'Заблокирована',late:'Просрочена',ready:'Готова к работе'}

export function taskTone(task:Task,tasks:Task[],now=Date.now()):string {
  if(task.column_semantic==='done')return 'done'
  if(task.column_semantic==='trash')return 'waiting'
  if(task.deadline&&parseUTC(task.deadline).getTime()<now)return 'late'
  const active=(t:Task)=>t.column_semantic==='active'||t.timer?.state==='running'||!!t.actual_started_at
  if(active(task))return 'active'
  const incoming=(task.predecessors??[]).filter(p=>p.link_type!=='before').map(p=>({id:p.task_id,hard:p.link_type==='blocked_by'}))
  for(const other of tasks)if(other.predecessors?.some(p=>p.task_id===task.id&&p.link_type==='before'))incoming.push({id:other.id,hard:false})
  const pending=incoming.filter(p=>tasks.find(t=>t.id===p.id)?.column_semantic!=='done')
  if(!pending.length)return 'ready'
  if(pending.some(p=>p.hard&&tasks.some(t=>t.id===p.id&&active(t))))return 'hard'
  if(pending.some(p=>!p.hard&&tasks.some(t=>t.id===p.id&&active(t))))return 'soft'
  return 'waiting'
}

export function IncidentMark({incidents}:{incidents:IncidentSummary[]}) {
  const open=incidents.filter(i=>i.status!=='resolved')
  if(!open.length)return null
  const red=open.some(i=>i.level==='red')
  return <span className={`incident-mark ${red?'red':'yellow'}`} role="img" aria-label={red?'Красный инцидент':'Жёлтый инцидент'} title={open.map(i=>`#${i.number} ${i.title}${i.level==='red'&&i.status==='open'?' · ожидает подтверждения':''}`).join('\n')}>⚠</span>
}

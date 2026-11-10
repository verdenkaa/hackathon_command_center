import {useState} from 'react'
import {api,Project} from './api'
import {useLoad} from './ui'
import {useProjectUpdates} from './realtime'
import {Tab} from './navigation'

export function QuickStart({project,onNavigate,onCreate}:{project:Project|undefined;onNavigate:(tab:Tab)=>void;onCreate:()=>void}) {
  const key=`aion-setup-${project?.id}`
  const [hidden,setHidden]=useState(()=>localStorage.getItem(key)==='hidden')
  const [data,error,reload]=useLoad(()=>Promise.all([api.participants(),api.modules(),api.dashboard()]),[project?.id])
  useProjectUpdates(reload)
  if(hidden||!project)return null
  if(error)return <div className="card" role="alert">Не удалось загрузить подсказки: {error} <button onClick={reload}>Повторить</button></div>
  if(!data)return null
  const [participants,tracks,dashboard]=data
  const steps=[{title:'Команда',done:participants.length>1,action:()=>onNavigate('admin')},{title:'Сроки',done:!!project.start_msk&&!!project.deadline_msk,action:()=>onNavigate('settings')},{title:'Треки',done:tracks.length>0,action:()=>onNavigate('planning')},{title:'Первая задача',done:dashboard.total_tasks>0,action:onCreate}]
  if(steps.every(s=>s.done))return null
  return <section className="card quick-start" aria-label="Первый запуск"><div className="row"><h3>Подготовьте проект к работе</h3><button className="small" onClick={()=>{localStorage.setItem(key,'hidden');setHidden(true)}}>Скрыть подсказки</button></div><div className="setup-steps">{steps.map((step,index)=><button key={step.title} onClick={step.action}>{step.done?'✓':index+1} · {step.title}</button>)}</div></section>
}

import {useEffect,useState} from 'react'
import {fmtDate,Modal} from './ui'

export interface Preview {
  token:string
  changes:{task_id:number;title:string;old_start:string|null;start:string;old_end:string|null;end:string;delta_seconds:number|null}[]
  conflicts:string[]
}
export function delta(seconds:number|null):string {
  if(seconds==null)return '—'
  const minutes=Math.round(Math.abs(seconds)/60)
  return `${seconds<0?'−':seconds>0?'+':''}${Math.floor(minutes/60)}:${String(minutes%60).padStart(2,'0')} ч`
}
export async function approvePlan(preview:Preview):Promise<boolean> {
  return new Promise(resolve=>{
    const event=new CustomEvent('planning-preview',{cancelable:true,detail:{preview,resolve}})
    window.dispatchEvent(event)
    if(!event.defaultPrevented)resolve(false)
  })
}
export function PlanPreview({preview,onResolve}:{preview:Preview;onResolve:(accepted:boolean)=>void}) {
  return <Modal title="Последствия изменения плана" onClose={()=>onResolve(false)}>
    <p>Изменения ещё не сохранены. Проверьте переносы и ограничения.</p>
    <ul>{preview.conflicts.map((text,i)=><li key={i}>{text}</li>)}</ul>
    {preview.changes.length>0 && <div style={{maxHeight:'45vh',overflow:'auto'}}><table>
      <thead><tr><th>Задача</th><th>Начало: было → станет</th><th>Окончание: было → станет</th><th>Сдвиг</th></tr></thead>
      <tbody>{preview.changes.map(c=><tr key={c.task_id}><td>{c.title}</td><td>{fmtDate(c.old_start)} → {fmtDate(c.start)}</td><td>{fmtDate(c.old_end)} → {fmtDate(c.end)}</td><td>{delta(c.delta_seconds)}</td></tr>)}</tbody>
    </table></div>}
    <div className="row" style={{justifyContent:'flex-end',marginTop:16}}><button onClick={()=>onResolve(false)}>Отмена</button><button className="primary" onClick={()=>onResolve(true)}>Подтвердить</button></div>
  </Modal>
}
export function PlanningPreviewHost() {
  const [pending,setPending]=useState<{preview:Preview;resolve:(accepted:boolean)=>void}|null>(null)
  useEffect(()=>{
    let active:((value:boolean)=>void)|null=null
    const listener=(e:Event)=>{
      e.preventDefault()
      active?.(false)
      const detail=(e as CustomEvent).detail
      active=detail.resolve
      setPending(detail)
    }
    window.addEventListener('planning-preview',listener)
    return ()=>{window.removeEventListener('planning-preview',listener);active?.(false)}
  },[])
  return pending?<PlanPreview preview={pending.preview} onResolve={accepted=>{pending.resolve(accepted);setPending(null)}}/>:null
}

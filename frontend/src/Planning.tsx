import {useCallback,useEffect,useMemo,useRef,useState,PointerEvent as ReactPointerEvent} from 'react'
import {api,ApiError,Column,Me,Module,Participant,PlanningData,Task} from './api'
import {TaskForm,TaskPanel} from './Board'
import {fmtDate,parseUTC,Modal} from './ui'
import {delta} from './PlanningPreview'
import {useProjectUpdates} from './realtime'
import {taskTone,TONE_LABELS,IncidentMark} from './taskVisuals'
export {PlanPreview} from './PlanningPreview'

const HOUR=3600000, STEP=15*60000, LABEL=170, TRACK=62
const ms=(value:string)=>parseUTC(value).getTime()
export const snapTime=(time:number)=>Math.round(time/STEP)*STEP
export const zoomScroll=(scroll:number,anchor:number,oldScale:number,newScale:number)=>(scroll+anchor)*newScale/oldScale-anchor
export function linkIssue(plan:Pick<PlanningData,'tasks'|'edges'>,source:number,target:number):string {
  if(source===target)return 'Нельзя соединить задачу с собой'
  if(!plan.tasks.some(t=>t.id===source)||!plan.tasks.some(t=>t.id===target))return 'Выберите задачи этого проекта вне корзины'
  if(plan.edges.some(e=>e.source===source&&e.target===target))return 'Такая зависимость уже существует'
  const pending=[target],seen=new Set<number>()
  while(pending.length){const id=pending.pop()!;if(id===source)return 'Связь создаёт цикл зависимостей';if(!seen.has(id)){seen.add(id);pending.push(...plan.edges.filter(e=>e.source===id).map(e=>e.target))}}
  return ''
}
export function packLane<T extends {start:string;planned_end:string}>(items:T[]):(T&{track:number})[] {
  const ends:number[]=[]
  return [...items].sort((a,b)=>ms(a.start)-ms(b.start)).map(item=>{
    let track=ends.findIndex(end=>end<=ms(item.start))
    if(track<0)track=ends.length
    ends[track]=ms(item.planned_end)
    return {...item,track}
  })
}
type Drag={kind:'move'|'resize'|'link'|'pan'|'unplaced';id:number;x:number;y:number;dx:number;dy:number;scrollLeft:number;scrollTop:number}

export default function Planning({me}:{me:Me}) {
  const [data,setData]=useState<PlanningData|null>(null)
  const [columns,setColumns]=useState<Column[]>([])
  const [participants,setParticipants]=useState<Participant[]>([])
  const [modules,setModules]=useState<Module[]>([])
  const [error,setError]=useState(''),[notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false),[query,setQuery]=useState('')
  const [selected,setSelected]=useState<number|null>(null),[panel,setPanel]=useState(false)
  const [newTask,setNewTask]=useState(false)
  const [removeEdge,setRemoveEdge]=useState<{source:number;target:number}|null>(null)
  const [scale,setScale]=useState(80),[origin,setOrigin]=useState(()=>Math.floor(Date.now()/HOUR)*HOUR-2*HOUR)
  const [drag,setDrag]=useState<Drag|null>(null),dragRef=useRef<Drag|null>(null)
  const [tick,setTick]=useState(Date.now()),[edgeIndex,setEdgeIndex]=useState<{source:number;target:number}|null>(null)
  const [review,setReview]=useState('all')
  const workspace=useRef<HTMLDivElement>(null),refreshPending=useRef(false)
  const viewport=useRef<HTMLDivElement>(null),ignoreClick=useRef(false),initialized=useRef(false)
  const alive=useRef(true),inFlight=useRef(false),busyRef=useRef(false)
  const load=useCallback(async():Promise<void>=>{
    if(inFlight.current||busyRef.current||dragRef.current){refreshPending.current=true;return}
    refreshPending.current=false
    inFlight.current=true
    try {
      const next=await api.planning()
      if(alive.current&&!busyRef.current&&!dragRef.current){setData(previous=>previous&&previous.revision>next.revision?previous:next);if(!initialized.current){
        const times=next.placements.map(p=>ms(p.start))
        setOrigin(Math.floor(Math.min(Date.now(),...(next.project.start?[ms(next.project.start)]:[]),...times)/HOUR)*HOUR-2*HOUR)
        initialized.current=true
      }} else refreshPending.current=true
    } catch(e){if(alive.current)setError((e as Error).message)}
    finally{inFlight.current=false;if(refreshPending.current&&!busyRef.current&&!dragRef.current&&alive.current)window.setTimeout(()=>void load(),0)}
  },[])
  useProjectUpdates(()=>void load())
  useEffect(()=>{
    alive.current=true
    load()
    Promise.all([api.columns(),api.participants(),api.modules()]).then(([c,p,m])=>{if(alive.current){setColumns(c);setParticipants(p);setModules(m)}}).catch(e=>setError(e.message))
    const clock=setInterval(()=>setTick(Date.now()),30000)
    return ()=>{alive.current=false;clearInterval(clock)}
  },[load])
  const editable=!!data && data.project.state!=='completed' && me.roles.some(r=>r.role==='admin'||r.role==='captain'&&r.project_id===data.project.id)
  const taskMap=useMemo(()=>new Map(data?.tasks.map(t=>[t.id,t])??[]),[data])
  const layout=useMemo(()=>{
    let top=48
    return (data?.lanes??[]).map(l=>{
      const items=packLane(data!.placements.filter(p=>p.lane_id===l.id))
      const height=Math.max(90,(Math.max(0,...items.map(p=>p.track))+1)*TRACK+24)
      const result={...l,top,height,items};top+=height;return result
    })
  },[data])
  const geometry=new Map<number,{x:number;y:number;width:number}>()
  layout.forEach(l=>l.items.forEach(p=>geometry.set(p.task_id,{x:LABEL+(ms(p.start)-origin)/HOUR*scale,y:l.top+12+p.track*TRACK,width:Math.max(8,(ms(p.planned_end)-ms(p.start))/HOUR*scale)})))
  const extent=Math.max(tick+12*HOUR,data?.project.deadline?ms(data.project.deadline):0,...(data?.placements.map(p=>ms(p.planned_end)+HOUR)??[]))
  const width=Math.max(900,LABEL+(extent-origin)/HOUR*scale),height=Math.max(300,...layout.map(l=>l.top+l.height))
  const interval=scale>=120?0.5:scale>=45?1:scale>=18?3:scale>=8?6:scale>=3?24:72
  const ticks=Array.from({length:Math.min(600,Math.ceil((width-LABEL)/(scale*interval)))},(_,i)=>origin+i*interval*HOUR)
  const chosen=selected?taskMap.get(selected):null
  const placement=data?.placements.find(p=>p.task_id===selected)
  const selectedEdge=edgeIndex==null?null:data?.edges.find(e=>e.source===edgeIndex.source&&e.target===edgeIndex.target)
  const matching=(t:Task)=>!query||`${t.id} ${t.title} ${t.assignees.map(a=>a.display_name).join(' ')}`.toLowerCase().includes(query.toLowerCase())
  const overlapIds=new Set(data?.overlaps.flatMap(o=>o.task_ids))
  const reviewMatch=(id:number)=>review==='all'||review==='unconnected'&&data?.unconnected_ids.includes(id)||review==='overlaps'&&overlapIds.has(id)||review==='critical'&&data?.forecast.critical_chain.includes(id)||review==='risk'&&data?.placements.some(p=>p.task_id===id&&(p.blocked||p.overdue||p.beyond_deadline||p.before_start))

  async function command(op:string,values:Record<string,unknown>={}) {
    if(!data||busyRef.current||!editable)return
    busyRef.current=true;setBusy(true);setError('');setNotice('')
    try {const next=await api.planCommand(data.revision,op,values);if(alive.current){setData(next);setNotice('Сохранено');return true}}
    catch(e){if(!(e instanceof ApiError&&e.code==='CANCELLED'))setError((e as Error).message);if(e instanceof ApiError&&e.code==='VERSION_CONFLICT'){busyRef.current=false;await load()}}
    finally{busyRef.current=false;setBusy(false);if(refreshPending.current)void load()}
  }
  function focusTask(id:number,open=true) {
    setSelected(id);setPanel(open);setEdgeIndex(null)
    const p=data?.placements.find(p=>p.task_id===id),v=viewport.current
    if(p&&v){const point=geometry.get(id)!;v.scrollTo({left:Math.max(0,point.x-LABEL-100),top:Math.max(0,point.y-v.clientHeight/2),behavior:'smooth'})}
  }
  function zoom(next:number,anchor?:number) {
    const v=viewport.current
    const target=Math.max(0.5,Math.min(640,next)),center=anchor??Math.max(0,(v?.clientWidth??900)-LABEL)/2
    const left=zoomScroll(v?.scrollLeft??0,center,scale,target)
    setScale(target);requestAnimationFrame(()=>{if(v)v.scrollLeft=left})
  }
  function fit() {
    const starts=data?.placements.map(p=>ms(p.start))??[],ends=data?.placements.map(p=>ms(p.planned_end))??[]
    const start=Math.min(tick,...(data?.project.start?[ms(data.project.start)]:[]),...starts)-HOUR,end=Math.max(tick+HOUR,data?.project.deadline?ms(data.project.deadline):0,...ends)+HOUR
    setOrigin(Math.floor(start/HOUR)*HOUR);setScale(Math.max(0.5,Math.min(320,((viewport.current?.clientWidth??1000)-LABEL-30)/((end-start)/HOUR))))
    if(viewport.current)viewport.current.scrollLeft=0
  }
  function startDrag(e:ReactPointerEvent,kind:Drag['kind'],id=0) {
    if(e.button!==0||busy||kind!=='pan'&&!editable)return
    e.preventDefault();e.stopPropagation()
    if(kind==='pan'&&(e.target as HTMLElement).closest('button,input,.gantt-task,.gantt-edge'))return
    const v=viewport.current!
    const d={kind,id,x:e.clientX,y:e.clientY,dx:0,dy:0,scrollLeft:v.scrollLeft,scrollTop:v.scrollTop}
    dragRef.current=d;setDrag(d);workspace.current!.setPointerCapture(e.pointerId)
    if(id){setSelected(id);setEdgeIndex(null)}
  }
  function moveDrag(e:ReactPointerEvent) {
    const d=dragRef.current,v=viewport.current
    if(!d||!v)return
    if(['resize','move'].includes(d.kind)&&e.clientX>v.getBoundingClientRect().right-30)v.scrollLeft+=24
    const next={...d,dx:e.clientX-d.x+(d.kind==='pan'?0:v.scrollLeft-d.scrollLeft),dy:e.clientY-d.y}
    dragRef.current=next;setDrag(next)
    if(d.kind==='pan'){v.scrollLeft=d.scrollLeft-next.dx;v.scrollTop=d.scrollTop-next.dy}
  }
  function stopDrag(e:ReactPointerEvent) {
    const d=dragRef.current,v=viewport.current
    if(!d||!v)return
    const moved=Math.abs(d.dx)+Math.abs(d.dy)>4
    dragRef.current=null;setDrag(null);ignoreClick.current=moved||d.kind==='link'
    if(workspace.current?.hasPointerCapture(e.pointerId))workspace.current.releasePointerCapture(e.pointerId)
    if(refreshPending.current)window.setTimeout(()=>void load(),0)
    if(d.kind==='pan'){if(!moved){setPanel(false);setSelected(null);setEdgeIndex(null)}return}
    const p=data?.placements.find(p=>p.task_id===d.id)
    if(d.kind==='link') {
      const hit=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-link-target]')
      const target=Number(hit?.getAttribute('data-link-target'))
      if(target&&target!==d.id){const issue=linkIssue(data!,d.id,target);if(issue)setError(issue);else command('link',{source_id:d.id,target_id:target})}
      else setError(target===d.id?'Нельзя соединить задачу с собой':'Перетащите стрелку на левую точку следующей задачи')
    } else if(d.kind==='unplaced'&&moved) {
      const rect=v.getBoundingClientRect()
      const localY=e.clientY-rect.top+v.scrollTop,localX=e.clientX-rect.left+v.scrollLeft
      const l=layout.find(l=>localY>=l.top&&localY<l.top+l.height)
      const task=taskMap.get(d.id)
      if(l&&task&&e.clientX>=rect.left&&e.clientX<=rect.right&&e.clientY>=rect.top&&e.clientY<=rect.bottom&&localX>=LABEL){
        const start=new Date(snapTime(origin+(localX-LABEL)/scale*HOUR)).toISOString()
        void command('place',{task_id:task.id,lane_id:l.id,start,estimate_seconds:task.estimate_seconds||3600})
      }
    } else if(moved) {
      if(!p)return
      const difference=Math.round(d.dx/scale*HOUR/STEP)*STEP
      if(d.kind==='resize')command('place',{task_id:d.id,lane_id:p.lane_id,start:parseUTC(p.start).toISOString(),estimate_seconds:Math.max(900,Math.round((ms(p.planned_end)-ms(p.start)+difference)/1000))})
      else {
        const localY=e.clientY-v.getBoundingClientRect().top+v.scrollTop
        const l=layout.find(l=>localY>=l.top&&localY<l.top+l.height)
        if(l)command('place',{task_id:d.id,lane_id:l.id,start:new Date(ms(p.start)+difference).toISOString()})
      }
    }
  }
  if(!data)return <div className="card">{error||'Загрузка планирования…'}</div>
  return <div className="planning">
      <div className="plan-heading"><div><h2>Планирование</h2><span className="muted">{data.tasks.length} задач · {data.lanes.length} треков · {editable?'редактирование':'только просмотр'}</span></div>
      <div className="row"><span className="muted" role="status">{busy?'Сохранение…':'Автосохранение'}</span>{editable&&<><button className="primary" disabled={busy} onClick={()=>setNewTask(true)}>+ Задача</button></>}</div>
    </div>
    {error&&<div className="error" role="alert">{error}</div>}{notice&&<span role="status" className="muted">{notice}</span>}
    {!!data.warnings?.length&&<details className="plan-limitations"><summary>Сохранено с замечаниями ({data.warnings.length})</summary><ul>{data.warnings.map((s,i)=><li key={i}>{s}</li>)}</ul></details>}
    <div className="plan-boundary-legend">МСК (UTC+3) · Начало проекта: {fmtDate(data.project.start)} · Дедлайн: {fmtDate(data.project.deadline)}</div>
    <div className="plan-toolbar">
      <input aria-label="Поиск задач плана" placeholder="Найти задачу или исполнителя…" value={query} onChange={e=>setQuery(e.target.value)}/>
      <select aria-label="Проверка плана" value={review} onChange={e=>setReview(e.target.value)}><option value="all">Все задачи</option><option value="unconnected">Без связей — проверить</option><option value="risk">Блокировки и сроки</option><option value="overlaps">Пересечения исполнителей</option><option value="critical">Критическая цепочка</option></select>
      <button aria-label="Уменьшить масштаб" onClick={()=>zoom(scale/1.5)}>−</button><span className="muted">{Math.round(scale)} px/ч</span><button aria-label="Увеличить масштаб" onClick={()=>zoom(scale*1.5)}>+</button>
      <button onClick={fit}>Весь проект</button><button onClick={()=>{const v=viewport.current;if(v)v.scrollLeft=Math.max(0,(tick-origin)/HOUR*scale-(v.clientWidth-LABEL)/2)}}>Сейчас</button>
      <button disabled={!placement} onClick={()=>{if(placement){const v=viewport.current!;setOrigin(ms(placement.start)-HOUR);setScale(Math.min(320,Math.max(50,(v.clientWidth-LABEL-120)/Math.max(1,(ms(placement.planned_end)-ms(placement.start))/HOUR))));v.scrollLeft=0;focusTask(placement.task_id,false)}}}>К выбранной</button>
    </div>
    <div ref={workspace} className={`plan-workspace ${panel&&chosen?'with-panel':''}`} onPointerMove={moveDrag} onPointerUp={stopDrag} onPointerCancel={()=>{dragRef.current=null;setDrag(null);if(refreshPending.current)void load()}}>
      <aside className="plan-backlog">
        <h3>Неразмещённые <span className="badge yellow">{data.unplaced_ids.length}</span></h3>
        {data.unplaced_ids.length===0&&<p className="muted">Все задачи размещены</p>}
        {data.tasks.filter(t=>data.unplaced_ids.includes(t.id)&&matching(t)).map(t=><div key={t.id} role="button" tabIndex={0} aria-label={`Неразмещённая задача ${t.title}`} className={`plan-list-task plan-unplaced ${selected===t.id?'selected':''}`} onPointerDown={e=>startDrag(e,'unplaced',t.id)} onClick={()=>{if(ignoreClick.current){ignoreClick.current=false;return}focusTask(t.id)}} onKeyDown={e=>{if(e.key==='Enter')focusTask(t.id)}}>
          {editable&&<button className="gantt-connector target" data-link-target={t.id} aria-label={`Начало ${t.title}`} onPointerDown={e=>{e.stopPropagation();e.preventDefault()}} onClick={e=>e.stopPropagation()}/>}
          <strong>#{t.id} {t.title}</strong><small>{t.estimate_seconds?`${t.estimate_seconds/3600} ч`:'По умолчанию 1 ч'} · {t.assignees.map(a=>a.display_name).join(', ')||'Без исполнителей'}</small>
          {data.edges.some(e=>e.source===t.id||e.target===t.id)&&<small>{data.edges.filter(e=>e.source===t.id||e.target===t.id).map(e=>`${e.source===t.id?'до':'после'} #${e.source===t.id?e.target:e.source}`).join(' · ')}</small>}
          {editable&&<button className="gantt-connector source" aria-label={`Связь из ${t.title}`} onPointerDown={e=>startDrag(e,'link',t.id)} onClick={e=>e.stopPropagation()}/>}</div>)}
        <h4 style={{marginTop:20}}>Найти и перейти</h4>
        {data.tasks.filter(t=>matching(t)&&reviewMatch(t.id)&&!data.unplaced_ids.includes(t.id)).map(t=><button key={t.id} className={`plan-list-task ${selected===t.id?'selected':''}`} onClick={()=>focusTask(t.id)}><span>#{t.id} {t.title}</span></button>)}
      </aside>
      <div ref={viewport} className={`gantt-viewport ${drag?.kind==='pan'?'panning':''}`} aria-label="Диаграмма Ганта" onPointerDown={e=>startDrag(e,'pan')}>
        <div className="gantt-field" style={{width,height}}>
          <div className="gantt-ruler" style={{width}}><span className="gantt-corner">Треки</span>{ticks.map(time=><span key={time} className="gantt-tick" style={{left:LABEL+(time-origin)/HOUR*scale,width:scale*interval}}>{new Date(time).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',...(interval<24?{hour:'2-digit',minute:'2-digit'}:{})})}</span>)}</div>
          {ticks.map(time=><div key={time} className="gantt-gridline" style={{left:LABEL+(time-origin)/HOUR*scale,height}}/>)}
          {layout.map(l=><div key={l.id} data-lane={l.id} className="gantt-lane" style={{top:l.top,height:l.height,width}}>
            <div className="gantt-lane-label"><strong>{l.name}</strong><IncidentMark incidents={[...(l.incidents??[]),...data.tasks.filter(t=>t.module_id===l.id).flatMap(t=>t.blocking_incidents)]}/></div>
          </div>)}
          {layout.length===0&&<p className="gantt-empty">{editable?'Создайте треки в настройках проекта.':'Пока нет треков.'}</p>}
          <svg className="gantt-connections" width={width} height={height}>
            <defs><marker id="plan-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>
            {data.edges.map((edge,i)=>{
              const a=geometry.get(edge.source),b=geometry.get(edge.target)
              if(!a||!b)return null
              const x1=a.x+a.width,y1=a.y+23,x2=b.x,y2=b.y+23,detour=22+(i%5)*9
              const path=x2>x1+40?`M${x1},${y1} C${x1+detour},${y1} ${x2-detour},${y2} ${x2},${y2}`:`M${x1},${y1} H${x1+detour} V${y1+34} H${x2-detour} V${y2} H${x2}`
              const active=edgeIndex?.source===edge.source&&edgeIndex?.target===edge.target||selected===edge.source||selected===edge.target
              return <g key={`${edge.task_id}-${edge.predecessor_id}`} role="button" tabIndex={0} aria-label={`Связь ${taskMap.get(edge.source)?.title} → ${taskMap.get(edge.target)?.title}`} className={`gantt-edge ${active?'active':''} ${edge.type==='blocked_by'?'blocking':''}`} onPointerDown={e=>e.stopPropagation()} onClick={()=>{setEdgeIndex({source:edge.source,target:edge.target});setSelected(edge.target);setPanel(false)}} onKeyDown={e=>{if(e.key==='Enter'){setEdgeIndex({source:edge.source,target:edge.target});setPanel(false)}}}><title>{taskMap.get(edge.source)?.title} → {taskMap.get(edge.target)?.title}</title><path className="edge-hit" d={path}/><path className="edge-line" d={path} markerEnd="url(#plan-arrow)"/></g>
            })}
            {drag?.kind==='link'&&(()=>{const p=geometry.get(drag.id);return p?<path className="edge-draft" d={`M${p.x+p.width},${p.y+23} l${drag.dx},${drag.dy}`}/>:null})()}
          </svg>
          {data.placements.map(p=>{
            const t=taskMap.get(p.task_id)!,point=geometry.get(p.task_id)!
            const activeDrag=drag?.id===t.id?drag:null
            const offset=activeDrag?.kind==='move'?Math.round(activeDrag.dx/scale*HOUR/STEP)*STEP/HOUR*scale:0
            const barWidth=activeDrag?.kind==='resize'?Math.max(STEP/HOUR*scale,point.width+Math.round(activeDrag.dx/scale*HOUR/STEP)*STEP/HOUR*scale):point.width
            const color=taskTone(t,data.tasks,tick)
            return <div key={t.id}>

              <div className={`gantt-task tone-${color} ${selected===t.id?'selected':''} ${!matching(t)||!reviewMatch(t.id)?'dimmed':''} ${data.forecast.critical_chain.includes(t.id)?'critical':''}`} style={{left:point.x+offset,top:point.y+(activeDrag?.kind==='move'?activeDrag.dy:0),width:barWidth}}
                role="button" tabIndex={0} aria-label={`Задача ${t.title}`} title={`${t.title}\n${t.assignees.map(a=>a.display_name).join(', ')||'Без исполнителей'}\n${t.column_title} · ${t.estimate_seconds!/3600} ч\n${fmtDate(p.start)} — ${fmtDate(p.planned_end)}${p.pinned?'\nНачало закреплено':''}`}
                onPointerDown={e=>startDrag(e,'move',t.id)} onClick={()=>{if(ignoreClick.current){ignoreClick.current=false;return}focusTask(t.id)}} onKeyDown={e=>{if(e.key==='Enter')focusTask(t.id)}}>
                {editable&&<button className="gantt-connector target" data-link-target={t.id} aria-label={`Начало ${t.title}`} onPointerDown={e=>{e.stopPropagation();e.preventDefault()}} onClick={e=>e.stopPropagation()}/>}
                <div className="gantt-task-text"><strong>{p.pinned?'⌖ ':''}{t.title}</strong><small>{TONE_LABELS[color]} · {t.assignees.map(a=>a.display_name).join(', ')||'Без исполнителей'}</small></div><IncidentMark incidents={t.blocking_incidents}/>
                {editable&&<><button className="gantt-resize" aria-label={`Изменить длительность ${t.title}`} onPointerDown={e=>startDrag(e,'resize',t.id)} onClick={e=>e.stopPropagation()}/><button className="gantt-connector source" aria-label={`Связь из ${t.title}`} onPointerDown={e=>startDrag(e,'link',t.id)} onClick={e=>e.stopPropagation()}/></>}
              </div>
            </div>
          })}
          {[{time:tick,label:'Сейчас',kind:'now'},...(data.project.start?[{time:ms(data.project.start),label:'Начало проекта',kind:'start'}]:[]),...(data.project.deadline?[{time:ms(data.project.deadline),label:'Дедлайн',kind:'deadline'}]:[])].map(m=><div key={m.kind} className={`gantt-time-marker ${m.kind}`} style={{left:LABEL+(m.time-origin)/HOUR*scale,height}}><span>{m.label}</span></div>)}
        </div>
      </div>
      {panel&&chosen&&<aside className="plan-task-panel"><h3>Задача</h3>
        <TaskPanel key={`${chosen.id}-${chosen.version}`} task={chosen} tasks={data.tasks} participants={participants} modules={modules} columns={columns} isCaptain={editable} readOnly={!editable} onChange={load} onClose={()=>setPanel(false)}/>
      </aside>}
    </div>
    {drag&&['unplaced','link'].includes(drag.kind)&&<div className="plan-drag-preview" style={{left:drag.x+drag.dx+14,top:drag.y+drag.dy+14}}>{drag.kind==='link'?'Связать → ':''}{taskMap.get(drag.id)?.title}</div>}
    {selectedEdge&&<div className="plan-edge-selection"><strong>{taskMap.get(selectedEdge.source)?.title} → {taskMap.get(selectedEdge.target)?.title}</strong><span> {selectedEdge.type==='blocked_by'?'заблокирована (blocked by)':'до / после'}</span><button onClick={()=>{focusTask(selectedEdge.source,false);setEdgeIndex(null)}}>К началу</button>{editable&&<><button disabled={busy} onClick={()=>command('set_blocker',{source_id:selectedEdge.source,target_id:selectedEdge.target,blocking:selectedEdge.type!=='blocked_by'})}>{selectedEdge.type==='blocked_by'?'Снять блокер':'Сделать блокером'}</button><button disabled={busy} onClick={()=>setRemoveEdge({source:selectedEdge.source,target:selectedEdge.target})}>Удалить связь</button></>}</div>}
    {removeEdge&&<Modal title="Удалить связь?" onClose={()=>setRemoveEdge(null)}><p>{taskMap.get(removeEdge.source)?.title} → {taskMap.get(removeEdge.target)?.title}</p><div className="row"><button onClick={()=>setRemoveEdge(null)}>Отмена</button><button className="primary" disabled={busy} onClick={async()=>{if(await command('unlink',{source_id:removeEdge.source,target_id:removeEdge.target})){setEdgeIndex(null);setRemoveEdge(null)}}}>ОК</button></div></Modal>}
    <div className="plan-legend">{Object.entries(TONE_LABELS).map(([tone,label])=><span key={tone} className={`tone-key tone-${tone}`}>■ {label}</span>)}<span>⌖ Закреплено</span></div>
    <PlanReview data={data} participants={participants} onTask={focusTask}/>
    {newTask&&<TaskForm columns={columns} onClose={()=>setNewTask(false)} onCreated={async id=>{setNewTask(false);await load();setSelected(id);setPanel(true)}}/>}
  </div>
}

function PlanReview({data,participants,onTask}:{data:PlanningData;participants:Participant[];onTask:(id:number)=>void}) {
  const tasks=new Map(data.tasks.map(t=>[t.id,t])),placements=new Map(data.placements.map(p=>[p.task_id,p]))
  const link=(id:number)=><button className="small ghost" onClick={()=>onTask(id)}>#{id} {tasks.get(id)?.title}</button>
  return <div className="plan-summary plan-review">
    <section><h3>{data.forecast.limitations.length?'Частичный прогноз':'Прогноз завершения'}</h3><strong>{fmtDate(data.forecast.finish)}</strong><p>К дедлайну: {delta(data.forecast.deadline_delta_seconds)}</p>
      <ul>{data.forecast.limitations.map((s,i)=><li key={i}>{s}</li>)}</ul>
      {data.placements.filter(p=>p.overdue||p.beyond_deadline||p.before_start).map(p=><p key={p.task_id}>{link(p.task_id)} — {[p.overdue?'срок задачи истёк':'',p.before_start?'раньше начала проекта':'',p.beyond_deadline?'выходит за дедлайн проекта':''].filter(Boolean).join(' · ')}: {fmtDate(p.planned_end)}</p>)}
    </section>
    <section><h3>Проверка капитаном</h3><p>{data.unplaced_ids.length} не размещено · {data.unconnected_ids.length} без связей · {data.overlaps.length} пересечений</p>
      {data.overlaps.map((o,i)=>{const a=placements.get(o.task_ids[0])!,b=placements.get(o.task_ids[1])!;return <p key={i}>{link(o.task_ids[0])} пересекается с {link(o.task_ids[1])}<br/>{o.user_ids.map(id=>participants.find(p=>p.id===id)?.display_name??`#${id}`).join(', ')} · {fmtDate(ms(a.start)>ms(b.start)?a.start:b.start)} — {fmtDate(ms(a.planned_end)<ms(b.planned_end)?a.planned_end:b.planned_end)}</p>})}
      {data.edges.map(e=>{const a=placements.get(e.source),b=placements.get(e.target);return a&&b&&ms(a.planned_end)>ms(b.start)?<p key={`${e.source}-${e.target}`}>{link(e.target)} начинается {fmtDate(b.start)}, раньше завершения {link(e.source)} ({fmtDate(a.planned_end)}) — {e.type==='blocked_by'?'нарушение блокировки':'допустимое перекрытие мягкой связи'}</p>:null})}
      {data.unplaced_ids.length>0&&<p>Не размещены: {data.unplaced_ids.map(id=><span key={id}>{link(id)} </span>)}</p>}
      {data.unconnected_ids.length>0&&<details><summary>Без связей (могут быть самостоятельными задачами)</summary>{data.unconnected_ids.map(id=><span key={id}>{link(id)} </span>)}</details>}
      {!data.overlaps.length&&!data.unplaced_ids.length&&<p className="muted">Пересечений исполнителей и неразмещённых задач нет.</p>}
    </section>
  </div>
}


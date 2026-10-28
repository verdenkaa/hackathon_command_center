import {useEffect,useRef} from 'react'
import {currentProject} from './api'

type Environment={events:EventTarget;Source:typeof EventSource;setInterval:typeof window.setInterval;clearInterval:typeof window.clearInterval}

export function watchProject(project:number,refresh:()=>void,env:Environment={events:window,Source:EventSource,setInterval:window.setInterval.bind(window),clearInterval:window.clearInterval.bind(window)}):()=>void {
  const source=new env.Source(`/api/v1/projects/${project}/events`,{withCredentials:true})
  let degraded=false
  const changed=()=>{degraded=false;refresh()}
  const failed=()=>{degraded=true}
  const denied=()=>{source.close();refresh()}
  source.addEventListener('change',changed)
  source.addEventListener('error',failed)
  source.addEventListener('access-lost',denied)
  env.events.addEventListener('project-updated',refresh)
  env.events.addEventListener('focus',refresh)
  env.events.addEventListener('online',refresh)
  const fallback=env.setInterval(()=>{if(degraded)refresh()},15000)
  return ()=>{
    source.removeEventListener('change',changed)
    source.removeEventListener('error',failed)
    source.removeEventListener('access-lost',denied)
    source.close();env.clearInterval(fallback)
    env.events.removeEventListener('project-updated',refresh)
    env.events.removeEventListener('focus',refresh)
    env.events.removeEventListener('online',refresh)
  }
}

export function useProjectUpdates(refresh:()=>void) {
  const latest=useRef(refresh)
  latest.current=refresh
  const project=currentProject()
  useEffect(()=>watchProject(project,()=>latest.current()),[project])
}

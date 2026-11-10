import {useEffect,useRef,useState} from 'react'

type Draft={value:string;base:string;version:number}
export function reconcileDraft(draft:Draft,value:string,version:number):Draft {
  return draft.value===draft.base || draft.value===value ? {value,base:value,version} : draft
}
export function useDraftField(value:string,version:number,key:string) {
  const [draft,setDraft]=useState<Draft>(()=>{
    try {const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved&&typeof saved.value==='string'&&typeof saved.base==='string'&&Number.isInteger(saved.version))return reconcileDraft(saved,value,version)}catch{}
    return {value,base:value,version}
  })
  useEffect(()=>setDraft(previous=>reconcileDraft(previous,value,version)),[value,version])
  const dirty=draft.value!==draft.base
  useEffect(()=>{try{if(dirty)sessionStorage.setItem(key,JSON.stringify(draft));else sessionStorage.removeItem(key)}catch{}},[key,draft,dirty])
  return [draft.value,(next:string)=>setDraft(previous=>({...previous,value:next})),draft.version,dirty,()=>setDraft({value,base:value,version})] as const
}
export function useStoredState<T>(key:string,initial:T) {
  const [value,setValue]=useState<T>(()=>{try{const saved=sessionStorage.getItem(key);return saved?JSON.parse(saved):initial}catch{return initial}})
  useEffect(()=>{try{sessionStorage.setItem(key,JSON.stringify(value))}catch{}},[key,value])
  return [value,setValue] as const
}
export function clearDraft(key:string) {try{for(const name of Object.keys(sessionStorage))if(name.startsWith(key))sessionStorage.removeItem(name)}catch{}}
export function timerSeconds(timer:{state:string;total_seconds:number}|null|undefined,received:number,now:number):number {
  return (timer?.total_seconds??0)+(timer?.state==='running'?Math.max(0,Math.floor((now-received)/1000)):0)
}
export function useTimerSeconds(timer:{state:string;total_seconds:number}|null|undefined):number {
  const snapshot=useRef({timer,received:Date.now()})
  if(snapshot.current.timer!==timer)snapshot.current={timer,received:Date.now()}
  const [now,setNow]=useState(Date.now())
  useEffect(()=>{setNow(Date.now());if(timer?.state!=='running')return;const tick=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(tick)},[timer])
  return timerSeconds(timer,snapshot.current.received,Math.max(now,snapshot.current.received))
}

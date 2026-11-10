import {useEffect,useState} from 'react'
export type Tab='board'|'planning'|'incidents'|'analytics'|'admin'|'settings'
const tabs:Tab[]=['board','planning','incidents','analytics','admin','settings']
export function parseRoute(search:string) {
  const p=new URLSearchParams(search)
  const id=(key:string)=>{const n=Number(p.get(key));return Number.isSafeInteger(n)&&n>0?n:null}
  return {tab:tabs.includes(p.get('tab') as Tab)?p.get('tab') as Tab:'board',project:id('project'),task:id('task'),incident:id('incident')}
}
export function writeRoute(values:Record<string,string|number|null>,replace=false) {
  const url=new URL(window.location.href)
  for(const [key,value] of Object.entries(values)){if(value===null||value==='')url.searchParams.delete(key);else url.searchParams.set(key,String(value))}
  if(url.href===window.location.href)return
  window.history[replace?'replaceState':'pushState']({},'',url)
  window.dispatchEvent(new Event('aion-navigation'))
}
export function useUrlFilter(key:string,initial='') {
  const [value,setValue]=useState(()=>new URLSearchParams(typeof window==='undefined'?'':window.location.search).get(key)??initial)
  useEffect(()=>{const restore=()=>setValue(new URLSearchParams(window.location.search).get(key)??initial);window.addEventListener('popstate',restore);return()=>window.removeEventListener('popstate',restore)},[key,initial])
  return [value,(next:string)=>{setValue(next);writeRoute({[key]:next},true)}] as const
}

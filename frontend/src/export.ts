import type {Analytics,Incident,Task} from './api'
export function tasksCsv(tasks:Task[]):string {
  const cell=(value:unknown)=>{let s=String(value??'');if(/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'}
  return '\ufeff'+[['ID','Задача','Статус','Исполнители','Срок UTC','Оценка, секунд'],...tasks.map(t=>[t.id,t.title,t.column_title,t.assignees.map(a=>a.display_name).join(', '),t.deadline,t.estimate_seconds])].map(row=>row.map(cell).join(',')).join('\r\n')
}
export function summaryMarkdown(data:Analytics,incidents:Incident[]):string {
  const line=(text:string)=>text.replace(/[\r\n]+/g,' ').replace(/([\\`*_[\]<>#])/g,'\\$1')
  return [`# ${line(data.kpi.name)}`,`Снимок: ${data.summary.generated_at}`,`Завершено: ${data.kpi.completed_tasks} из ${data.kpi.total_tasks}`,'','## Завершённые задачи',...data.summary.tasks.filter(t=>t.availability==='done').map(t=>`- #${t.id} ${line(t.title)}`),'','## Открытые риски',...data.summary.situations.map(s=>`- ${line(s.title)}`),'','## Инциденты',...incidents.map(i=>`- #${i.number} ${line(i.title)} — ${i.status==='resolved'?'решён':'открыт'}${i.resolution?': '+line(i.resolution):''}`)].join('\n')
}
export function download(name:string,content:string,type:string) {
  const url=URL.createObjectURL(new Blob([content],{type})),link=document.createElement('a')
  link.href=url;link.download=name;link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000)
}

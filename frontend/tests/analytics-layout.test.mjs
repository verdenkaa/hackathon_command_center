import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const result=await build({entryPoints:['src/Analytics.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
const m={exports:{}}
new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)

const task=(id,title,availability='ready')=>({id,title,availability,deadline:'2030-01-01T12:00:00',column_title:'To Do',assignees:[],waiting_reasons:[],missing:[],blocking_incidents:[]})
const fixture=()=>({plan:{incomplete:false},tasks:[task(1,'First'),task(2,'Second'),task(3,'Finished','done')],attention:[],incidents:[],tracks:[{id:1,name:'Backend',done:1,total:3,percent:33,active:0,waiting:0,overdue:0,blocked:0,incident_ids:[],task_ids:[1,2,3]}],participants:[{id:1,display_name:'Alex',traffic_status:'green',task_ids:[1,2,3],active_ids:[],ready_ids:[],waiting_ids:[],incident_ids:[],overlaps:[[1,2],[1,3]],downstream:{levels:[],limitations:[]}}],unassigned_ids:[1,2,3]})
const renderSummary=summary=>renderToStaticMarkup(createElement(m.exports.OperationalSections,{summary,onOpenTask(){},onOpenIncident(){}}))

test('compact sections put workload first, collapse attention and track tasks, and name unfinished overlap pairs',()=>{
  const html=renderSummary(fixture())
  assert.ok(html.indexOf('Участники и нагрузка')<html.indexOf('Что требует внимания'))
  assert.match(html,/<details class="card attention-section"><summary/)
  assert.match(html,/<details class="track-tasks"><summary/)
  assert.doesNotMatch(html,/Задачи и их доступность|задачи и влияние|Назначенные задачи/)
  assert.match(html,/Прогресс трека Backend/)
  assert.match(html,/Не назначен исполнитель/)
  assert.match(html,/class="nearest-tasks"/)
  const overlap=html.match(/<div class="overlap-pairs">(.*?)<\/div>/)?.[1]
  assert.ok(overlap?.includes('#1 First')&&overlap.includes('#2 Second'))
  assert.ok(!overlap.includes('Finished'))
  assert.match(html,/aria-label="Пересечения: 1,/)
})

test('workload colors follow exact count boundaries',()=>{
  for(const [field,label,cases] of [
    ['active_ids','В работе',[[0,'bad'],[1,'good'],[2,'warn'],[3,'bad']]],
    ['ready_ids','Доступны',[[0,'bad'],[1,'good']]],
    ['waiting_ids','Ожидают',[[0,'good'],[3,'good'],[4,'bad']]],
    ['incident_ids','Инциденты',[[0,'good'],[1,'bad']]],
  ])for(const [count,tone] of cases){
    const summary=fixture();summary.participants[0][field]=Array(count).fill(1)
    assert.ok(renderSummary(summary).includes(`class="workload-value tone-${tone}" title=`)&&new RegExp(`class="workload-value tone-${tone}"[^>]*aria-label="${label}: ${count},`).test(renderSummary(summary)),`${label} ${count}`)
  }
  const s=fixture();s.participants[0].overlaps=[[1,3]]
  assert.match(renderSummary(s),/class="workload-value tone-good"[^>]*aria-label="Пересечения: 0,/)
})

test('progress separates completed duration and calendar time from timer spending',()=>{
  const data={summary:{period:{phase:'running',percent:50,elapsed_seconds:3600,duration_seconds:7200,remaining_seconds:3600,start:'2030-01-01T00:00:00',deadline:'2030-01-01T02:00:00'},progress:{tasks:{numerator:1,denominator:2,percent:50},duration:{numerator:3600,denominator:14400,percent:25,missing_count:1,incomplete:true}},plan:{status:'incomplete',finish:null,covered_tasks:1,total_tasks:2,limitations:['Missing data']}}}
  const html=renderToStaticMarkup(createElement(m.exports.AnalyticsMetrics,{data}))
  for(const title of ['По количеству задач','По длительности задач','По календарному времени проекта','Нет длительности: 1','План неполный'])assert.ok(html.includes(title),title)
  assert.doesNotMatch(html,/п.п.|Израсходовано оценки|Расход времени опережает/)
})
test('notification has a native open button separate from read and delete actions',async()=>{
  const out=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const app={exports:{}}
  new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),app,app.exports)
  const html=renderToStaticMarkup(createElement(app.exports.NotificationItem,{notification:{id:1,type:'incident_yellow_created',payload:{title:'Block'},created_at:'2026-10-28T00:00:00'},onOpen(){},onRead(){},onDelete(){}}))
  assert.match(html,/aria-label="Открыть блокер: Block"/)
  assert.doesNotMatch(html,/role="button"/)
})

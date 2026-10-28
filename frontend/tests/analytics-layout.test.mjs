import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const result=await build({entryPoints:['src/Analytics.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
const m={exports:{}}
new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
test('budget comparison uses existing task and timer totals',()=>{
  assert.deepEqual(m.exports.spendingSummary({total_tasks:12,progress_percent:58.3,estimate_seconds:86400,actual_seconds:30600}),{timePercent:35.4,gap:22.9})
  assert.deepEqual(m.exports.spendingSummary({total_tasks:2,progress_percent:50,estimate_seconds:100,actual_seconds:150}),{timePercent:150,gap:-100})
  assert.deepEqual(m.exports.spendingSummary({total_tasks:0,progress_percent:0,estimate_seconds:0,actual_seconds:10}),{timePercent:null,gap:null})
})
test('analytics groups tasks, timers and comparison without explanatory essays',()=>{
  const data={kpi:{total_tasks:12,completed_tasks:7,progress_percent:58.3,in_progress_tasks:3,overdue_tasks:1,active_timers:3,estimate_seconds:86400,actual_seconds:30600,calendar_seconds:21600,deadline_seconds_left:43200},forecast:{remaining_seconds:32400,status:'on_track',margin_seconds:36000}}
  const html=renderToStaticMarkup(createElement(m.exports.AnalyticsMetrics,{data}))
  for(const title of ['Задачи','Таймеры','Сведения','Прогресс задач','Израсходовано оценки','22.9'])assert.ok(html.includes(title),title)
  assert.doesNotMatch(html,/не личные|человекочасы|допущения|объединение интервалов/)
})
test('notification has a native open button separate from read and delete actions',async()=>{
  const out=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const app={exports:{}}
  new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),app,app.exports)
  const html=renderToStaticMarkup(createElement(app.exports.NotificationItem,{notification:{id:1,type:'incident_yellow_created',payload:{title:'Block'},created_at:'2026-10-28T00:00:00'},onOpen(){},onRead(){},onDelete(){}}))
  assert.match(html,/aria-label="Открыть блокер: Block"/)
  assert.doesNotMatch(html,/role="button"/)
})

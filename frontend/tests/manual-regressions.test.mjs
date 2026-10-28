import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

async function load(path) {
  const result = await build({entryPoints:[path],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const m={exports:{}}
  new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
  return m.exports
}
test('pending red incidents have purple color and explicit status', async () => {
  const ui=await load('src/ui.tsx')
  assert.equal(ui.incidentKind({level:'red',status:'open'}),'purple')
  assert.equal(ui.incidentLabel({level:'red',status:'open'}),'Ожидает подтверждения')
  assert.equal(ui.incidentKind({level:'red',status:'confirmed'}),'red')
  assert.equal(ui.incidentKind({level:'yellow',status:'open'}),'yellow')
})
test('burndown handles single observation and scales all lines', async () => {
  const ui=await load('src/ui.tsx')
  const html=renderToStaticMarkup(createElement(ui.LineChart,{points:[{date:'2026-10-28T01:00:00',remaining:1,completed:50}]}))
  assert.match(html,/Задачи/)
  assert.match(html,/Время/)
  assert.doesNotMatch(html,/NaN/)
  const step=renderToStaticMarkup(createElement(ui.LineChart,{points:[{date:'2026-10-28T01:00:00',remaining:12,completed:0},{date:'2026-10-28T02:00:00',remaining:5,completed:7}]}))
  assert.match(step,/H [\d.]+ V [\d.]+/)
})
test('incident form defaults owner and explains automatic reselection', async () => {
  const mod=await load('src/Incidents.tsx')
  const html=renderToStaticMarkup(createElement(mod.IncidentForm,{me:{id:7},participants:[{id:7,display_name:'Tester'}],tasks:[],modules:[]}))
  assert.match(html,/value="7" selected/)
  assert.match(html,/Глубина/)
  assert.match(html,/заново/)
})
test('task properties include editable estimate, deadline, tags and primary owner', async () => {
  const mod=await load('src/Board.tsx')
  const task={id:1,project_id:1,title:'A',description:'',priority:'medium',column_key:'a',column_semantic:'normal',assignees:[],predecessors:[],checklist:[],tags:[],blocking_incidents:[]}
  const html=renderToStaticMarkup(createElement(mod.TaskPanel,{task,tasks:[task],participants:[],modules:[],columns:[]}))
  assert.match(html,/Плановая оценка/)
  assert.match(html,/datetime-local/)
  assert.match(html,/Основной исполнитель/)
})
test('task board uses purple for a pending red blocker',async()=>{
  const mod=await load('src/Board.tsx')
  const task={id:1,title:'A',column_key:'backlog',priority:'medium',assignees:[],tags:[],blocking_incidents:[{id:8,number:1,title:'Block',level:'red',status:'open'}]}
  const html=renderToStaticMarkup(createElement(mod.TaskCard,{task,columns:[],blocked:true}))
  assert.match(html,/badge purple/)
  assert.match(html,/Ожидает подтверждения/)
})

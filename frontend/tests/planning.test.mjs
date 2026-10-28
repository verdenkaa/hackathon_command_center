import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import test from 'node:test'
import {build} from 'esbuild'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

const result = await build({entryPoints:['src/Planning.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
const m = {exports:{}}
new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)

test('zoom keeps the time under the anchor and snapping uses fifteen minutes',()=>{
  assert.equal(m.exports.zoomScroll(200,400,50,100),800)
  assert.equal(m.exports.snapTime(16*60000),15*60000)
  assert.equal(m.exports.snapTime(29*60000),30*60000)
})
test('client explains a duplicate or cyclic link before saving',()=>{
  const plan={tasks:[{id:1},{id:2},{id:3}],edges:[{source:1,target:2},{source:2,target:3}]}
  assert.match(m.exports.linkIssue(plan,3,1),/цикл/)
  assert.match(m.exports.linkIssue(plan,1,2),/существует/)
  assert.match(m.exports.linkIssue(plan,1,1),/собой/)
  assert.equal(m.exports.linkIssue(plan,1,3),'')
})
test('overlapping bars in one free lane remain separately accessible',()=>{
  const result=m.exports.packLane([{task_id:1,start:'2026-10-28T08:00:00',planned_end:'2026-10-28T10:00:00'},
    {task_id:2,start:'2026-10-28T09:00:00',planned_end:'2026-10-28T11:00:00'},
    {task_id:3,start:'2026-10-28T10:00:00',planned_end:'2026-10-28T12:00:00'}])
  assert.equal(result[0].track,0)
  assert.equal(result[1].track,1)
  assert.equal(result[2].track,0)
})
test('preview explicitly shows proposed dates, delta and conflicts',()=>{
  const html=renderToStaticMarkup(createElement(m.exports.PlanPreview,{preview:{changes:[{task_id:1,title:'API',old_start:'2026-10-28T08:00:00',start:'2026-10-28T09:00:00',old_end:'2026-10-28T09:00:00',end:'2026-10-28T10:00:00',delta_seconds:3600}],conflicts:['Закреплённое начало']},onResolve(){}}))
  for(const value of ['API','Закреплённое начало','Подтвердить','Отмена','+1']) assert.ok(html.includes(value),value)
})
test('read only shared task panel disables edits',async()=>{
  const out=await build({entryPoints:['src/Board.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const b={exports:{}}
  new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),b,b.exports)
  const task={id:1,project_id:1,title:'A',description:'',priority:'medium',column_key:'a',assignees:[],predecessors:[],checklist:[],tags:[],blocking_incidents:[]}
  const html=renderToStaticMarkup(createElement(b.exports.TaskPanel,{task,tasks:[task],participants:[],modules:[],columns:[],readOnly:true}))
  assert.match(html,/<fieldset disabled/)
})

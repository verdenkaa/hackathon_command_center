import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import test from 'node:test'
import {build} from 'esbuild'
const out=await build({entryPoints:['src/taskVisuals.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
const m={exports:{}}
new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
const task=(id,status='normal',predecessors=[])=>({id,column_semantic:status,predecessors,blocking_incidents:[]})
test('root tasks are ready and only immediate neighbours react to active work',()=>{
  const a=task(1),b=task(2,'normal',[{task_id:1,link_type:'after'}]),c=task(3,'normal',[{task_id:2,link_type:'blocked_by'}])
  assert.equal(m.exports.taskTone(a,[a,b,c]),'ready')
  assert.equal(m.exports.taskTone(b,[a,b,c]),'waiting')
  a.column_semantic='active'
  assert.equal(m.exports.taskTone(a,[a,b,c]),'active')
  assert.equal(m.exports.taskTone(b,[a,b,c]),'soft')
  assert.equal(m.exports.taskTone(c,[a,b,c]),'waiting')
  a.column_semantic='normal'
  a.actual_started_at='2026-10-28T08:00:00'
  assert.equal(m.exports.taskTone(b,[a,b,c]),'soft')
  a.column_semantic='done'
  assert.equal(m.exports.taskTone(b,[a,b,c]),'ready')
  b.column_semantic='active'
  assert.equal(m.exports.taskTone(c,[a,b,c]),'hard')
})
test('reverse before is an incoming dependency; overdue wins except completed',()=>{
  const a=task(1,'normal',[{task_id:2,link_type:'before'}]),b=task(2)
  assert.equal(m.exports.taskTone(b,[a,b]),'waiting')
  b.deadline='2000-01-01T00:00:00'
  assert.equal(m.exports.taskTone(b,[a,b]),'late')
  b.column_semantic='done'
  assert.equal(m.exports.taskTone(b,[a,b]),'done')
})

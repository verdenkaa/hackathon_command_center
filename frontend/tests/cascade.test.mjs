import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import test from 'node:test'
import {build} from 'esbuild'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const out=await build({entryPoints:['src/Incidents.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
const m={exports:{}}
new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
test('source filters combine assignee, track and tag',()=>{
  const t={module_id:3,tags:['api'],assignees:[{user_id:7}]}
  assert.equal(m.exports.matchesSource(t,'mine','api','3',7),true)
  assert.equal(m.exports.matchesSource(t,'8','api','3',7),false)
  assert.equal(m.exports.matchesSource(t,'mine','web','3',7),false)
  assert.equal(m.exports.matchesSource(t,'mine','api','none',7),false)
})
test('cascade displays separate hard reach, potential risks and non-mutating scenarios',()=>{
  const cascade={source_ids:[1],levels:[{depth:1,hard_task_ids:[2],potential_task_ids:[3],new_hard_count:1,new_potential_count:1,user_ids:[7],track_ids:[8],start:null,end:null}],scenarios:[{delay_seconds:900,task_ids:[2],finish_shift_seconds:0}],limitations:['Прогноз частичный']}
  const html=renderToStaticMarkup(createElement(m.exports.CascadeView,{cascade,depth:1,tasks:[]}))
  for(const label of ['Жёсткий каскад','Потенциальный риск','15 мин','Прогноз частичный'])assert.ok(html.includes(label),label)
})

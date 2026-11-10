import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
const out=await build({entryPoints:['src/export.ts'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external'})
const m={exports:{}}
new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
test('export quotes CSV fields and neutralizes spreadsheet formulas',()=>{
  const tasks=[{id:1,title:'=HYPERLINK("unsafe")',column_title:'Ready',assignees:[],deadline:null,estimate_seconds:0}]
  const csv=m.exports.tasksCsv(tasks)
  assert.ok(csv.includes("\"'=HYPERLINK("))
  assert.ok(csv.includes('""unsafe""'))
})
test('summary includes completed work and incident outcomes',()=>{
  const text=m.exports.summaryMarkdown({kpi:{name:'Demo',completed_tasks:1,total_tasks:1},summary:{generated_at:'2026-11-02',tasks:[{id:1,title:'API ready',availability:'done'}],situations:[]}},[{number:2,title:'Service unavailable',status:'resolved',resolution:'Switched locally'}])
  assert.match(text,/API ready/);assert.match(text,/Switched locally/)
})

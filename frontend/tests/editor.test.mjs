import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
const out=await build({entryPoints:['src/editor.ts'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external'})
const m={exports:{}}
new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
test('remote refresh updates untouched fields and preserves the version of an edited draft',()=>{
  assert.deepEqual(m.exports.reconcileDraft({value:'A',base:'A',version:1},'B',2),{value:'B',base:'B',version:2})
  assert.deepEqual(m.exports.reconcileDraft({value:'My draft',base:'A',version:1},'B',2),{value:'My draft',base:'A',version:1})
  assert.deepEqual(m.exports.reconcileDraft({value:'Saved',base:'A',version:1},'Saved',2),{value:'Saved',base:'Saved',version:2})
})
test('live timer adds local elapsed time only while running',()=>{
  assert.equal(m.exports.timerSeconds({state:'running',total_seconds:10},1000,4000),13)
  assert.equal(m.exports.timerSeconds({state:'paused',total_seconds:10},1000,4000),10)
  assert.equal(m.exports.timerSeconds(null,1000,4000),0)
})

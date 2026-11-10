import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
const out=await build({entryPoints:['src/navigation.ts'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external'})
const m={exports:{}}
new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
test('route rejects unknown tabs and restores object identity',()=>{
  assert.deepEqual(m.exports.parseRoute('?tab=planning&project=2&task=8'),{tab:'planning',project:2,task:8,incident:null})
  assert.equal(m.exports.parseRoute('?tab=unknown&project=-1&task=NaN').tab,'board')
  assert.equal(m.exports.parseRoute('?project=-1').project,null)
})

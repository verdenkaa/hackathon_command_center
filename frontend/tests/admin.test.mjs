import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
const out=await build({entryPoints:['src/Admin.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
const m={exports:{}}
new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
test('new user hides password and marks name as required',()=>{
  const html=renderToStaticMarkup(createElement(m.exports.CreateUser,{onClose(){},onCreated(){}}))
  assert.match(html,/type="password"/)
  assert.match(html,/autoComplete="new-password"/)
  assert.match(html,/Имя \*/)
})

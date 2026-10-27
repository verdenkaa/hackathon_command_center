import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import test from 'node:test'
import { build } from 'esbuild'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

test('sandbox cleanup requires explicit confirmation and shows its scope', async () => {
  const result = await build({entryPoints:['src/Sandbox.tsx'],bundle:true,write:false,
    platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const module = {exports:{}}
  new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),module,module.exports)
  const html = renderToStaticMarkup(createElement(module.exports.ResetSandbox, {
    workspace:{project_id:2,project_name:'Sandbox',counts:{tasks:10},team:[]},busy:false,onReset:async()=>true,
  }))
  assert.match(html, /ОЧИСТИТЬ/)
  assert.match(html, /disabled=""[^>]*>Очистить песочницу/)
  assert.match(html, /Общие аккаунты/)
  assert.match(html, /Sandbox/)
})

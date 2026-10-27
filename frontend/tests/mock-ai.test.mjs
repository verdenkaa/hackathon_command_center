import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import test from 'node:test'
import { build } from 'esbuild'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

test('AI preview displays the actual mock request and editable input controls', async () => {
  const result = await build({entryPoints:['src/MockAi.tsx'],bundle:true,write:false,
    platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const module = {exports:{}}
  new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),module,module.exports)
  const html = renderToStaticMarkup(createElement(module.exports.AiRequestView, {
    context:{mode:'mock',provider:'gemini',prompt:'Проверь риски',question:'Что мешает?',trigger:'manual',snapshot:{tasks:[{title:'API'}]}},
  }))
  assert.match(html, /Проверь риски/)
  assert.match(html, /Что мешает/)
  assert.match(html, /API/)
  assert.match(html, /mock/)
})

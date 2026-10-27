import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import test from 'node:test'
import { build } from 'esbuild'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const result = await build({entryPoints:['src/Board.tsx'], bundle:true, write:false,
  platform:'node', format:'cjs', packages:'external', jsx:'automatic'})
const module = {exports:{}}
new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),module,module.exports)
const columns = [{id:1,key:'backlog',title:'Очередь'}, {id:2,key:'custom',title:'Моя колонка'}]

test('task card uses real project columns including custom titles', () => {
  const html = renderToStaticMarkup(createElement(module.exports.TaskCard, {
    task:{title:'Task',column_key:'custom',assignees:[],tags:[],priority:'medium'}, columns,
  }))
  assert.match(html, /value="custom" selected="">Моя колонка/)
  assert.doesNotMatch(html, /value="testing"/)
})

test('new task form offers custom project columns', () => {
  const html = renderToStaticMarkup(createElement(module.exports.TaskForm, {columns}))
  assert.match(html, /value="custom">Моя колонка/)
})

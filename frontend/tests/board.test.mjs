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
    task:{id:42,title:'Task',column_key:'custom',assignees:[],tags:[],priority:'medium'}, columns,
  }))
  assert.match(html, /value="custom" selected="">Моя колонка/)
  assert.doesNotMatch(html, /value="testing"/)
  assert.match(html, /#42 /)
})

test('new task form offers custom project columns', () => {
  const html = renderToStaticMarkup(createElement(module.exports.TaskForm, {columns}))
  assert.match(html, /value="custom">Моя колонка/)
})

test('task dialog has a named modal and protects keyboard focus', () => {
  const html=renderToStaticMarkup(createElement(module.exports.TaskForm,{columns}))
  assert.match(html,/role="dialog"/)
  assert.match(html,/aria-modal="true"/)
  assert.match(html,/aria-label="Закрыть окно"/)
})

test('shared task details show the soft planning dependency beside the description', () => {
  const source = {id:1,project_id:1,title:'Подготовить API',description:'Описание A',priority:'medium',column_key:'backlog',column_semantic:'normal',assignees:[],predecessors:[],checklist:[],tags:[],blocking_incidents:[]}
  const target = {...source,id:2,title:'Собрать интерфейс',description:'Описание B',predecessors:[{task_id:1,link_type:'after'}]}
  const render = task => renderToStaticMarkup(createElement(module.exports.TaskPanel,{task,tasks:[source,target],participants:[],modules:[],columns}))
  const dependent = render(target)
  assert.match(dependent, /aria-label="Зависимости задачи"/)
  assert.match(dependent, /Выполняется после.*#1.*Подготовить API/)
  assert.ok(dependent.indexOf('aria-label="Зависимости задачи"') < dependent.indexOf('>Описание<'))
  assert.match(render(source), /Выполняется до.*#2.*Собрать интерфейс/)
})

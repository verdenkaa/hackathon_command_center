import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('advice separates evidence, proposal, unknowns and team decision', async()=>{
  const result=await build({entryPoints:['src/Advisor.tsx'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const m={exports:{}}
  new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
  const html=renderToStaticMarkup(createElement(m.exports.AdviceCard,{rec:{id:1,summary:'Проверьте помощь',content:'Старый текст',status:'accepted',comment:'Обсудим',excluded:false,created_at:'2026-10-28T10:00:00',snapshot_at:'2026-10-28T10:00:00',structured:{situation:'Есть пересечение',grounds:['План задач'],consequence:'Риск задержки',action:'Спросите участника',limitations:['Навыки неизвестны'],related:{task_ids:[67],incident_ids:[],user_ids:[],track_ids:[]},significance:'warning',freshness:'uncertain'}},canManage:false,onChange(){},onOpenTask(){},onOpenIncident(){},onPlanning(){}}))
  for(const text of ['Ситуация','Основания','Действие','Ограничения','Навыки неизвестны','Принята','Задача #67','Снимок']) assert.ok(html.includes(text),text)
  assert.ok(!html.includes('Изменить решение'))
  assert.ok(!html.includes('Старый текст'))
})

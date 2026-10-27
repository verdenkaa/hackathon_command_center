import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import test from 'node:test'
import { build } from 'esbuild'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

test('new incident form renders without crashing', async () => {
  const result = await build({
    entryPoints: ['src/Incidents.tsx'], bundle: true, write: false,
    platform: 'node', format: 'cjs', packages: 'external', jsx: 'automatic',
  })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', result.outputFiles[0].text)(
    createRequire(import.meta.url), module, module.exports,
  )
  const html = renderToStaticMarkup(createElement(module.exports.IncidentForm, {
    me: { id: 1 }, participants: [], tasks: [], modules: [],
    onClose() {}, onCreated() {},
  }))
  assert.match(html, /Новый инцидент/)
  assert.match(html, /Создать/)
})

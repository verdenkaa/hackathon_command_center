import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import test from 'node:test'
import {build} from 'esbuild'

const out=await build({entryPoints:['src/realtime.ts'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external'})
const m={exports:{}}
new Function('require','module','exports',out.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)

test('live subscription refreshes on change, reconnect and local mutation, cleans up on unmount',()=>{
  const events=new EventTarget(), streams=[]
  let calls=0, timer, cleared=false
  class Source extends EventTarget {
    constructor(url){super();this.url=url;streams.push(this)}
    close(){this.closed=true}
  }
  const stop=m.exports.watchProject(7,()=>calls++,{events,Source,setInterval:fn=>{timer=fn;return 1},clearInterval:()=>{cleared=true}})
  assert.equal(streams[0].url,'/api/v1/projects/7/events')
  streams[0].dispatchEvent(new Event('change'))
  events.dispatchEvent(new Event('project-updated'))
  events.dispatchEvent(new Event('focus'))
  assert.equal(calls,3)
  streams[0].dispatchEvent(new Event('error'))
  timer()
  assert.equal(calls,4)
  streams[0].dispatchEvent(new Event('change'))
  timer()
  assert.equal(calls,5)
  stop()
  events.dispatchEvent(new Event('project-updated'))
  streams[0].dispatchEvent(new Event('change'))
  assert.equal(calls,5)
  assert.ok(streams[0].closed&&cleared)
})

test('access revocation stops reconnecting the event stream',()=>{
  const events=new EventTarget()
  let stream,calls=0
  class Source extends EventTarget {constructor(){super();stream=this} close(){this.closed=true}}
  const stop=m.exports.watchProject(1,()=>calls++,{events,Source,setInterval:()=>1,clearInterval(){}})
  stream.dispatchEvent(new Event('access-lost'))
  assert.ok(stream.closed)
  assert.equal(calls,1)
  stop()
})

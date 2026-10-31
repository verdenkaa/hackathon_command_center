// Offline DOM unit tests: no browser, user window, network, or real credentials.
const {JSDOM}=require('jsdom');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {test}=require('node:test');
const html=readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const script=readFileSync(path.join(__dirname,'../static/panel.js'),'utf8');
function fixture(){
  const dom=new JSDOM(html,{url:'http://127.0.0.1:8787',runScripts:'outside-only'}), w=dom.window;
  const calls=[];
  const status={config:{id:'abc123',configured:true,desired:true,login:'actual-admin',data_dir:'D:/test',subdomain:'dots-bots-hub'},
    history:{records:[]},metrics:[],events:[],services:{},tunnel:{url:'https://dots-bots-hub.fxtun.ru'},
    installations:{main:'abc123',items:[{id:'abc123',name:'QA'}]},container:{State:'running'},api:true,ui:true};
  w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.setInterval=()=>0;
  w.fetch=async(url,options)=>{calls.push({url,options});return{ok:true,json:async()=>url.endsWith('/operator')?{login:'actual-admin',key:'ARCHIVE-KEY',password:'VERIFIED-PASSWORD',password_message:'Проверен по базе',previous_keys:[],relationship:'Ключ архива'}:status};};
  w.eval(script);
  return {w,calls,status,$:id=>w.document.getElementById(id),close:()=>dom.window.close()};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('scenario buttons have visible selection and existing scenario starts selected platform',async()=>{
  const f=fixture();await settle();
  f.$('scenario-new').click();
  assert.equal(f.$('new-platform-form').hidden,false);
  assert.equal(f.$('scenario-new').getAttribute('aria-pressed'),'true');
  f.$('scenario-existing').click();await settle();
  assert.ok(f.calls.some(c=>c.url==='/api/platforms/select'&&JSON.parse(c.options.body).start===true));
  f.close();
});
test('monitor opens verified tunnel and offers separate platform stop',async()=>{
  const f=fixture();await settle();
  assert.equal(f.$('open-platform').href,'https://dots-bots-hub.fxtun.ru/');
  assert.ok(f.$('monitor-view').querySelector('[data-action="stop"]'));
  assert.ok(f.$('shutdown-hub'));
  f.close();
});
test('credentials dialog separates verified login password and archive key',async()=>{
  const f=fixture();await settle();f.$('show-key').click();await settle();
  assert.ok(f.$('operator-login').textContent.includes('actual-admin'));
  assert.equal(f.$('account-password').value,'VERIFIED-PASSWORD');
  assert.equal(f.$('operator-key').value,'ARCHIVE-KEY');
  f.$('close-key').click();assert.equal(f.$('account-password').value,'');
  f.close();
});

test('project deletion requires typed name and defaults to keeping files',async()=>{
  const f=fixture();await settle();
  f.$('delete-project').click();
  assert.equal(f.$('delete-dialog').open,true);
  assert.equal(f.$('delete-data').checked,false);
  assert.equal(f.$('confirm-delete-project').disabled,true);
  f.$('delete-confirmation').value='QA';
  f.$('delete-confirmation').dispatchEvent(new f.w.Event('input'));
  assert.equal(f.$('confirm-delete-project').disabled,false);
  f.$('confirm-delete-project').click();await settle();
  const call=f.calls.find(c=>c.url==='/api/platforms/delete');
  assert.deepEqual(JSON.parse(call.options.body),{identity:'abc123',confirmation:'QA',delete_data:false});
  f.close();
});

'use strict';
const $ = id => document.getElementById(id);
const stamp = value => value ? new Date(value * 1000).toLocaleString('ru-RU') : 'нет данных';
const size = value => value == null ? 'нет данных' : value < 1048576 ? `${(value / 1024).toFixed(1)} КиБ` : `${(value / 1048576).toFixed(1)} МиБ`;
let state, restoreTicket;
let renderedInstallation;
// Two actual views. Move existing, tested sections once, preserving form listeners.
const monitorView=document.createElement('div'), settingsView=document.createElement('div');
monitorView.id='monitor-view'; settingsView.id='settings-view'; settingsView.hidden=true;
monitorView.setAttribute('role','tabpanel'); settingsView.setAttribute('role','tabpanel');
$('notice').after(monitorView,settingsView);
const restoreSection=document.createElement('section');
restoreSection.id='restore-settings';
restoreSection.innerHTML='<div class="eyebrow">ЭТАП 7 · ВОССТАНОВЛЕНИЕ И ПЕРЕНОС</div><h2>Работа с архивом</h2>';
restoreSection.append($('backups').querySelector('.two-columns'));
for(const id of ['overview','backups','events']) monitorView.append($(id));
for(const id of ['setup','dependencies','credentials','integrations','launch','network']) settingsView.append($(id));
settingsView.append(restoreSection,$('hub-settings'));
$('overview').querySelector('.metric-grid').before($('overview').querySelector('.overview-grid'));
function setTab(name){
  monitorView.hidden=name!=='monitor'; settingsView.hidden=name!=='settings';
  for(const button of document.querySelectorAll('[data-tab]')){const selected=button.dataset.tab===name;button.classList.toggle('active',selected);button.setAttribute('aria-selected',String(selected));}
  window.scrollTo(0,0);
}
for(const button of document.querySelectorAll('[data-tab]')) button.addEventListener('click',()=>setTab(button.dataset.tab));
function scenario(isNew){
  $('new-platform-form').hidden=!isNew;$('existing-scenario').hidden=isNew;
  for(const [id,active] of [['scenario-new',isNew],['scenario-existing',!isNew]]){$(id).setAttribute('aria-pressed',String(active));$(id).classList.toggle('selected',active);}
}
$('scenario-new').addEventListener('click',()=>{
  scenario(true);$('new-platform-form').elements.name.focus();
  message('Новая платформа: укажите название, пустую папку и логин. Затем нажмите «Создать и перейти к подготовке».');
});
$('scenario-existing').addEventListener('click',()=>{
  scenario(false);
  if(!$('platform-select').value){message('Сохранённых платформ пока нет. Создайте новую или подключите существующую папку базы.',true);return;}
  selectPlatform(true);
});
function message(text, error = false) { $('notice').textContent = text; $('notice').className = error ? 'error' : ''; $('notice').hidden = false; }
async function api(path, body, method = 'POST') {
  const options = {method, credentials:'same-origin'};
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) { options.body=JSON.stringify(body); options.headers={'Content-Type':'application/json'}; }
  const response = await fetch('/api/' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Операция не выполнена');
  return data;
}
function text(id, value) { $(id).textContent = value; }
function service(id, value) { text(id, value == null ? 'Не проверен' : value ? 'Готов' : 'Недоступен'); $(id).className='service-state ' + (value == null ? '' : value ? 'good' : 'bad'); }
function renderServices(s){
  const labels={ok:'Работает',error:'Сбой',loading:'Подготовка',unknown:'Не проверено',waiting:'Ожидает запуска'};
  const symbols={ok:'✓',error:'×',loading:'◌',unknown:'?',waiting:'…'};
  const names={docker:'Docker',platform:'Платформа',fxtunnel:'fxTunnel',telegram:'Telegram',gemini:'Gemini'};
  $('services-grid').replaceChildren();
  for(const [name,value] of Object.entries(s.services||{})){
    const button=document.createElement('button');button.type='button';button.className='service-tile';
    const icon=document.createElement('span');icon.className='service-logo';
    if(name==='platform'){icon.textContent='⬡';}else{const img=document.createElement('img');img.src='/static/icons/'+name+'.png';img.alt='';icon.append(img);}
    const badge=document.createElement('span');badge.className='status-badge '+value.status;badge.textContent=symbols[value.status];badge.setAttribute('aria-label',labels[value.status]);
    icon.append(badge);const title=document.createElement('b');title.textContent=names[name];const subtitle=document.createElement('small');subtitle.textContent=labels[value.status];
    button.append(icon,title,subtitle);button.title=value.detail;
    button.addEventListener('click',()=>{$('service-detail').hidden=false;$('service-detail').textContent=names[name]+': '+value.detail;});
    $('services-grid').append(button);
  }
}
function render(s) {
  state = s;
  const c = s.config, h = s.history, latest = h.records.at(-1), metric = s.metrics.at(-1);
  if(renderedInstallation!==c.id){
    renderedInstallation=c.id;
    delete $('setup-form').dataset.loaded;delete $('settings-form').dataset.loaded;delete $('tunnel-form').dataset.loaded;
    for(const form of [$('settings-form'),$('tunnel-form')])form.reset();
    $('service-detail').hidden=true;
    closeKey();
  }
  const entry=s.installations?.items.find(row=>row.id===c.id);
  text('installation', entry?.name || 'Новый проект');
  text('account-login',c.login);
  text('main-platform','Основной проект запускается автоматически при включённом автозапуске. Переключение остановит текущую.');
  const select=$('platform-select'), options=(s.installations?.items||[]);
  const signature=JSON.stringify([options,s.installations?.main,c.id]);
  if(select.dataset.signature!==signature){
    select.replaceChildren();for(const row of options){const option=document.createElement('option');option.value=row.id;option.textContent=row.name+(row.id===s.installations.main?' · основная':'');select.append(option);}select.value=c.id;select.dataset.signature=signature;
    scenario(!options.length);
  }
  $('legacy-attach').hidden=c.configured;
  $('delete-project').disabled=!!s.busy||!options.length;$('select-platform').disabled=!!s.busy||!options.length;$('start-selected').disabled=!!s.busy||!options.length;
  $('show-key').disabled=!c.configured;
  $('scenario-existing').disabled=!!s.busy;
  $('scenario-new').disabled=!!s.busy;
  renderServices(s);
  text('app-version', 'v' + s.version);
  const running = s.container?.State === 'running', ready = running && s.api === true && s.ui === true;
  text('platform-status', s.busy ? 'Выполняется: ' + s.busy : s.error || (ready ? 'Платформа работает · производственная сборка' : !c.configured ? 'Завершите первоначальную настройку' : running ? 'Контейнер работает; ожидаем готовность' : 'Платформа остановлена'));
  text('platform-badge', ready ? 'РАБОТАЕТ' : running ? 'ПРОВЕРКА' : 'ОСТАНОВЛЕНА');
  $('platform-badge').className='pill ' + (ready ? 'good' : running ? '' : 'bad');
  text('tunnel-status', (s.tunnel?.url || s.tunnel?.error || 'Не настроен') + (s.tunnel?.checked_at ? ' · проверено ' + stamp(s.tunnel.checked_at) : ''));
  $('copy-link').disabled=!s.tunnel?.url;
  const open=$('open-platform');
  if(s.tunnel?.url){open.href=s.tunnel.url;open.removeAttribute('aria-disabled');open.title='Открыть платформу по проверенной ссылке туннеля';}
  else{open.removeAttribute('href');open.setAttribute('aria-disabled','true');open.title='Ссылка появится после запуска и проверки туннеля';}
  text('host-cpu', metric?.host_cpu == null ? '—' : metric.host_cpu.toFixed(1) + '%');
  text('host-memory', metric?.host_memory == null ? '—' : metric.host_memory.toFixed(1) + '%');
  $('memory-bar').value=metric?.host_memory || 0;
  text('panel-memory', 'Память панели: ' + size(metric?.panel_memory_bytes));
  text('container-cpu', metric?.container_cpu == null ? '—' : metric.container_cpu.toFixed(1) + '% CPU');
  text('container-memory', 'Память: ' + (metric?.container_memory || 'нет данных'));
  const points=s.metrics.filter(m => m.host_cpu != null).map((m,i,all)=>`${all.length > 1 ? i/(all.length-1)*280 : 0},${62-Math.min(m.host_cpu,100)*.6}`).join(' ');
  $('cpu-chart').setAttribute('points',points);
  text('last-check', 'Проверено: ' + stamp(s.checked_at) + (s.checked_at && Date.now()/1000-s.checked_at > 90 ? ' · данные устарели' : ''));
  text('recovery-count', s.recovery_attempts);
  text('recovery-title', s.recovery_exhausted ? 'Автоматически восстановить не удалось' : 'Контролируемый перезапуск');
  text('recovery-description', s.recovery_exhausted ? 'Проверьте место на диске, состояние базы и события. После устранения причины запустите платформу вручную.' : c.desired ? 'Автоматическое восстановление включено. До трёх попыток с паузой и ожиданием готовности.' : 'Явная остановка соблюдается. Автоматический запуск отключён.');
  text('backup-age', latest ? stamp(latest.created) : 'Копий пока нет');
  text('backup-size', latest ? `${size(latest.size)} · ${latest.seconds.toFixed(1)} с` : 'Проверенная локальная копия');
  text('backup-check', h.message || 'Проверка изменений каждые 5 минут');
  text('data-folder', c.data_dir); text('disk-free', size(s.disk_free_bytes));
  text('autostart-toggle', 'Автозапуск: ' + (s.autostart ? 'включён · отключить' : 'выключен · включить'));
  if(s.dependencies) text('dependency-state', s.dependencies.phase || `WSL: ${s.dependencies.wsl === null ? 'не нужен' : s.dependencies.wsl ? 'готов' : 'нет'} · Ubuntu: ${s.dependencies.distro === null ? 'не нужна' : s.dependencies.distro ? 'готова' : 'нет'} · Docker: ${s.dependencies.docker ? 'установлен' : 'нет'} · Compose: ${s.dependencies.compose ? 'готов' : 'нет'} · шаг: ${s.dependencies.next}`);
  text('local-backup-state', h.message || 'Копий пока нет');
  text('external-backup-state', h.external_error || (c.external_folder ? 'Последняя проверка: ' + stamp(h.external_at) : 'Не настроен'));
  text('telegram-backup-state', h.telegram_error || (h.telegram_at ? `Принято: ${stamp(h.telegram_at)}; снимок: ${stamp(h.telegram_snapshot_at)}` : c.telegram_chat ? 'Первая отправка ожидается' : 'Не настроен'));
  $('unlock-form').hidden=s.host_platform !== 'posix' || s.vault_unlocked;
  $('transfer-box').hidden=!c.transfer_pending;
  const setup=$('setup-form');
  for (const element of setup.elements) element.disabled=c.configured;
  if (!setup.dataset.loaded) { setup.elements.data_dir.value=c.data_dir; setup.elements.login.value=c.login; setup.dataset.loaded='yes'; }
  const settings=$('settings-form');
  if (!settings.dataset.loaded) { for(const name of ['external_folder','telegram_chat','telegram_thread','telegram_alert_chat','telegram_alert_thread','administrator']) settings.elements[name].value=c[name] || ''; settings.dataset.loaded='yes'; }
  if(!$('tunnel-form').dataset.loaded){$('tunnel-form').elements.subdomain.value=c.subdomain||'';$('tunnel-form').dataset.loaded='yes';}
  text('delivery-feedback',h.telegram_error||h.alert_error||'Сначала сохраните настройки, затем проверьте оповещения и отправку копии.');
  text('launch-hint',s.operation_error || (s.busy ? 'Выполняется: '+s.busy : !c.configured?'Сначала выберите или создайте платформу на этапе 1.':'Платформа: '+(ready?'готова к работе':c.desired?'ожидаем готовность':'остановлена')));
  $('launch-hint').classList.toggle('warning',Boolean(s.operation_error));
  $('backup-list').replaceChildren();
  for(const record of [...h.records].reverse().slice(0,30)) {
    const row=document.createElement('tr');
    for(const value of [stamp(record.created),size(record.size),record.seconds.toFixed(1)+' с','Проверена локально']) { const cell=document.createElement('td'); cell.textContent=value; row.append(cell); }
    const cell=document.createElement('td'), link=document.createElement('a'); link.href='/api/backup/'+encodeURIComponent(record.id); link.download=''; link.textContent='Экспорт ↓'; cell.append(link); row.append(cell); $('backup-list').append(row);
  }
  if(!h.records.length) { const row=document.createElement('tr'),cell=document.createElement('td'); cell.colSpan=5; cell.textContent='Проверенных копий пока нет'; row.append(cell); $('backup-list').append(row); }
  $('event-list').replaceChildren();
  for(const event of [...s.events].reverse()) { const row=document.createElement('div'), time=document.createElement('time'),content=document.createElement('span'); row.className='event '+event.level; time.textContent=stamp(event.at);content.textContent=event.message;row.append(time,content);$('event-list').append(row); }
  if(!s.events.length) $('event-list').textContent='Событий пока нет';
  for(const button of document.querySelectorAll('[data-action]')){
    const action=button.dataset.action;
    button.disabled=Boolean(s.busy)||(!c.configured && !['check','telegram-test'].includes(action))||(action==='tunnel-start'&&!ready);
    button.title=button.disabled?(s.busy?'Дождитесь завершения текущей операции':!c.configured?'Сначала создайте или выберите платформу':'Сначала дождитесь готовности платформы'):'';
  }
}
async function refresh() { try { render(await api('status',undefined,'GET')); } catch(error) { message(error.message,true); } }
for(const button of document.querySelectorAll('[data-action]')) button.addEventListener('click', async()=>{ try { await api('action/'+button.dataset.action); message('Операция запущена. Состояние и результат появятся в панели.'); await refresh(); } catch(error) { message(error.message,true); } });
$('setup-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('setup',Object.fromEntries(new FormData(event.target)));message('Установка подготовлена. Сохраните ключ оператора, соберите образ и нажмите «Старт».');await refresh();}catch(error){message(error.message,true);}});
$('unlock-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('unlock',Object.fromEntries(new FormData(event.target)));event.target.reset();await refresh();}catch(error){message(error.message,true);}});
$('settings-form').addEventListener('submit',async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.target));for(const key of ['telegram_thread','telegram_alert_thread'])data[key]=data[key]?Number(data[key]):null;try{data.clear_keys=['telegram','gemini'].filter(name=>data['clear_'+name]==='on');delete data.clear_telegram;delete data.clear_gemini;const result=await api('settings',data);event.target.elements.telegram.value='';event.target.elements.gemini.value='';event.target.elements.clear_telegram.checked=false;event.target.elements.clear_gemini.checked=false;message(result.message);await refresh();}catch(error){message(error.message,true);}});
$('show-key').addEventListener('click',async()=>{
  try{
    const data=await api('operator');
    text('operator-login','Логин: '+data.login);
    $('account-password').value=data.password||'';
    $('account-password').placeholder='Пароль неизвестен хабу';
    text('password-message',data.password_message);
    $('copy-access').disabled=!data.password;
    text('account-login',data.login);
    let selector=$('operator-key-select');
    if(!selector){selector=document.createElement('select');selector.id='operator-key-select';selector.setAttribute('aria-label','Ключ текущего или старого архива');$('operator-key').before(selector);selector.addEventListener('change',()=>{$('operator-key').value=selector.value;});}
    selector.replaceChildren();
    for(const [index,key] of [data.key,...(data.previous_keys||[])].entries()){const option=document.createElement('option');option.value=key;option.textContent=index?'Предыдущий ключ '+index:'Текущий ключ';selector.append(option);}
    $('operator-key').value=data.key;text('key-explanation',data.relationship);$('key-dialog').showModal();
  }catch(error){message(error.message,true);}
});
$('copy-access').addEventListener('click',()=>navigator.clipboard.writeText($('operator-login').textContent+'\n'+$('account-password').value).then(()=>message('Логин и пароль скопированы')));
$('copy-key').addEventListener('click',()=>navigator.clipboard.writeText($('operator-key').value).then(()=>message('Ключ скопирован')));
$('save-key').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([$('operator-login').textContent+'\n'+$('operator-key').value+'\n'],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='hcc-operator-key.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
function closeKey(){$('operator-key').value='';$('account-password').value='';$('operator-key-select')?.replaceChildren();$('key-dialog').close();}
$('close-key').addEventListener('click',closeKey);$('key-dialog').addEventListener('cancel',closeKey);
$('restore-form').addEventListener('submit',async event=>{event.preventDefault();try{const result=await api('restore/inspect',new FormData(event.target));restoreTicket=result.ticket;text('restore-description',`${result.warning} Снимок ${result.manifest.created_at}; версия ${result.manifest.application}; схема ${result.manifest.schema}.`);event.target.elements.key.value='';$('restore-dialog').showModal();}catch(error){message(error.message,true);}});
$('cancel-restore').addEventListener('click',()=>{$('restore-dialog').close();restoreTicket=null;});
$('apply-restore').addEventListener('click',async()=>{try{$('apply-restore').disabled=true;await api('restore/apply',{ticket:restoreTicket,confirm:true});$('restore-dialog').close();message('Восстановлено. Завершите перенос, затем запустите платформу и проверьте вход оператора.');await refresh();}catch(error){message(error.message,true);}finally{$('apply-restore').disabled=false;}});
$('activate').addEventListener('click',async()=>{try{await api('transfer/activate',{previous_server_stopped:$('old-stopped').checked,accept_quota_pause:$('old-stopped').checked});await refresh();message('Перенос подтверждён. Введите интеграционные секреты и запустите платформу.');}catch(error){message(error.message,true);}});
$('check-dependencies').addEventListener('click',async()=>{try{message('Проверяем компоненты…');await api('dependencies/check');await refresh();}catch(error){message(error.message,true);}});
$('install-dependencies').addEventListener('click',async()=>{try{await api('dependencies/install');message('Шаг установки запущен. Прогресс и необходимые действия появятся в панели.');}catch(error){message(error.message,true);}});
$('autostart-toggle').addEventListener('click',async()=>{try{await api('autostart',{enabled:!state.autostart});await refresh();}catch(error){message(error.message,true);}});
$('tunnel-form').addEventListener('submit',async event=>{event.preventDefault();try{const data=Object.fromEntries(new FormData(event.target));data.clear_key=data.clear_key==='on';await api('tunnel/settings',data);event.target.elements.fxtunnel.value='';event.target.elements.clear_key.checked=false;message('Секрет и имя сохранены. Откройте туннель отдельной кнопкой.');}catch(error){message(error.message,true);}});
$('copy-link').addEventListener('click',()=>{if(state?.tunnel?.url) navigator.clipboard.writeText(state.tunnel.url).then(()=>message('Действующая ссылка скопирована'));});
$('new-platform-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.target.querySelector('button.primary');button.disabled=true;
  try{message('Подготавливаем отдельную платформу и останавливаем предыдущую…');await api('platforms/new',Object.fromEntries(new FormData(event.target)));await refresh();message('Платформа создана. Далее: этап 2 — проверка среды, этап 3 — сохранение данных входа.');scenario(false);$('dependencies').scrollIntoView({behavior:'smooth'});}catch(error){message(error.message,true);}finally{button.disabled=false;}
});
async function selectPlatform(start){
  if(!$('platform-select').value)return;
  try{message(start?'Останавливаем предыдущую платформу и запускаем выбранную…':'Выбираем платформу…');await api('platforms/select',{identity:$('platform-select').value,start});restoreTicket=null;await refresh();message(start?'Контейнер запущен. Готовность API появится в мониторинге.':'Выбрано. Настройки ниже относятся к этой платформе.');if(start)setTab('monitor');}catch(error){message(error.message,true);}
}
$('select-platform').addEventListener('click',()=>selectPlatform(false));
$('start-selected').addEventListener('click',()=>selectPlatform(true));
for(const button of document.querySelectorAll('[data-folder]'))button.addEventListener('click',async()=>{
  if(!window.pywebview?.api){message('Выбор папки доступен в приложении хаба. В режиме диагностики введите путь вручную.');return;}
  const value=await window.pywebview.api.choose_folder();if(value)button.closest('form').elements[button.dataset.folder].value=value;
});
$('shutdown-hub').addEventListener('click',async()=>{
  $('shutdown-hub').disabled=true;message('Останавливаем платформу и туннель. Дождитесь закрытия окна…');
  try{await api('shutdown');message('Хаб выключен.');}catch(error){message(error.message,true);$('shutdown-hub').disabled=false;}
});
document.addEventListener('click',event=>{
  const link=event.target.closest('a');if(!link||link.hasAttribute('download'))return;
  if(link.getAttribute('aria-disabled')==='true'){event.preventDefault();message('Дождитесь проверенной ссылки туннеля.');return;}
  if(link.getAttribute('href')?.startsWith('#')){event.preventDefault();setTab('monitor');return;}
  if(link.target==='_blank'&&window.pywebview?.api){event.preventDefault();window.pywebview.api.open_external(link.href.replace(/\/$/,''));}
});
(async()=>{const token=new URLSearchParams(location.hash.slice(1)).get('token');if(token){history.replaceState(null,'',location.pathname);try{await api('session',{token});}catch(error){message(error.message,true);return;}}await refresh();setInterval(refresh,5000);})();

$('split-projects').addEventListener('click',async()=>{if(!confirm('Остановить платформу и создать отдельные копии проектов? Исходная база сохранится.'))return;try{await api('platforms/split',{});await refresh();message('Проекты разделены. Выберите проект, задайте ключи и запустите Aion.');}catch(error){message(error.message,true);}});

let deleteTarget;
$('delete-project').addEventListener('click',()=>{
  deleteTarget=state?.installations?.items.find(row=>row.id===$('platform-select').value);
  if(!deleteTarget)return;
  text('delete-description',`Проект: ${deleteTarget.name}. Папка данных: ${deleteTarget.data_dir||'не указана'}. Работающий проект будет остановлен.`);
  text('delete-error','');$('delete-data').checked=false;$('delete-confirmation').value='';$('confirm-delete-project').disabled=true;
  $('delete-dialog').showModal();
});
$('delete-confirmation').addEventListener('input',()=>{$('confirm-delete-project').disabled=$('delete-confirmation').value!==deleteTarget?.name;});
$('cancel-delete-project').addEventListener('click',()=>{$('delete-dialog').close();deleteTarget=null;});
$('confirm-delete-project').addEventListener('click',async()=>{
  if(!deleteTarget||$('delete-confirmation').value!==deleteTarget.name)return;
  $('confirm-delete-project').disabled=true;
  try{await api('platforms/delete',{identity:deleteTarget.id,confirmation:$('delete-confirmation').value,delete_data:$('delete-data').checked});$('delete-dialog').close();deleteTarget=null;restoreTicket=null;await refresh();message('Проект удалён из списка. Другой проект не запускался.');}
  catch(error){text('delete-error',error.message);$('confirm-delete-project').disabled=false;}
});

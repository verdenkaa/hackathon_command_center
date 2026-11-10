import {test,expect,Page} from '@playwright/test'

async function setup(page:Page) {
  await page.request.post('/api/v1/auth/login',{data:{login:'admin',password:'e2e-password'}})
  const response=await page.request.post('/api/v1/projects',{data:{name:`Browser test ${Date.now()}`}})
  expect(response.ok()).toBeTruthy()
  return (await response.json()).id as number
}
async function task(page:Page,project:number,title:string) {
  const response=await page.request.post(`/api/v1/projects/${project}/tasks`,{data:{title}})
  expect(response.ok()).toBeTruthy();return response.json()
}
async function open(page:Page,project:number) {
  await page.goto(`/?project=${project}`)
  await expect(page.getByRole('button',{name:'Доска',exact:true})).toBeVisible()
}

test('remote edits update untouched fields; stale drafts cannot overwrite them',async({page})=>{
  const project=await setup(page),created=await task(page,project,'Initial title')
  await open(page,project)
  await page.locator('.task-card').filter({hasText:'Initial title'}).click()
  const title=page.locator('.side-panel input').first()
  await page.request.patch(`/api/v1/tasks/${created.id}`,{data:{title:'Remote title',version:created.version}})
  await expect(title).toHaveValue('Remote title')
  await title.focus();await page.locator('.side-panel .section-title').filter({hasText:'Описание'}).click()
  expect((await (await page.request.get(`/api/v1/tasks/${created.id}`)).json()).title).toBe('Remote title')
  await title.fill('My draft')
  const current=await (await page.request.get(`/api/v1/tasks/${created.id}`)).json()
  await page.request.patch(`/api/v1/tasks/${created.id}`,{data:{title:'Second remote edit',version:current.version}})
  await expect(page.getByText('Задача обновлена.',{exact:false})).toBeVisible()
  await title.blur()
  await expect(page.locator('.side-panel').getByRole('alert').first()).toBeVisible()
  expect((await (await page.request.get(`/api/v1/tasks/${created.id}`)).json()).title).toBe('Second remote edit')
  await expect(title).toHaveValue('My draft')
})

test('drafts survive closing; focus stays in the dialog; lost response retries do not duplicate',async({page})=>{
  const project=await setup(page);await open(page,project)
  await page.getByRole('button',{name:'+ Задача',exact:true}).click()
  await page.getByLabel('Название *',{exact:true}).fill('Retried task')
  await page.getByRole('button',{name:'Создать',exact:true}).focus();await page.keyboard.press('Tab')
  expect(await page.evaluate(()=>document.querySelector('[role=dialog]')!.contains(document.activeElement))).toBeTruthy()
  page.once('dialog',dialog=>dialog.accept());await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button',{name:'+ Задача',exact:true}).click()
  await expect(page.getByLabel('Название *',{exact:true})).toHaveValue('Retried task')
  await page.locator('.check-list input[type=checkbox]').first().check()
  let lost=false
  await page.route(`**/api/v1/projects/${project}/tasks`,async route=>{
    if(route.request().method()==='POST'&&!lost){lost=true;await route.fetch();await route.abort()}else await route.continue()
  })
  await page.getByRole('button',{name:'Создать',exact:true}).click()
  await expect(page.getByText('Связь прервана.',{exact:false})).toBeVisible()
  await page.getByRole('button',{name:'Создать',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const tasks=await (await page.request.get(`/api/v1/projects/${project}/tasks`)).json()
  expect(tasks).toHaveLength(1);expect(tasks[0].assignees).toHaveLength(1)
})

test('loading failures can be retried and failed saves show a message',async({page})=>{
  const project=await setup(page)
  await page.route('**/api/v1/projects',route=>route.fulfill({status:503,json:{error:{code:'TEST',message:'Тестовый отказ загрузки'}}}))
  await page.goto(`/?project=${project}`)
  await expect(page.getByRole('alert')).toContainText('Тестовый отказ загрузки')
  await page.unroute('**/api/v1/projects');await page.getByRole('button',{name:'Повторить загрузку',exact:true}).click()
  await page.getByRole('button',{name:'Настройки',exact:true}).click()
  await page.getByLabel('Название',{exact:true}).fill('Failed rename')
  await page.route(`**/api/v1/projects/${project}`,route=>route.request().method()==='PATCH'?route.fulfill({status:503,json:{error:{code:'TEST',message:'Не удалось сохранить название'}}}):route.continue())
  await page.getByRole('button',{name:'Сохранить',exact:true}).first().click()
  await expect(page.getByRole('alert')).toContainText('Не удалось сохранить название')
})

test('navigation, open task and filters survive reload and back',async({page})=>{
  const project=await setup(page);await task(page,project,'Searchable')
  await open(page,project);await page.getByPlaceholder('Поиск…',{exact:true}).fill('Search')
  await page.locator('.task-card').click();await expect(page).toHaveURL(/task=/)
  await page.reload();await expect(page.locator('.side-panel input').first()).toHaveValue('Searchable')
  await page.getByRole('button',{name:'Закрыть',exact:true}).click()
  await page.getByRole('button',{name:'Планирование',exact:true}).click()
  await page.reload();await expect(page.locator('nav.tabs button.active')).toHaveText('Планирование')
  await page.goBack();await expect(page.locator('nav.tabs button.active')).toHaveText('Доска')
  await expect(page.getByPlaceholder('Поиск…',{exact:true})).toHaveValue('Search')
})

test('mobile plan supports placement without dragging, and timer visibly ticks',async({page})=>{
  const project=await setup(page),created=await task(page,project,'Mobile task')
  await page.setViewportSize({width:390,height:844});await open(page,project)
  await page.getByRole('button',{name:'Планирование',exact:true}).click()
  await page.getByLabel('Название первого трека',{exact:true}).fill('Mobile lane')
  await page.getByRole('button',{name:'Создать трек',exact:true}).click()
  await page.locator('.schedule-task').click()
  await page.getByLabel('Длительность (минуты)',{exact:true}).fill('45')
  await page.getByRole('button',{name:'Сохранить размещение',exact:true}).click()
  await expect.poll(async()=>((await (await page.request.get(`/api/v1/projects/${project}/planning`)).json()).placements.length)).toBe(1)
  const current=await (await page.request.get(`/api/v1/projects/${project}/planning`)).json()
  const shifted=new Date(current.placements[0].start+'Z');shifted.setUTCHours(shifted.getUTCHours()+1)
  await page.request.post(`/api/v1/projects/${project}/planning`,{data:{revision:current.revision,op:'place',task_id:created.id,lane_id:current.placements[0].lane_id,start:shifted.toISOString()}})
  const expected=new Date(shifted.getTime()+3*3600000).toISOString().slice(0,16)
  await expect(page.getByLabel('Начало задачи (МСК)',{exact:true})).toHaveValue(expected)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
  await page.getByRole('button',{name:'▶ Старт',exact:true}).click()
  const counter=page.locator('.plan-task-panel .shared-task-panel .mono').first()
  const first=await counter.innerText();await expect(counter).not.toHaveText(first,{timeout:4000})
  expect((await (await page.request.get(`/api/v1/tasks/${created.id}`)).json()).timer.state).toBe('running')
})

test('a planning arrow appears in both task details without blocking work',async({page})=>{
  const project=await setup(page),a=await task(page,project,'Arrow source'),b=await task(page,project,'Arrow target')
  const lane=await (await page.request.post(`/api/v1/projects/${project}/modules`,{data:{name:'Arrow lane'}})).json()
  for(const item of [a,b])expect((await page.request.patch(`/api/v1/tasks/${item.id}`,{data:{version:item.version,module_id:lane.id,estimate_seconds:3600}})).ok()).toBeTruthy()
  await open(page,project);await page.locator('.task-card').filter({hasText:b.title}).click()
  const plan=await page.context().newPage();await plan.goto(`/?project=${project}&tab=planning`)
  const source=plan.getByRole('button',{name:`Связь из ${a.title}`,exact:true}),target=plan.getByRole('button',{name:`Начало ${b.title}`,exact:true})
  await expect(source).toBeVisible();const s=(await source.boundingBox())!,t=(await target.boundingBox())!
  await plan.mouse.move(s.x+s.width/2,s.y+s.height/2);await plan.mouse.down();await plan.mouse.move(t.x+t.width/2,t.y+t.height/2,{steps:15});await plan.mouse.up()
  await expect(page.getByRole('region',{name:'Зависимости задачи'})).toContainText(`Выполняется после: #${a.id} ${a.title}`)
  expect((await (await page.request.get(`/api/v1/tasks/${b.id}`)).json()).predecessors).toEqual([{task_id:a.id,link_type:'after'}])
  await page.getByRole('button',{name:'▶ Старт',exact:true}).click();await expect(page.getByRole('button',{name:'⏸ Пауза',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Закрыть',exact:true}).click();await page.locator('.task-card').filter({hasText:a.title}).click()
  await expect(page.getByRole('region',{name:'Зависимости задачи'})).toContainText(`Выполняется до: #${b.id} ${b.title}`)
})

test('user form hides the password and requires a name',async({page})=>{
  const project=await setup(page);await open(page,project)
  await page.getByRole('button',{name:'Админ',exact:true}).click();await page.getByRole('button',{name:'+ Пользователь',exact:true}).click()
  await expect(page.getByLabel('Пароль *',{exact:true})).toHaveAttribute('type','password')
  await page.getByLabel('Логин *',{exact:true}).fill('member-'+Date.now());await page.getByLabel('Пароль *',{exact:true}).fill('member-password')
  await expect(page.getByRole('button',{name:'Создать',exact:true})).toBeDisabled()
  await page.getByLabel('Имя *',{exact:true}).fill('Browser member');await page.getByRole('button',{name:'Создать',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('analytics exports tasks and a demo summary',async({page})=>{
  const project=await setup(page);await task(page,project,'Exported task');await open(page,project)
  await page.getByRole('button',{name:'Аналитика',exact:true}).click()
  for(const [button,filename] of [['Экспорт задач CSV','aion-tasks.csv'],['Итоги Markdown','aion-summary.md']]){
    const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:button,exact:true}).click()
    const download=await downloaded;expect(download.suggestedFilename()).toBe(filename);expect(await download.failure()).toBeNull()
  }
})

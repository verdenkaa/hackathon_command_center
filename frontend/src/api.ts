import {approvePlan,Preview} from './PlanningPreview'

export interface Role {
  id: number
  role: string
  project_id: number | null
}

export interface Me {
  managed?: boolean
  id: number
  login: string
  display_name: string
  telegram_username: string | null
  active: boolean
  avatar: string | null
  roles: Role[]
}

export interface Project {
  id: number
  name: string
  deadline_msk: string | null
  start_msk: string | null
  state: string
  created_at: string
}

export interface Column {
  id: number
  key: string
  title: string
  position: number
  semantic: string
  auto_start_timer: boolean
  auto_stop_timer: boolean
}

export interface Assignee {
  user_id: number
  login: string
  display_name: string
  is_primary: boolean
}

export interface Timer {
  state: string
  accumulated_seconds: number
  elapsed_seconds: number
  total_seconds: number
}

export interface Task {
  actual_started_at?:string|null
  actual_completed_at?:string|null
  id: number
  project_id: number
  column_id: number
  column_key: string
  column_title: string
  column_semantic: string
  blocking_incidents: IncidentSummary[]
  module_id: number | null
  parent_id: number | null
  title: string
  description: string | null
  priority: string
  estimate_seconds: number | null
  deadline: string | null
  tags: string[]
  version: number
  created_at: string
  updated_at: string
  assignees: Assignee[]
  predecessors: { task_id: number; link_type: string }[]
  checklist: { id: number; text: string; done: boolean; position: number }[]
  timer: Timer | null
}

export interface Placement {
  task_id:number;lane_id:number;start:string;end:string;planned_end:string;pinned:boolean
  actual_started_at:string|null;actual_completed_at:string|null
  baseline:{start:string;end:string;estimate_seconds:number;lane_id:number}|null
  deviation_seconds:number|null;blocked:boolean;overdue:boolean;beyond_deadline:boolean;before_start:boolean
}
export interface PlanEdge {source:number;target:number;task_id:number;predecessor_id:number;type:string}
export interface PlanningData {
  warnings?:string[]
  revision:number
  project:{id:number;name:string;start:string|null;deadline:string|null;state:string}
  lanes:{id:number;name:string;position:number;incidents?:IncidentSummary[]}[]
  tasks:Task[];placements:Placement[];edges:PlanEdge[]
  unplaced_ids:number[];unconnected_ids:number[]
  overlaps:{task_ids:number[];user_ids:number[]}[]
  baseline:{id:number;created_at:string}|null;baseline_count:number
  forecast:{finish:string|null;deadline_delta_seconds:number|null;critical_chain:number[];limitations:string[]}
}

export interface IncidentSummary { id:number; number:number; title:string; level:string; status:string }

export interface Incident {
  deleted_user_ids?:number[]
  source_task_id?:number|null
  cascade_depth?:number
  cascade?:Cascade|null
  id: number
  number: number
  project_id: number
  level: string
  status: string
  title: string
  description: string | null
  impact: string | null
  urgency: string | null
  author_id: number
  owner_id: number | null
  resolution: string | null
  created_at: string
  confirmed_at: string | null
  resolved_at: string | null
  age_seconds: number
  targets: { target_type: string; target_id: number }[]
  events: { id: number; actor_id: number | null; event_type: string; data: Record<string, unknown>; created_at: string }[]
}

export interface Cascade {
  source_ids:number[]
  levels:{depth:number;hard_task_ids:number[];potential_task_ids:number[];new_hard_count:number;new_potential_count:number;user_ids:number[];track_ids:number[];start:string|null;end:string|null}[]
  scenarios:{delay_seconds:number;task_ids:number[];finish_shift_seconds:number}[]
  limitations:string[]
}

export interface Notification {
  id: number
  project_id: number | null
  user_id: number | null
  type: string
  payload: Record<string, unknown>
  read_at: string | null
  created_at: string
}

export interface AiSettings {
  enabled: boolean
  priority_provider: string
  prompt: string
  interval_minutes: number
  triggers: Record<string, boolean>
  auto_enabled: boolean
  next_run_at: string | null
}

export interface Recommendation {
  status_by_name?:string|null
  id: number
  provider: string
  trigger: string
  summary: string
  content: string
  request_context: AiPreview | null
  excluded: boolean
  created_at: string
  structured: Advice | null
  status: string
  status_by: number | null
  status_at: string | null
  comment: string
  snapshot_at: string | null
  snapshot_version: string | null
  last_seen_at: string | null
}

export interface RelatedObjects { task_ids:number[];track_ids:number[];user_ids:number[];incident_ids:number[] }
export interface Advice {title:string;situation:string;grounds:string[];consequence:string;action:string;limitations:string[];related:RelatedObjects;significance:string;freshness:string}
export interface AdvisorJob {id:number;kind:string;trigger:string;state:string;question:string;answer:{answer?:string;grounds?:string[];limitations?:string[];related?:RelatedObjects;result?:string}|null;error_code:string|null;attempts:number;created_at:string;snapshot_at:string|null;snapshot_version:string|null;next_attempt_at:string}
export interface AdvisorQuota {day_remaining:number;day_limit:number;reset_at:string;reset_seconds:number;minute_used:number;minute_limit:number;minute_tokens:number;token_limit:number;queued:number;key_saved:boolean;vault_available:boolean}
export interface ProviderSettings {model:string;rpm:number;rpd:number;tpm:number;max_attempts:number;max_input_tokens:number;key_saved:boolean;vault_available:boolean}

export interface AiPreview {
  mode: 'mock'
  provider: string
  prompt: string
  trigger: string
  question: string
  snapshot: Record<string, unknown>
}

export interface TelegramMessage {
  id: number
  project_id: number | null
  event_type: string
  text: string
  mentions: string[]
  mode: string
  created_at: string
}

export interface SandboxCheck {
  name: string
  title: string
  status: 'passed' | 'failed'
  detail: string
  duration_ms: number
}

export interface SandboxRun {
  id: number
  scenario: string
  status: 'ok' | 'error'
  logs: string[]
  checks: SandboxCheck[]
  duration_ms: number
  created_at: string
}

export interface SandboxWorkspace {
  project_id: number | null
  project_name: string | null
  state: string | null
  counts: Record<string, number>
  team: {user_id:number; login:string; display_name:string; role:string; active:boolean}[]
}

export interface UserInfo {
  id: number
  login: string
  display_name: string
  telegram_username: string | null
  active: boolean
  created_at: string
}

export interface Participant {
  id: number
  login: string
  display_name: string
  telegram_username: string | null
  traffic_status: string
  active_tasks: number
  active_timer_seconds: number
}

export interface Module {
  id: number
  name: string
  description: string | null
  traffic_status: string
  created_at: string
}

export interface Analytics {
  summary: OperationalSummary
  forecast: {remaining_seconds:number;calendar_estimate_seconds:number|null;status:string;finish:string|null;margin_seconds:number|null;assumptions:string}
  deviations: {task_id:number;title:string;actual_seconds:number;overrun_seconds:number;ahead_seconds:number;overdue_seconds:number;owners:string[]}[]
  kpi: {
    project_id: number
    name: string
    state: string
    deadline_msk: string | null
    deadline_seconds_left: number | null
    total_tasks: number
    completed_tasks: number
    in_progress_tasks: number
    overdue_tasks: number
    active_timers: number
    active_participants: number
    progress_percent: number
    estimate_seconds: number
    actual_seconds: number
    calendar_seconds: number
  }
  participants: Participant[]
  modules: { id: number; name: string; total: number; done: number; progress: number; traffic_status: string }[]
  burn_down: { date: string; created: number; completed: number; remaining: number; ideal?:number; observation_only?:boolean }[]
  time_by_user: { user_id: number | null; login: string; display_name: string; seconds: number }[]
  active_incidents: { id: number; number:number; title: string; level: string; status: string }[]
  risks: { type: string; task_id?: number; incident_id?: number; title: string; level?: string; status?: string; deadline?: string | null }[]
}

export interface Measure {numerator:number;denominator:number;percent:number|null;missing_count:number;incomplete:boolean;unknown_reason:string|null}
export interface SummaryTask extends Task {track_name:string|null;availability:'done'|'active'|'waiting'|'ready';waiting_reasons:string[];missing:string[]}
export interface OperationalSummary {
  project_id:number;generated_at:string;project_state:string
  period:{start:string|null;deadline:string|null;phase:string;duration_seconds:number|null;elapsed_seconds:number|null;remaining_seconds:number|null;until_start_seconds:number|null;overdue_seconds:number|null;percent:number|null;unknown_reason:string|null}
  progress:{tasks:Measure;duration:Measure}
  plan:{status:string;incomplete:boolean;finish:string|null;deadline_delta_seconds:number|null;source:string;covered_tasks:number;total_tasks:number;limitations:string[]}
  tasks:SummaryTask[]
  tracks:{id:number|null;name:string;task_ids:number[];done:number;total:number;percent:number|null;active:number;waiting:number;overdue:number;blocked:number;incident_ids:number[]}[]
  incidents:(IncidentSummary&{source_task_id:number|null;cascade_depth:number;targets:{target_type:string;target_id:number}[];hard_task_ids:number[];potential_task_ids:number[];direct_task_ids:number[];affected_task_ids:number[];track_ids:number[];limitations:string[]})[]
  participants:{id:number;display_name:string;traffic_status:string;task_ids:number[];active_ids:number[];ready_ids:number[];waiting_ids:number[];incident_ids:number[];overlaps:number[][];downstream:Cascade}[]
  attention:{code:string;reason:string;task_ids:number[];incident_id:number|null;user_ids:number[]}[]
  unassigned_ids:number[];limitations:string[]
}

export interface DashboardKpi {
  deadline_seconds_left: number | null
  total_tasks: number
  completed_tasks: number
  in_progress_tasks: number
  overdue_tasks: number
  active_timers: number
  active_participants: number
  progress_percent: number
  estimate_seconds: number
  actual_seconds: number
  calendar_seconds: number
  risks: { task_id: number; title: string; deadline: string | null; type: string }[]
}

export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit, previewAttempt=0): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let code = 'HTTP_ERROR'
    let message = res.statusText
    try {
      const body = await res.json()
      code = body?.error?.code ?? code
      message = body?.error?.message ?? message
      if (code === 'VALIDATION_ERROR' && body?.error?.details?.errors?.[0]?.msg) message = body.error.details.errors[0].msg.replace(/^Value error, /,'')
      if(code==='PLANNING_PREVIEW' && previewAttempt<3) {
        const preview=body.error.details as Preview
        if(await approvePlan(preview)) return request<T>(path,{...init,headers:{'Content-Type':'application/json',...init?.headers,'X-Planning-Confirm':preview.token}},previewAttempt+1)
        throw new ApiError(409,'CANCELLED','Изменение отменено')
      }
    } catch (e) {
      if(e instanceof ApiError)throw e
      /* ignore */
    }
    if(code==='VERSION_CONFLICT')window.dispatchEvent(new Event('project-updated'))
    throw new ApiError(res.status, code, message)
  }
  const body=await res.json()
  if(init?.method && !['GET','HEAD'].includes(init.method))window.dispatchEvent(new Event('project-updated'))
  return body
}

export function currentProject(): number {
  const id = Number(localStorage.getItem('hcc-project') ?? 1)
  return Number.isFinite(id) && id > 0 ? id : 1
}

export function setCurrentProject(id: number) {
  localStorage.setItem('hcc-project', String(id))
}

function pid() {
  return currentProject()
}

export const api = {
  telegramSettings: ():Promise<TelegramSettingsData> => request(`/api/v1/projects/${pid()}/telegram`),
  saveTelegram: (payload:{chat_id:string|null;routes:Record<string,number|null>;public_url:string;confirm_chat:boolean}):Promise<TelegramSettingsData> => request(`/api/v1/projects/${pid()}/telegram`,{method:'PUT',body:JSON.stringify(payload)}),
  telegramDeliveries: ():Promise<Delivery[]> => request(`/api/v1/projects/${pid()}/telegram/deliveries`),
  testTelegram: (chat:string,thread:number|null) => request(`/api/v1/projects/${pid()}/telegram/test`,{method:'POST',body:JSON.stringify({confirmed_chat_id:chat,thread_id:thread})}),
  retryTelegram: (id:number,accept:boolean) => request(`/api/v1/projects/${pid()}/telegram/deliveries/${id}/retry`,{method:'POST',body:JSON.stringify({accept_duplicate_risk:accept})}),
  deleteTelegramKey: () => request('/api/v1/telegram/bot/key',{method:'DELETE'}),
  deletionPreview: (id:number):Promise<DeletionPreview> => request(`/api/v1/admin/users/${id}/deletion-preview`),
  deleteUser: (id:number,body:{confirm:true;preview_version:string;incident_captains:Record<number,number>;task_primaries:Record<number,number>}) => request(`/api/v1/admin/users/${id}`,{method:'DELETE',body:JSON.stringify(body)}),
  planning: ():Promise<PlanningData> => request(`/api/v1/projects/${pid()}/planning`),
  planCommand: (revision:number,op:string,values:Record<string,unknown>={}):Promise<PlanningData> => request(`/api/v1/projects/${pid()}/planning`,{method:'POST',body:JSON.stringify({revision,op,...values})}),
  login: (login: string, password: string) =>
    request('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ login, password }) }),
  logout: () => request('/api/v1/auth/logout', { method: 'POST' }),
  me: (): Promise<Me> => request('/api/v1/auth/me'),

  projects: (): Promise<Project[]> => request('/api/v1/projects'),
  createProject: (name: string) =>
    request('/api/v1/projects', { method: 'POST', body: JSON.stringify({ name }) }),
  patchProject: (payload: Record<string, unknown>) =>
    request(`/api/v1/projects/${pid()}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  columns: (): Promise<Column[]> => request(`/api/v1/projects/${pid()}/columns`),
  createColumn: (title: string, autoStart = false, autoStop = false) =>
    request(`/api/v1/projects/${pid()}/columns`, {
      method: 'POST',
      body: JSON.stringify({ title, auto_start_timer: autoStart, auto_stop_timer: autoStop }),
    }),
  patchColumn: (id: number, payload: Record<string, unknown>) =>
    request(`/api/v1/columns/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteColumn: (id: number, target?: number) => request(`/api/v1/columns/${id}${target ? `?target_column_id=${target}` : ''}`, { method: 'DELETE' }),
  modules: (): Promise<Module[]> => request(`/api/v1/projects/${pid()}/modules`),
  createModule: (name: string, description?: string) =>
    request(`/api/v1/projects/${pid()}/modules`, { method: 'POST', body: JSON.stringify({ name, description: description ?? null }) }),
  patchModule: (id: number, payload: Record<string, unknown>) =>
    request(`/api/v1/modules/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteModule: (id: number) => request(`/api/v1/modules/${id}`, { method: 'DELETE' }),
  participants: (): Promise<Participant[]> => request(`/api/v1/projects/${pid()}/participants`),
  analytics: (): Promise<Analytics> => request(`/api/v1/projects/${pid()}/analytics`),
  dashboard: (): Promise<DashboardKpi> => request(`/api/v1/projects/${pid()}/dashboard`),

  task: (id:number): Promise<Task> => request(`/api/v1/tasks/${id}`),
  incidentImpact: (id:number, depth:number): Promise<{task_ids:number[];user_ids:number[]}> => request(`/api/v1/tasks/${id}/incident-impact?depth=${depth}`),
  incidentCascade: (id:number):Promise<Cascade> => request(`/api/v1/tasks/${id}/incident-cascade`),
  tasks: (): Promise<Task[]> => request(`/api/v1/projects/${pid()}/tasks`),
  createTask: (payload: Record<string, unknown>): Promise<Task> =>
    request(`/api/v1/projects/${pid()}/tasks`, { method: 'POST', body: JSON.stringify(payload) }),
  patchTask: (taskId: number, payload: Record<string, unknown>, version: number) =>
    request(`/api/v1/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify({ ...payload, version }) }),
  moveTask: (taskId: number, columnKey: string, version: number) =>
    request(`/api/v1/tasks/${taskId}/move`, { method: 'POST', body: JSON.stringify({ column_key: columnKey, version }) }),
  taskHistory: (taskId: number): Promise<{ text:string; action: string; actor_id: number | null; data: Record<string, unknown>; created_at: string }[]> =>
    request(`/api/v1/tasks/${taskId}/history`),
  setAssignees: (taskId: number, assignees: { user_id: number; is_primary: boolean }[]) =>
    request(`/api/v1/tasks/${taskId}/assignees`, { method: 'PUT', body: JSON.stringify({ assignees }) }),
  addDependency: (taskId: number, predecessorId: number, linkType = 'blocked_by') =>
    request(`/api/v1/tasks/${taskId}/dependencies`, {
      method: 'POST',
      body: JSON.stringify({ predecessor_id: predecessorId, link_type: linkType }),
    }),
  removeDependency: (taskId: number, predecessorId: number) =>
    request(`/api/v1/tasks/${taskId}/dependencies/${predecessorId}`, { method: 'DELETE' }),
  checklistAdd: (taskId: number, text: string) =>
    request(`/api/v1/tasks/${taskId}/checklist`, { method: 'POST', body: JSON.stringify({ text }) }),
  checklistPatch: (itemId: number, done: boolean) =>
    request(`/api/v1/checklist/${itemId}`, { method: 'PATCH', body: JSON.stringify({ done }) }),
  checklistDelete: (itemId: number) => request(`/api/v1/checklist/${itemId}`, { method: 'DELETE' }),
  timer: (taskId: number, action: 'start' | 'pause' | 'stop') =>
    request(`/api/v1/tasks/${taskId}/timer/${action}`, { method: 'POST' }),
  timeAdjust: (taskId: number, accumulatedSeconds: number) =>
    request(`/api/v1/tasks/${taskId}/time-adjustment`, { method: 'POST', body: JSON.stringify({ accumulated_seconds: accumulatedSeconds }) }),

  incident: (id:number): Promise<Incident> => request(`/api/v1/incidents/${id}`),
  incidents: (): Promise<Incident[]> => request(`/api/v1/projects/${pid()}/incidents`),
  createIncident: (payload: Record<string, unknown>) =>
    request(`/api/v1/projects/${pid()}/incidents`, { method: 'POST', body: JSON.stringify(payload) }),
  confirmRed: (id: number, confirm: boolean, comment?: string) =>
    request(`/api/v1/incidents/${id}/confirm-red`, { method: 'POST', body: JSON.stringify({ confirm, comment }) }),
  resolveIncident: (id: number, resolution: string) =>
    request(`/api/v1/incidents/${id}/resolve`, { method: 'POST', body: JSON.stringify({ resolution }) }),
  commentIncident: (id: number, text: string) =>
    request(`/api/v1/incidents/${id}/events`, { method: 'POST', body: JSON.stringify({ text }) }),

  aiSettings: (): Promise<AiSettings> => request(`/api/v1/projects/${pid()}/ai/settings`),
  advisorQuota: (): Promise<AdvisorQuota> => request(`/api/v1/projects/${pid()}/ai/quota`),
  advisorJobs: (): Promise<AdvisorJob[]> => request(`/api/v1/projects/${pid()}/ai/requests`),
  askAdvisor: (kind:'question'|'analysis', question=''):Promise<AdvisorJob> => request(`/api/v1/projects/${pid()}/ai/requests`,{method:'POST',body:JSON.stringify({kind,question})}),
  decideAdvice: (id:number,status:string,comment:string) => request(`/api/v1/projects/${pid()}/ai/recommendations/${id}`,{method:'PATCH',body:JSON.stringify({status,comment})}),
  providerSettings: ():Promise<ProviderSettings> => request('/api/v1/ai/provider'),
  patchProvider: (payload:Partial<ProviderSettings>) => request('/api/v1/ai/provider',{method:'PATCH',body:JSON.stringify(payload)}),
  deleteAdvisorKey: () => request('/api/v1/ai/provider/key',{method:'DELETE'}),
  patchAiSettings: (payload: Record<string, unknown>) =>
    request(`/api/v1/projects/${pid()}/ai/settings`, { method: 'PATCH', body: JSON.stringify(payload) }),
  previewAi: (question = '', trigger = 'manual'): Promise<AiPreview> => request(`/api/v1/projects/${pid()}/ai/preview`, { method: 'POST', body: JSON.stringify({trigger, question}) }),
  runAi: (question = '', trigger = 'manual') => request(`/api/v1/projects/${pid()}/ai/run`, { method: 'POST', body: JSON.stringify({ trigger, question }) }),
  recommendations: (): Promise<Recommendation[]> => request(`/api/v1/projects/${pid()}/ai/recommendations`),
  excludeRecommendation: (id: number) => request(`/api/v1/projects/${pid()}/ai/recommendations/${id}/exclude`, {method:'POST'}),

  notifications: (): Promise<Notification[]> => request('/api/v1/notifications'),
  openNotification: (id:number): Promise<{target:{type:'task'|'incident';id:number;project_id:number}|null;message:string}> => request(`/api/v1/notifications/${id}/open`, {method:'POST'}),
  readNotification: (id: number) => request(`/api/v1/notifications/${id}/read`, { method: 'POST' }),
  readAllNotifications: () => request('/api/v1/notifications/read-all', { method: 'POST' }),
  deleteNotification: (id: number) => request(`/api/v1/notifications/${id}`, { method: 'DELETE' }),
  clearNotifications: () => request('/api/v1/notifications', { method: 'DELETE' }),

  users: (): Promise<UserInfo[]> => request('/api/v1/admin/users'),
  createUser: (payload: Record<string, unknown>) =>
    request('/api/v1/admin/users', { method: 'POST', body: JSON.stringify(payload) }),
  patchUser: (id: number, payload: Record<string, unknown>) =>
    request(`/api/v1/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  resetPassword: (id: number, newPassword: string) =>
    request(`/api/v1/admin/users/${id}/password-reset`, { method: 'POST', body: JSON.stringify({ new_password: newPassword }) }),
  deactivateUser: (id: number) => request(`/api/v1/admin/users/${id}/deactivate`, { method: 'POST' }),
  assignRole: (userId: number, role: string, projectId?: number | null) =>
    request('/api/v1/admin/roles', { method: 'POST', body: JSON.stringify({ user_id: userId, role, project_id: role === 'admin' ? null : projectId ?? pid() }) }),
  roles: (): Promise<{ id: number; user_id: number; role: string; project_id: number | null }[]> =>
    request('/api/v1/admin/roles'),
  revokeRole: (id: number) => request(`/api/v1/admin/roles/${id}`, { method: 'DELETE' }),
  loginEvents: (): Promise<{ id: number; login: string; ip: string | null; success: boolean; reason: string | null; created_at: string }[]> =>
    request('/api/v1/admin/login-events'),
  blockIp: (ip: string) => request('/api/v1/admin/ip-rules', { method: 'POST', body: JSON.stringify({ ip }) }),
  resetIpLimit: (ip: string) => request(`/api/v1/admin/ip-rules/reset?ip=${encodeURIComponent(ip)}`, { method: 'POST' }),
  backups: (): Promise<{ id: number; path: string; kind: string; created_at: string }[]> =>
    request('/api/v1/admin/backups'),
  createBackup: () => request('/api/v1/admin/backups', { method: 'POST' }),
  restoreBackup: (id: number) => request(`/api/v1/admin/backups/${id}/restore`, { method: 'POST', body: JSON.stringify({ confirm: true }) }),
  runJobs: () => request('/api/v1/admin/jobs/run', { method: 'POST' }),

  sandboxScenarios: (): Promise<Record<string, string>> => request('/api/v1/admin/sandbox/scenarios'),
  telegramMessages: (): Promise<TelegramMessage[]> => request(`/api/v1/admin/sandbox/telegram?project_id=${pid()}`),
  sandboxWorkspace: (): Promise<SandboxWorkspace> => request('/api/v1/admin/sandbox/workspace'),
  sandboxChecks: (): Promise<Record<string,string>> => request('/api/v1/admin/sandbox/checks'),
  sandboxReset: (projectId: number): Promise<{status:string; archive_path:string; workspace:SandboxWorkspace}> =>
    request('/api/v1/admin/sandbox/reset', {method:'POST',body:JSON.stringify({project_id:projectId,confirm:true})}),
  sandboxTelegram: (projectId: number): Promise<TelegramMessage[]> => request('/api/v1/admin/sandbox/telegram?project_id=' + projectId),
  sandboxRun: (scenario: string): Promise<SandboxRun> =>
    request('/api/v1/admin/sandbox/run', { method: 'POST', body: JSON.stringify({ scenario }) }),
  sandboxRuns: (): Promise<SandboxRun[]> =>
    request('/api/v1/admin/sandbox/runs'),

  completionVote: (action: 'complete' | 'reopen') =>
    request(`/api/v1/projects/${pid()}/completion-votes`, { method: 'POST', body: JSON.stringify({ action }) }),
}

export interface TelegramSettingsData {
  project_id:number;bot_connected:boolean;chat_id:string|null;routes:Record<string,number|null>;public_url:string
  events:Record<string,string>;missing_usernames:{id:number;name:string}[];pending:number;queue_policy:string
}
export interface Delivery {
  id:number;event_type:string;chat_id:string;thread_id:number|null;state:string;attempts:number;error:string|null
  created_at:string;attempted_at:string|null;sent_at:string|null;next_attempt_at:string;parts_sent:number
}
export interface DeletionPreview {
  version:string;blocked:boolean;deletion_limits:string;links:Record<string,number>
  tasks:{id:number;title:string;project:string;project_id:number;needs_primary:boolean;remaining:{id:number;name:string;is_primary:boolean}[]}[]
  projects:{id:number;name:string;captains:{id:number;name:string}[];incidents:{id:number;number:number;title:string}[]}[]
}

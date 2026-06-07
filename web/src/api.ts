import type { Page, PlanResult, Project, Session, SessionDetail } from './types'

const BASE = ''

async function rpcCall<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(`${BASE}/v1/rpc`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, params }),
  })
  const data = await res.json()
  if (data.error) {
    throw new Error(`${data.error.code}: ${data.error.message}`)
  }
  return data.result as T
}

export async function listProjects(): Promise<Page<Project>> {
  return rpcCall('project.list', {})
}

export async function listSessions(projectId: string): Promise<Page<Session>> {
  return rpcCall('session.list', { project_id: projectId })
}

export async function getSessionDetail(
  sessionId: string,
  messageLimit = 50,
): Promise<SessionDetail> {
  return rpcCall('session.detail', {
    session_id: sessionId,
    message_limit: messageLimit,
  })
}

export async function createSession(projectId: string): Promise<Session> {
  return rpcCall('session.create', { project_id: projectId })
}

/**
 * Stream session.resume_create:
 *
 *   1. Backend creates a fresh session under the project.
 *   2. Backend yields <<session-created>>{session}<</session-created>>
 *      synthetic TextDelta — frontend uses this to switch active session
 *      BEFORE LLM events start arriving.
 *   3. Backend then streams the LLM's resume turn (welcome +
 *      ask_user_question with progress-aware options).
 *
 * Same shape as ``streamCreateLearningProject`` but:
 *   - takes only project_id (no plan, project already exists)
 *   - emits "session-created" sentinel instead of "project-created"
 */
export interface ResumeCreateSessionCallbacks {
  onSessionCreated: (session: Session) => void
  onEvent: (event: Record<string, unknown>) => void
  onError: (msg: string) => void
  onDone?: () => void
}

export function streamResumeCreateSession(
  projectId: string,
  callbacks: ResumeCreateSessionCallbacks,
): AbortController {
  const controller = new AbortController()
  const body = JSON.stringify({
    method: 'session.resume_create',
    params: { project_id: projectId },
  })

  fetch(`${BASE}/v1/turn/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        callbacks.onError(`HTTP ${res.status}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) {
        callbacks.onError('No response body')
        return
      }
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event: Record<string, unknown>
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          // Intercept session-created / session-error sentinels
          if (event.type === 'text_delta') {
            const text = (event.text as string) ?? ''
            const created = /<<session-created>>([\s\S]*?)<<\/session-created>>/.exec(text)
            if (created) {
              try {
                const payload = JSON.parse(created[1]) as Session
                callbacks.onSessionCreated(payload)
              } catch (e) {
                callbacks.onError(`bad session-created payload: ${String(e)}`)
              }
              continue
            }
            const errMatch = /<<session-error>>([\s\S]*?)<<\/session-error>>/.exec(text)
            if (errMatch) {
              callbacks.onError(errMatch[1])
              continue
            }
          }
          if (event.type === 'error') {
            callbacks.onError(`${event.code}: ${event.message}`)
            continue
          }
          callbacks.onEvent(event)
        }
      }
      callbacks.onDone?.()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') callbacks.onError(String(err))
    })

  return controller
}

export interface ResetResult {
  cleared: boolean
  items_cleared: string[]
}

export async function resetLearning(projectId: string): Promise<ResetResult> {
  return rpcCall('learning.reset', { project_id: projectId })
}

export interface DeletedResult {
  deleted: boolean
}

export async function deleteProject(projectId: string): Promise<DeletedResult> {
  return rpcCall('project.delete', { id: projectId, hard: true })
}

export async function deleteSession(sessionId: string): Promise<DeletedResult> {
  return rpcCall('session.delete', { session_id: sessionId, hard: true })
}

export async function createLearningProject(
  topic: string,
  goal: string,
  plan: PlanResult,
): Promise<CreateLearningProjectResult> {
  return rpcCall('learning.create_project', { topic, goal, plan })
}

export interface PlanPreviewParams {
  topic: string
  goal: 'interview' | 'deep' | 'easy'
  feedback?: string | null
  previous_plan?: PlanResult | null
}

export interface PlanPreviewCallbacks {
  onProgress: (label: string) => void
  onPlan: (plan: PlanResult) => void
  onError: (msg: string) => void
  onDone?: () => void
}

/**
 * Stream the plan-preview endpoint.
 *
 * Renders tool calls into onProgress("[⏳ web_search]"-style strings),
 * then on TurnEnd extracts the embedded plan JSON (the backend ships it
 * as a synthetic <<plan-result>>{...}<</plan-result>> TextDelta) and
 * calls onPlan. On parse failure calls onError.
 */
export function streamPlanPreview(
  params: PlanPreviewParams,
  callbacks: PlanPreviewCallbacks,
): AbortController {
  const controller = new AbortController()

  const body = JSON.stringify({
    method: 'learning.plan_preview',
    params,
  })

  let textBuffer = ''

  fetch(`${BASE}/v1/turn/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        callbacks.onError(`HTTP ${res.status}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) {
        callbacks.onError('No response body')
        return
      }
      const decoder = new TextDecoder()
      let buffer = ''
      let resolved = false
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event: Record<string, unknown>
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          const type = event.type as string
          if (type === 'tool_call_start') {
            const name = event.name as string
            const args = event.args as Record<string, unknown> | undefined
            const q = args?.query ? ` "${args.query}"` : ''
            callbacks.onProgress(`⏳ ${name}${q}`)
          } else if (type === 'text_delta') {
            textBuffer += (event.text as string) ?? ''
          } else if (type === 'turn_end') {
            resolved = true
            const planMatch = /<<plan-result>>([\s\S]*?)<<\/plan-result>>/.exec(textBuffer)
            if (planMatch) {
              try {
                callbacks.onPlan(JSON.parse(planMatch[1]) as PlanResult)
              } catch (e) {
                callbacks.onError(`plan JSON parse failed: ${String(e)}`)
              }
            } else if (/<<plan-error>>/.test(textBuffer)) {
              callbacks.onError('LLM did not produce a parseable plan')
            } else {
              callbacks.onError('No plan emitted in stream')
            }
          } else if (type === 'error') {
            resolved = true
            callbacks.onError(`${event.code}: ${event.message}`)
          }
        }
      }
      // Fallback: if stream ended without turn_end (e.g. backend crashed,
      // max loops hit), still check for plan markers in the buffer.
      if (!resolved) {
        const planMatch = /<<plan-result>>([\s\S]*?)<<\/plan-result>>/.exec(textBuffer)
        if (planMatch) {
          try {
            callbacks.onPlan(JSON.parse(planMatch[1]) as PlanResult)
          } catch (e) {
            callbacks.onError(`plan JSON parse failed: ${String(e)}`)
          }
        } else if (/<<plan-error>>/.test(textBuffer)) {
          callbacks.onError('LLM did not produce a parseable plan')
        } else {
          callbacks.onError('No plan emitted in stream')
        }
      }
      callbacks.onDone?.()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') callbacks.onError(String(err))
    })

  return controller
}

export interface CreateLearningProjectResult {
  project: Project
  session: Session
}

/**
 * Stream the create_project turn.
 *
 * Two phases:
 *   1. Backend yields a synthetic <<project-created>>{project, session}<</project-created>>
 *      TextDelta as soon as files + DB are committed. We surface this via
 *      onCreated — frontend should immediately switch active session.
 *   2. Backend then streams the LLM's priming turn (welcome +
 *      ask_user_question). We forward each event to onEvent so the chat
 *      view (already mounted with the new session_id) renders normally.
 *
 * On commit failure, backend emits <<project-error>>...<</project-error>>
 * and ends the stream — we report via onError.
 */
export interface CreateLearningProjectCallbacks {
  onCreated: (result: CreateLearningProjectResult) => void
  onEvent: (event: Record<string, unknown>) => void
  onError: (msg: string) => void
  onDone?: () => void
}

export function streamCreateLearningProject(
  topic: string,
  goal: string,
  plan: PlanResult,
  callbacks: CreateLearningProjectCallbacks,
): AbortController {
  const controller = new AbortController()
  const body = JSON.stringify({
    method: 'learning.create_project',
    params: { topic, goal, plan },
  })

  fetch(`${BASE}/v1/turn/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        callbacks.onError(`HTTP ${res.status}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) {
        callbacks.onError('No response body')
        return
      }
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event: Record<string, unknown>
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          // Intercept the synthetic project-created/error sentinels
          // before they reach the chat-event handler.
          if (event.type === 'text_delta') {
            const text = (event.text as string) ?? ''
            const created = /<<project-created>>([\s\S]*?)<<\/project-created>>/.exec(text)
            if (created) {
              try {
                const payload = JSON.parse(created[1]) as CreateLearningProjectResult
                callbacks.onCreated(payload)
              } catch (e) {
                callbacks.onError(`bad project-created payload: ${String(e)}`)
              }
              continue
            }
            const errMatch = /<<project-error>>([\s\S]*?)<<\/project-error>>/.exec(text)
            if (errMatch) {
              callbacks.onError(errMatch[1])
              continue
            }
          }
          if (event.type === 'error') {
            callbacks.onError(`${event.code}: ${event.message}`)
            continue
          }
          callbacks.onEvent(event)
        }
      }
      callbacks.onDone?.()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') callbacks.onError(String(err))
    })

  return controller
}

export interface StreamCallbacks {
  onEvent: (event: Record<string, unknown>) => void
  onError?: (error: string) => void
  onDone?: () => void
}

export function streamTurn(
  sessionId: string,
  text: string,
  projectId: string | undefined,
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController()

  const body = JSON.stringify({
    method: 'turn.send',
    params: { session_id: sessionId, text },
    project_id: projectId,
  })

  fetch(`${BASE}/v1/turn/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        callbacks.onError?.(`HTTP ${res.status}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) {
        callbacks.onError?.('No response body')
        return
      }
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6))
              callbacks.onEvent(event)
            } catch {
              // skip malformed events
            }
          }
        }
      }
      callbacks.onDone?.()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError?.(String(err))
      }
    })

  return controller
}

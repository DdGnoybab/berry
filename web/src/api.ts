import type { Page, Project, Session } from './types'

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

export async function createSession(projectId: string): Promise<Session> {
  return rpcCall('session.create', { project_id: projectId })
}

export interface ResetResult {
  cleared: boolean
  items_cleared: string[]
}

export async function resetLearning(projectId: string): Promise<ResetResult> {
  return rpcCall('learning.reset', { project_id: projectId })
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

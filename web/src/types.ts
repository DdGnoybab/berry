export interface AgentEvent {
  type: 'turn_start' | 'text_delta' | 'tool_call_start' | 'approval_asked' | 'tool_result' | 'turn_end' | 'error'
  session_id?: string
  text?: string
  id?: string
  name?: string
  args?: Record<string, unknown>
  output?: string
  is_error?: boolean
  stop_reason?: string
  code?: string
  message?: string
}

export interface SuggestionOption {
  label: string
  description?: string | null
  recommended: boolean
}

export interface SuggestionEvent {
  type: 'suggestion_emitted'
  suggestion_id: string
  prompt: string
  options: SuggestionOption[]
}

export interface ProjectProgress {
  phase: 'uninitialized' | 'planning' | 'learning' | 'done' | string
  percent: number
  done_atoms: number
  total_atoms: number
  done_modules: number
  total_modules: number
  current_atom: string | null
  topic: string | null
}

export interface Project {
  id: string
  name: string
  title: string
  domain: string
  created_at: string
  progress?: ProjectProgress | null
}

export interface PlanAtom {
  id: string
  name: string
}

export interface PlanModule {
  id: string
  name: string
  atoms: PlanAtom[]
}

export interface PlanResult {
  modules: PlanModule[]
  interview_md: string
}

export interface Session {
  id: string
  project_id: string
  status: string
  started_at: string
  title: string | null
  message_count: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCallInfo[]
  suggestions?: SuggestionEvent
  timestamp: Date
}

export interface ToolCallInfo {
  id: string
  name: string
  args: Record<string, unknown>
  output?: string
  isError?: boolean
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export interface MessageEnvelope {
  role: string
  content: Array<{ type: string; text?: string; [k: string]: unknown }>
  created_at: string
  metadata: Record<string, unknown>
}

export interface SessionDetail {
  meta: Session
  messages: MessageEnvelope[]
}

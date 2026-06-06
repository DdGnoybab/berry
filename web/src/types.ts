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
  key: string
  label: string
  recommended: boolean
}

export interface SuggestionEvent {
  type: 'suggestion_options'
  suggestion_id: string
  context: string
  prompt: string
  options: SuggestionOption[]
}

export interface Project {
  id: string
  name: string
  title: string
  domain: string
  created_at: string
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

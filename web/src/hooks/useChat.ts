import { useCallback, useRef, useState } from 'react'
import { streamTurn } from '../api'
import type { ChatMessage, SuggestionEvent, ToolCallInfo } from '../types'

let msgCounter = 0
function makeId(): string {
  return `msg-${Date.now()}-${++msgCounter}`
}

export function useChat(sessionId: string | null, projectId: string | undefined) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const sendMessage = useCallback(
    (text: string) => {
      if (!sessionId || !text.trim() || isStreaming) return

      const userMsg: ChatMessage = {
        id: makeId(),
        role: 'user',
        content: text,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, userMsg])
      setIsStreaming(true)

      let assistantId = ''
      let assistantContent = ''
      let currentToolCalls: ToolCallInfo[] = []

      abortRef.current = streamTurn(sessionId, text, projectId, {
        onEvent(event) {
          const e = event as Record<string, unknown>
          const type = e.type as string

          switch (type) {
            case 'turn_start':
              assistantId = makeId()
              assistantContent = ''
              currentToolCalls = []
              setMessages((prev) => [
                ...prev,
                {
                  id: assistantId,
                  role: 'assistant' as const,
                  content: '',
                  toolCalls: [],
                  timestamp: new Date(),
                },
              ])
              break

            case 'text_delta':
              assistantContent += (e.text as string) ?? ''
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: assistantContent }
                    : m,
                ),
              )
              break

            case 'tool_call_start':
              currentToolCalls = [
                ...currentToolCalls,
                {
                  id: (e.id as string) ?? '',
                  name: (e.name as string) ?? '',
                  args: (e.args as Record<string, unknown>) ?? {},
                },
              ]
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, toolCalls: [...currentToolCalls] }
                    : m,
                ),
              )
              break

            case 'tool_result':
              currentToolCalls = currentToolCalls.map((tc) =>
                tc.id === e.id
                  ? { ...tc, output: e.output as string, isError: e.is_error as boolean }
                  : tc,
              )
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, toolCalls: [...currentToolCalls] }
                    : m,
                ),
              )
              break

            case 'suggestion_options': {
              const suggestion: SuggestionEvent = {
                type: 'suggestion_options',
                suggestion_id: (e.suggestion_id as string) ?? '',
                context: (e.context as string) ?? '',
                prompt: (e.prompt as string) ?? '',
                options: (e.options as Array<Record<string, unknown>>)?.map((o) => ({
                  key: (o.key as string) ?? '',
                  label: (o.label as string) ?? '',
                  recommended: (o.recommended as boolean) ?? false,
                })) ?? [],
              }
              // Attach to the current assistant message
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, suggestions: suggestion }
                    : m,
                ),
              )
              break
            }

            case 'turn_end':
              setIsStreaming(false)
              break

            case 'error':
              setMessages((prev) => [
                ...prev,
                {
                  id: makeId(),
                  role: 'assistant' as const,
                  content: `Error: ${(e.code as string) ?? 'UNKNOWN'} - ${(e.message as string) ?? 'Unknown error'}`,
                  timestamp: new Date(),
                },
              ])
              setIsStreaming(false)
              break
          }
        },
        onError(err) {
          setMessages((prev) => [
            ...prev,
            {
              id: makeId(),
              role: 'assistant' as const,
              content: `Connection error: ${err}`,
              timestamp: new Date(),
            },
          ])
          setIsStreaming(false)
        },
        onDone() {
          setIsStreaming(false)
        },
      })
    },
    [sessionId, projectId, isStreaming],
  )

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
  }, [])

  return { messages, isStreaming, sendMessage, stopStreaming, clearMessages }
}

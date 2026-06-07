import { useCallback, useEffect, useRef, useState } from 'react'
import { getSessionDetail, streamTurn } from '../api'
import type { ChatMessage, SuggestionEvent, ToolCallInfo } from '../types'

let msgCounter = 0
function makeId(): string {
  return `msg-${Date.now()}-${++msgCounter}`
}

/**
 * Mutable per-turn state held outside React state — same accumulators
 * the reducer uses (assistantId, accumulated content/tool calls).
 *
 * Owned by useChat for the duration of one turn; reset between turns.
 */
interface TurnAccumulator {
  assistantId: string
  assistantContent: string
  currentToolCalls: ToolCallInfo[]
}

function freshAccumulator(): TurnAccumulator {
  return { assistantId: '', assistantContent: '', currentToolCalls: [] }
}

export function useChat(sessionId: string | null, projectId: string | undefined) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const accRef = useRef<TurnAccumulator>(freshAccumulator())
  const skipHistoryRef = useRef(false)

  useEffect(() => {
    if (!sessionId) {
      setMessages([])
      return
    }
    if (skipHistoryRef.current) {
      skipHistoryRef.current = false
      return
    }
    let cancelled = false
    getSessionDetail(sessionId)
      .then((detail) => {
        if (cancelled) return
        const loaded: ChatMessage[] = detail.messages
          .filter((env) => env.role === 'user' || env.role === 'assistant')
          .map((env, i) => ({
            id: `hist-${sessionId}-${i}`,
            role: env.role as 'user' | 'assistant',
            content: env.content
              .filter((b) => b.type === 'text')
              .map((b) => b.text ?? '')
              .join(''),
            timestamp: new Date(env.created_at),
          }))
        setMessages((prev) => (prev.length > 0 ? prev : loaded))
      })
      .catch(() => {
        if (!cancelled) setMessages((prev) => prev)
      })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  /**
   * Apply ONE backend SSE event to the message state.
   * Pure function over the accumulator + setMessages — used by both
   * normal turn streaming (via streamTurn) and externally-driven
   * streams (e.g. learning.create_project's priming turn).
   */
  const feedEvent = useCallback((event: Record<string, unknown>) => {
    const acc = accRef.current
    const type = event.type as string

    switch (type) {
      case 'turn_start': {
        acc.assistantId = makeId()
        acc.assistantContent = ''
        acc.currentToolCalls = []
        const newId = acc.assistantId
        setMessages((prev) => [
          ...prev,
          {
            id: newId,
            role: 'assistant' as const,
            content: '',
            toolCalls: [],
            timestamp: new Date(),
          },
        ])
        break
      }
      case 'text_delta':
        acc.assistantContent += (event.text as string) ?? ''
        setMessages((prev) =>
          prev.map((m) =>
            m.id === acc.assistantId ? { ...m, content: acc.assistantContent } : m,
          ),
        )
        break

      case 'tool_call_start':
        acc.currentToolCalls = [
          ...acc.currentToolCalls,
          {
            id: (event.id as string) ?? '',
            name: (event.name as string) ?? '',
            args: (event.args as Record<string, unknown>) ?? {},
          },
        ]
        setMessages((prev) =>
          prev.map((m) =>
            m.id === acc.assistantId
              ? { ...m, toolCalls: [...acc.currentToolCalls] }
              : m,
          ),
        )
        break

      case 'tool_result': {
        acc.currentToolCalls = acc.currentToolCalls.map((tc) =>
          tc.id === event.id
            ? { ...tc, output: event.output as string, isError: event.is_error as boolean }
            : tc,
        )
        setMessages((prev) =>
          prev.map((m) =>
            m.id === acc.assistantId
              ? { ...m, toolCalls: [...acc.currentToolCalls] }
              : m,
          ),
        )
        break
      }

      case 'suggestion_emitted': {
        const suggestion: SuggestionEvent = {
          type: 'suggestion_emitted',
          suggestion_id: (event.suggestion_id as string) ?? '',
          prompt: (event.prompt as string) ?? '',
          options: (event.options as Array<Record<string, unknown>>)?.map((o) => ({
            label: (o.label as string) ?? '',
            description: (o.description as string | null) ?? null,
            recommended: (o.recommended as boolean) ?? false,
          })) ?? [],
        }
        setMessages((prev) =>
          prev.map((m) =>
            m.id === acc.assistantId ? { ...m, suggestions: suggestion } : m,
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
            content: `Error: ${(event.code as string) ?? 'UNKNOWN'} - ${(event.message as string) ?? 'Unknown error'}`,
            timestamp: new Date(),
          },
        ])
        setIsStreaming(false)
        break
    }
  }, [])

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
      accRef.current = freshAccumulator()

      abortRef.current = streamTurn(sessionId, text, projectId, {
        onEvent: feedEvent,
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
    [sessionId, projectId, isStreaming, feedEvent],
  )

  /**
   * Begin an externally-driven turn (e.g. learning.create_project's
   * priming turn). Resets accumulator and sets isStreaming. Caller is
   * responsible for piping events through ``feedEvent`` and calling
   * ``finishExternalTurn`` when the upstream stream ends.
   */
  const beginExternalTurn = useCallback(() => {
    accRef.current = freshAccumulator()
    setIsStreaming(true)
  }, [])

  const finishExternalTurn = useCallback(() => {
    setIsStreaming(false)
  }, [])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
    accRef.current = freshAccumulator()
  }, [])

  return {
    messages,
    isStreaming,
    sendMessage,
    stopStreaming,
    clearMessages,
    feedEvent,
    beginExternalTurn,
    finishExternalTurn,
  }
}

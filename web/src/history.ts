import type { ChatMessage, MessageEnvelope, ToolCallInfo } from './types'

/**
 * Translate a sequence of persisted LLM-native envelopes into the UI's
 * ChatMessage view, matching the shape that the live SSE accumulator
 * (``feedEvent`` in ``useChat``) produces.
 *
 * Why this exists
 * ---------------
 * The backend persists messages.jsonl in Anthropic API protocol form:
 * each ``tool_use`` splits the assistant's reply into a new envelope, and
 * each tool's response is a ``role: user`` envelope holding only a
 * ``tool_result`` block. Rendering those envelopes directly produces
 * blank user bubbles and orphan assistant bubbles wedged between tool
 * calls — visually inconsistent with the live stream, where everything
 * within one user-driven turn collapses into a single assistant bubble
 * with its tool calls attached.
 *
 * This function bridges the two: it walks the envelope sequence and
 * emits ChatMessages that look exactly like what ``feedEvent`` would
 * have produced if the same turn had streamed in live.
 *
 * Translation rules
 * -----------------
 * - Skip envelopes whose ``metadata.synthetic === true`` (priming
 *   prompts, memory reminders, nag reminders — injected into the LLM
 *   session but never part of the visible chat).
 * - Skip envelopes whose role is neither ``user`` nor ``assistant``.
 * - For a ``user`` envelope:
 *     - text blocks → push a new user bubble (a real user message;
 *       this also marks a turn boundary).
 *     - tool_result blocks → attach output to the matching tool call
 *       on the current assistant bubble (matched by ``tool_use_id``).
 * - For an ``assistant`` envelope:
 *     - if the last emitted bubble is also assistant → continue it
 *       (this is the "post-tool_result" continuation of the same turn).
 *     - else → open a new assistant bubble.
 *     - text blocks → append to bubble's content (joined with no
 *       separator, mirroring streaming text_delta accumulation).
 *     - tool_use blocks → push a ToolCallInfo onto bubble.toolCalls,
 *       initially without output (output arrives via the next
 *       tool_result).
 *
 * The function is pure: same input → same output, no side effects, no
 * dependencies on React/DOM. Unit-testable in isolation once a test
 * runner is wired up.
 */
export function envelopesToMessages(
  envelopes: MessageEnvelope[],
  sessionId: string,
): ChatMessage[] {
  const messages: ChatMessage[] = []

  // Find the open assistant bubble (tail), if any. Used to attach
  // tool_result blocks and to decide whether to continue or open a new
  // bubble for the next assistant envelope.
  const tailAssistant = (): ChatMessage | null => {
    const last = messages[messages.length - 1]
    return last && last.role === 'assistant' ? last : null
  }

  const newId = (): string => `hist-${sessionId}-${messages.length}`

  for (const env of envelopes) {
    if (env.role !== 'user' && env.role !== 'assistant') continue
    if (env.metadata?.synthetic === true) continue

    if (env.role === 'user') {
      const userText = env.content
        .filter((b) => b.type === 'text')
        .map((b) => (b.text as string) ?? '')
        .join('')

      const toolResults = env.content.filter((b) => b.type === 'tool_result')
      for (const tr of toolResults) {
        const tail = tailAssistant()
        if (!tail || !tail.toolCalls) continue
        const targetId = (tr.tool_use_id as string) ?? ''
        const output = (tr.output as string) ?? ''
        const isError = (tr.is_error as boolean) ?? false
        tail.toolCalls = tail.toolCalls.map((tc) =>
          tc.id === targetId ? { ...tc, output, isError } : tc,
        )
      }

      if (userText.trim().length > 0) {
        messages.push({
          id: newId(),
          role: 'user',
          content: userText,
          timestamp: new Date(env.created_at),
        })
      }
      continue
    }

    // role === 'assistant'
    let bubble = tailAssistant()
    if (!bubble) {
      bubble = {
        id: newId(),
        role: 'assistant',
        content: '',
        toolCalls: [],
        timestamp: new Date(env.created_at),
      }
      messages.push(bubble)
    }

    for (const block of env.content) {
      if (block.type === 'text') {
        bubble.content += (block.text as string) ?? ''
      } else if (block.type === 'tool_use') {
        const tc: ToolCallInfo = {
          id: (block.id as string) ?? '',
          name: (block.name as string) ?? '',
          args: (block.input as Record<string, unknown>) ?? {},
        }
        bubble.toolCalls = [...(bubble.toolCalls ?? []), tc]
      }
      // other block types (e.g. thinking) are ignored for the UI.
    }
  }

  // Drop trailing empty assistant bubbles (turn ended on tool_use with
  // no follow-up text — should never happen in a well-formed
  // conversation, but guards against partial writes).
  while (
    messages.length > 0 &&
    messages[messages.length - 1].role === 'assistant' &&
    messages[messages.length - 1].content.trim().length === 0 &&
    (messages[messages.length - 1].toolCalls?.length ?? 0) === 0
  ) {
    messages.pop()
  }

  return messages
}

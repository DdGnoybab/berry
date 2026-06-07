import { useEffect, useRef, useState } from 'react'
import { streamCreateLearningProject, streamPlanPreview } from '../api'
import { BerryLoading } from './BerryLoading'
import type { PlanResult, Project, Session } from '../types'

type Step = 'input' | 'previewing' | 'review' | 'committing'

type Goal = 'interview' | 'deep' | 'easy'

interface Props {
  onClose: () => void
  /**
   * Called the instant backend confirms the project is committed
   * (DB row + workspace files written, first session created).
   * Modal closes immediately; the LLM's priming turn keeps streaming
   * via ``onStreamEvent`` into the chat view that's now mounted with
   * the new session_id.
   */
  onCreated: (project: Project, session: Session) => void
  /** Forward each backend SSE event to App.useChat so the chat view
   *  renders the priming turn live. */
  onStreamEvent: (event: Record<string, unknown>) => void
  /** Called when the SSE stream ends (success or failure). */
  onStreamDone: () => void
}

export function NewProjectModal({ onClose, onCreated, onStreamEvent, onStreamDone }: Props) {
  const [step, setStep] = useState<Step>('input')
  const [topic, setTopic] = useState('')
  const [goal, setGoal] = useState<Goal>('interview')
  const [progressLog, setProgressLog] = useState<string[]>([])
  const [plan, setPlan] = useState<PlanResult | null>(null)
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState<string | null>(null)
  const previewAbortRef = useRef<AbortController | null>(null)
  const createAbortRef = useRef<AbortController | null>(null)

  // Only abort preview stream on unmount. The create stream must survive
  // modal close — priming-turn events flow via onStreamEvent → feedEvent.
  useEffect(() => {
    return () => previewAbortRef.current?.abort()
  }, [])

  function startPreview(prevPlan: PlanResult | null, fb: string | null) {
    if (!topic.trim()) return
    setStep('previewing')
    setProgressLog([])
    setError(null)
    // Feedback has been consumed by this preview request; clear the
    // textarea so the user isn't re-submitting stale text on the next
    // "重新生成" click. Any new adjustment must be a freshly typed message.
    if (fb) {
      setFeedback('')
    }
    previewAbortRef.current?.abort()
    previewAbortRef.current = streamPlanPreview(
      {
        topic: topic.trim(),
        goal,
        feedback: fb,
        previous_plan: prevPlan,
      },
      {
        onProgress: (label) =>
          setProgressLog((prev) => {
            if (prev.length > 0 && prev[prev.length - 1] === label) {
              return prev
            }
            return [...prev, label]
          }),
        onPlan: (p) => {
          setPlan(p)
          setStep('review')
        },
        onError: (msg) => {
          setError(msg)
          setStep(prevPlan ? 'review' : 'input')
        },
      },
    )
  }

  function commit() {
    if (!plan) return
    setStep('committing')
    setError(null)
    previewAbortRef.current?.abort()
    createAbortRef.current = streamCreateLearningProject(topic.trim(), goal, plan, {
      onCreated: (result) => {
        onCreated(result.project, result.session)
      },
      onEvent: (ev) => {
        onStreamEvent(ev)
      },
      onError: (msg) => {
        setError(msg)
        setStep('review')
      },
      onDone: () => {
        onStreamDone()
      },
    })
  }

  // Step → header chip data
  const stepInfo = (() => {
    if (step === 'review') return { num: '02', tag: 'REVIEW', subtitle: 'CHECK PLAN' }
    if (step === 'committing') return { num: '03', tag: 'COMMIT', subtitle: 'INITIALIZING' }
    return { num: '01', tag: 'INPUT', subtitle: 'NEW TOPIC' }
  })()

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-header modal-header--zen">
          <span className="modal-header__bar" aria-hidden="true" />
          <div className="modal-header__main">
            <div className="modal-header__top">
              <span className="modal-header__num">#{stepInfo.num}</span>
              <span className="modal-header__dot" aria-hidden="true">●</span>
              <span className="modal-header__title">{stepInfo.subtitle}</span>
            </div>
            <div className="modal-header__steps">
              <span
                className={`modal-step ${step === 'input' ? 'modal-step--active' : 'modal-step--done'}`}
              >
                <span className="modal-step__idx">01</span>
                <span className="modal-step__label">INPUT</span>
              </span>
              <span className="modal-step__sep" aria-hidden="true">›</span>
              <span
                className={`modal-step ${step === 'review' || step === 'previewing' ? 'modal-step--active' : step === 'committing' ? 'modal-step--done' : ''}`}
              >
                <span className="modal-step__idx">02</span>
                <span className="modal-step__label">PLAN</span>
              </span>
              <span className="modal-step__sep" aria-hidden="true">›</span>
              <span
                className={`modal-step ${step === 'committing' ? 'modal-step--active' : ''}`}
              >
                <span className="modal-step__idx">03</span>
                <span className="modal-step__label">COMMIT</span>
              </span>
            </div>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        {error && <div className="modal-error">⚠ {error}</div>}

        {step === 'input' && (
          <div className="modal-body">
            <label className="modal-label">学的什么?</label>
            <input
              className="modal-input"
              type="text"
              placeholder="Redis / LangGraph / DDD …"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              autoFocus
            />

            <label className="modal-label">目标?</label>
            <div className="modal-goals">
              <GoalRow
                value="interview"
                current={goal}
                onChange={setGoal}
                title="面试突击"
                hint="按高频考点学,不抠源码"
              />
              <GoalRow
                value="deep"
                current={goal}
                onChange={setGoal}
                title="深入掌握"
                hint="源码级 + 设计取舍 + 横评"
              />
              <GoalRow
                value="easy"
                current={goal}
                onChange={setGoal}
                title="简单了解"
                hint="知道是什么、能干什么"
              />
            </div>

            <div className="modal-actions">
              <button className="btn-secondary" onClick={onClose}>取消</button>
              <button
                className="btn-primary"
                onClick={() => startPreview(null, null)}
                disabled={!topic.trim()}
              >
                生成计划 →
              </button>
            </div>
          </div>
        )}

        {step === 'previewing' && (
          <div className="modal-body modal-body--centered">
            <WobbleLoading topic={topic} step={progressLog.length} />
          </div>
        )}

        {step === 'review' && plan && (
          <div className="modal-body">
            <p className="modal-hint">
              📚 {topic} · {goalLabel(goal)} · {totalAtoms(plan)} atom · {plan.modules.length} 模块
            </p>
            <div className="modal-plan-tree">
              {plan.modules.map((m) => (
                <details key={m.id} className="modal-plan-module" open>
                  <summary>
                    <span className="modal-module-id">{m.id}</span>
                    <span className="modal-module-name">{m.name}</span>
                    <span className="modal-module-count">{m.atoms.length} atom</span>
                  </summary>
                  <ul>
                    {m.atoms.map((a) => (
                      <li key={a.id}>
                        <span className="modal-atom-id">{a.id}</span>
                        <span className="modal-atom-name">{a.name}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
            </div>

            <label className="modal-label">想调整?</label>
            <textarea
              className="modal-textarea"
              placeholder="例:我已经会 SDS 了,跳过这块。再加一个分布式锁的模块。"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={3}
            />

            <div className="modal-actions">
              <button
                className="btn-secondary"
                onClick={() => {
                  setStep('input')
                  setPlan(null)
                  setFeedback('')
                }}
              >
                ← 返回
              </button>
              <button
                className="btn-secondary"
                onClick={() => startPreview(plan, feedback.trim() || null)}
                disabled={!feedback.trim()}
              >
                重新生成
              </button>
              <button className="btn-primary" onClick={commit}>
                ✓ 开始学习
              </button>
            </div>
          </div>
        )}

        {step === 'committing' && (
          <div className="modal-body">
            <BerryLoading text="Creating workspace" />
          </div>
        )}
      </div>
    </div>
  )
}

function GoalRow({
  value,
  current,
  onChange,
  title,
  hint,
}: {
  value: Goal
  current: Goal
  onChange: (g: Goal) => void
  title: string
  hint: string
}) {
  return (
    <label className={`modal-goal-row ${current === value ? 'selected' : ''}`}>
      <input
        type="radio"
        name="goal"
        value={value}
        checked={current === value}
        onChange={() => onChange(value)}
      />
      <span className="modal-goal-title">{title}</span>
      <span className="modal-goal-hint">{hint}</span>
    </label>
  )
}

function goalLabel(g: Goal): string {
  return g === 'interview' ? '面试突击' : g === 'deep' ? '深入掌握' : '简单了解'
}

function totalAtoms(plan: PlanResult): number {
  return plan.modules.reduce((s, m) => s + m.atoms.length, 0)
}

/**
 * Cute wobbly LOADING text — replaces the "⏳ web_search × 6" log spam.
 *
 * Each letter wobbles with a slight rotation/translation; the gerund
 * subline ("Searching for redis...") cycles through 4 phrases driven by
 * the backend's tool-call count (so it still feels alive but isn't
 * spammy 1-line-per-event).
 */
function WobbleLoading({ topic, step }: { topic: string; step: number }) {
  const phrases = [
    'Searching the web...',
    'Reading sources...',
    'Cross-referencing...',
    'Drafting your plan...',
  ]
  const phrase = phrases[Math.min(step, phrases.length - 1)]

  return (
    <div className="wobble-loading">
      <div className="wobble-loading__letters" aria-label="loading">
        {'LOADING'.split('').map((ch, i) => (
          <span key={i} className="wobble-loading__letter" style={{ animationDelay: `${i * 0.08}s` }}>
            {ch}
          </span>
        ))}
        <span className="wobble-loading__dots">
          <span style={{ animationDelay: '0s' }}>.</span>
          <span style={{ animationDelay: '0.2s' }}>.</span>
          <span style={{ animationDelay: '0.4s' }}>.</span>
        </span>
      </div>
      <div className="wobble-loading__topic">
        TOPIC <span className="wobble-loading__topic-name">「{topic}」</span>
      </div>
      <div className="wobble-loading__phrase" key={phrase}>
        {phrase}
      </div>
    </div>
  )
}

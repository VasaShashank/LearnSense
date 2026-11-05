import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiClient } from '../api/client'

type ResumeState = Awaited<ReturnType<typeof ApiClient.resumeLearner>>

export interface AuthenticatedEntryResult {
  learnerId: string
  resume: ResumeState
}

/**
 * Pure orchestration helper so the init -> resume sequence can be tested without
 * rendering React or mocking browser-only APIs.
 */
export async function initializeAndResumeLearner(
  initialize: () => Promise<{ learner_id: string }>,
  resume: (learnerId: string) => Promise<ResumeState>,
): Promise<AuthenticatedEntryResult> {
  const initialized = await initialize()
  const learnerId = initialized?.learner_id
  if (typeof learnerId !== 'string' || learnerId.trim() === '') {
    throw new Error('Initialization did not return a learner ID.')
  }
  // Resume with the backend-issued canonical ID, never a client-derived one.
  const resumed = await resume(learnerId)
  if (resumed?.learner_id !== learnerId) {
    throw new Error('Resume response did not match the initialized learner.')
  }
  return { learnerId, resume: resumed }
}

/**
 * Map any failure to a fixed, user-safe message. Raw error text (which can include
 * the backend URL, transport reasons or server internals) is never displayed.
 */
export function userMessageFor(error: unknown): string {
  const status = typeof error === 'object' && error !== null && 'status' in error
    ? Number((error as { status: unknown }).status)
    : NaN
  const code = typeof error === 'object' && error !== null && 'code' in error
    ? String((error as { code: unknown }).code)
    : ''
  if (status === 401) return 'Your session is no longer valid. Please sign out and sign in again.'
  if (status === 403 || status === 404) return 'This account does not have access to a learner workspace.'
  if (status === 409) return 'Your learner record needs attention. Please contact support.'
  if (code === 'REQUEST_TIMEOUT' || code === 'BACKEND_UNREACHABLE' || status === 0 || status >= 500) {
    return 'LearnSense is temporarily unreachable. Check your connection and try again.'
  }
  return 'We could not load your learner workspace. Please try again.'
}

const ENTRY_STATE_GUIDANCE: Record<string, string> = {
  SOURCE_SELECTION: 'Next step: add a learning source to begin.',
  NEEDS_CALIBRATION: 'Next step: complete the self-assessment for your subject.',
  VERIFICATION_IN_PROGRESS: 'Your verification quiz is in progress and can be resumed.',
  VERIFICATION_ERROR: 'Quiz generation failed earlier; it can be retried.',
  VERIFICATION_COMPLETE: 'Your onboarding is complete.',
}

interface AuthenticatedLearnerEntryProps {
  userId: string
  onSignOut: () => Promise<unknown> | void
  signingOut: boolean
}

type Phase = 'initializing' | 'ready' | 'error'

interface EntryState {
  phase: Phase
  learnerId: string | null
  resume: ResumeState | null
  error: string | null
}

export function AuthenticatedLearnerEntry({
  userId,
  onSignOut,
  signingOut,
}: AuthenticatedLearnerEntryProps) {
  const [state, setState] = useState<EntryState>({
    phase: 'initializing',
    learnerId: null,
    resume: null,
    error: null,
  })
  const runIdRef = useRef(0)
  const mountedRef = useRef(true)

  const run = useCallback(async () => {
    const runId = ++runIdRef.current
    setState({ phase: 'initializing', learnerId: null, resume: null, error: null })

    try {
      const result = await initializeAndResumeLearner(
        () => ApiClient.initializeCurrentLearner(),
        (learnerId) => ApiClient.resumeLearner(learnerId),
      )
      if (!mountedRef.current || runIdRef.current !== runId) return
      setState({ phase: 'ready', learnerId: result.learnerId, resume: result.resume, error: null })
    } catch (error) {
      if (!mountedRef.current || runIdRef.current !== runId) return
      setState({
        phase: 'error',
        learnerId: null,
        resume: null,
        error: userMessageFor(error),
      })
    }
  }, [userId]) // new identity => new callback => effect re-runs and supersedes in-flight work

  useEffect(() => {
    mountedRef.current = true
    void run()
    return () => {
      mountedRef.current = false
      runIdRef.current += 1
    }
  }, [userId, run])

  if (state.phase === 'initializing') {
    return (
      <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5" aria-live="polite">
        <section className="w-full max-w-xl rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-4 text-center">
          <h1 className="font-display text-xl font-semibold text-white">Preparing your learner workspace</h1>
          <p className="text-sm text-universe-slate">Initializing and resuming your trusted server-side learner record…</p>
          <button
            type="button"
            onClick={() => void onSignOut()}
            disabled={signingOut}
            className="rounded-xl border border-white/[0.12] bg-space-800 px-4 py-2 text-sm font-semibold text-white hover:border-cyan-400/40 disabled:opacity-60"
          >
            {signingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </section>
      </main>
    )
  }

  if (state.phase === 'error') {
    return (
      <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
        <section className="w-full max-w-xl rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-5">
          <h1 className="font-display text-xl font-semibold text-white">Learner workspace unavailable</h1>
          <p role="alert" className="rounded-xl border border-red-400/30 bg-red-500/[0.08] px-4 py-3 text-sm leading-5 text-red-200">
            {state.error ?? 'Unable to initialize your learner workspace.'}
          </p>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => void run()}
              disabled={signingOut}
              className="flex-1 rounded-xl bg-cyan-500 px-4 py-3 text-sm font-bold text-space-950 hover:bg-cyan-400 disabled:opacity-60"
            >
              Retry
            </button>
            <button
              type="button"
              onClick={() => void onSignOut()}
              disabled={signingOut}
              className="flex-1 rounded-xl border border-white/[0.12] bg-space-800 px-4 py-3 text-sm font-semibold text-white hover:border-cyan-400/40 disabled:opacity-60"
            >
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        </section>
      </main>
    )
  }

  const resume = state.resume!
  return (
    <main className="min-h-screen universe-canvas text-universe-text p-5">
      <section className="mx-auto w-full max-w-3xl rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="font-display text-2xl font-semibold text-white">Authenticated learner workspace</h1>
            <p className="mt-1 text-sm text-universe-slate">Your identity and progress are resolved from the server.</p>
          </div>
          <button
            type="button"
            onClick={() => void onSignOut()}
            disabled={signingOut}
            className="rounded-xl border border-white/[0.12] bg-space-800 px-4 py-3 text-sm font-semibold text-white hover:border-cyan-400/40 disabled:opacity-60"
          >
            {signingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>

        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div className="rounded-2xl bg-space-950/60 border border-white/[0.08] p-4">
            <dt className="text-universe-slate">Learner ID</dt>
            <dd className="mt-1 font-mono text-white break-all">{state.learnerId}</dd>
          </div>
          <div className="rounded-2xl bg-space-950/60 border border-white/[0.08] p-4">
            <dt className="text-universe-slate">Entry state</dt>
            <dd className="mt-1 font-mono text-white">{resume.entry_state}</dd>
          </div>
          <div className="rounded-2xl bg-space-950/60 border border-white/[0.08] p-4">
            <dt className="text-universe-slate">Subject</dt>
            <dd className="mt-1 font-mono text-white">{resume.subject_id ?? 'None selected'}</dd>
          </div>
          <div className="rounded-2xl bg-space-950/60 border border-white/[0.08] p-4">
            <dt className="text-universe-slate">Onboarded</dt>
            <dd className="mt-1 font-mono text-white">{resume.is_onboarded ? 'Yes' : 'No'}</dd>
          </div>
        </dl>

        <p className="text-sm leading-6 text-universe-text" data-testid="entry-guidance">
          {ENTRY_STATE_GUIDANCE[resume.entry_state] ?? 'Your learner workspace is ready.'}
        </p>

        <p className="text-xs leading-5 text-universe-slate/80">
          This authenticated entry path never uses demo persona IDs. Learning modules will connect to this canonical learner ID in subsequent integration work.
        </p>
      </section>
    </main>
  )
}

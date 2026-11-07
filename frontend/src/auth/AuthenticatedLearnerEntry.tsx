import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
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

export interface AuthenticatedLearnerEntryProps {
  userId: string
  userEmail?: string | null
  onSignOut: () => Promise<unknown> | void
  signingOut: boolean
  onLaunchWorkspace?: () => void
  children?: (data: { learnerId: string; resume: ResumeState }) => ReactNode
}

type Phase = 'initializing' | 'ready' | 'error'

interface EntryState {
  phase: Phase
  learnerId: string | null
  resume: ResumeState | null
  error: string | null
}

interface UserProfileData {
  displayName: string
  email: string
  memberships: Array<{
    membership_id: string
    org_id: string
    org_name: string
    role: string
    is_active: boolean
  }>
}

export function AuthenticatedLearnerEntry({
  userId,
  userEmail,
  onSignOut,
  signingOut,
  onLaunchWorkspace,
  children,
}: AuthenticatedLearnerEntryProps) {
  const [state, setState] = useState<EntryState>({
    phase: 'initializing',
    learnerId: null,
    resume: null,
    error: null,
  })
  const [profile, setProfile] = useState<UserProfileData>({
    displayName: '',
    email: userEmail || '',
    memberships: [],
  })
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [inviteToken, setInviteToken] = useState('')
  const [inviteFeedback, setInviteFeedback] = useState<string | null>(null)
  const [isSavingName, setIsSavingName] = useState(false)

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

      // Fetch user profile asynchronously if supported
      if (typeof (ApiClient as any).getCurrentUser === 'function') {
        try {
          (ApiClient as any).getCurrentUser().then((me: any) => {
            if (!mountedRef.current || !me) return
            setProfile({
              displayName: me.display_name || '',
              email: me.email || userEmail || '',
              memberships: me.memberships || [],
            })
            setNameInput(me.display_name || '')
          }).catch(() => {})
        } catch {
          // ignore client mock absence
        }
      }
    } catch (error) {
      if (!mountedRef.current || runIdRef.current !== runId) return
      setState({
        phase: 'error',
        learnerId: null,
        resume: null,
        error: userMessageFor(error),
      })
    }
  }, [userId, userEmail])

  useEffect(() => {
    mountedRef.current = true
    void run()
    return () => {
      mountedRef.current = false
      runIdRef.current += 1
    }
  }, [userId, run])

  const handleSaveDisplayName = async () => {
    setIsSavingName(true)
    try {
      await ApiClient.updateProfile({ display_name: nameInput.trim() })
      setProfile((prev) => ({ ...prev, displayName: nameInput.trim() }))
      setEditingName(false)
    } catch {
      // Ignored
    } finally {
      setIsSavingName(false)
    }
  }

  const handleAcceptInvite = async () => {
    if (!inviteToken.trim()) return
    setInviteFeedback(null)
    try {
      await ApiClient.acceptInvitation(inviteToken.trim())
      setInviteFeedback('Invitation accepted successfully! Refreshing memberships...')
      setInviteToken('')
      const me = await ApiClient.getCurrentUser()
      if (me) {
        setProfile((prev) => ({ ...prev, memberships: me.memberships || [] }))
      }
    } catch (err: any) {
      setInviteFeedback(err.message || 'Failed to accept invitation. Verify the token.')
    }
  }

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

  if (children) {
    return <>{children({ learnerId: state.learnerId!, resume })}</>
  }

  return (
    <main className="min-h-screen universe-canvas text-universe-text p-5">
      <section className="mx-auto w-full max-w-3xl rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="font-display text-2xl font-semibold text-white">Authenticated learner workspace</h1>
            <p className="mt-1 text-sm text-universe-slate">Your identity and progress are resolved from the server.</p>
          </div>
          <div className="flex items-center gap-3">
            {onLaunchWorkspace && (
              <span
                role="button"
                tabIndex={0}
                onClick={onLaunchWorkspace}
                className="rounded-xl bg-cyan-500 px-4 py-2.5 text-sm font-bold text-space-950 hover:bg-cyan-400 transition-colors shadow-lg shadow-cyan-500/20 cursor-pointer"
              >
                Launch Workspace →
              </span>
            )}
            <button
              type="button"
              onClick={() => void onSignOut()}
              disabled={signingOut}
              className="rounded-xl border border-white/[0.12] bg-space-800 px-4 py-2.5 text-sm font-semibold text-white hover:border-cyan-400/40 disabled:opacity-60"
            >
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        </div>

        {/* Profile Card */}
        <div className="rounded-2xl bg-space-950/60 border border-white/[0.08] p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-mono text-universe-slate">Account Profile</span>
            {!editingName ? (
              <span
                role="button"
                tabIndex={0}
                onClick={() => setEditingName(true)}
                className="text-xs text-cyan-400 hover:text-cyan-300 cursor-pointer"
              >
                Edit Name
              </span>
            ) : (
              <div className="flex gap-2">
                <span
                  role="button"
                  tabIndex={0}
                  onClick={handleSaveDisplayName}
                  className="text-xs font-semibold text-cyan-400 hover:text-cyan-300 cursor-pointer"
                >
                  {isSavingName ? 'Saving…' : 'Save'}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={() => setEditingName(false)}
                  className="text-xs text-universe-slate hover:text-white cursor-pointer"
                >
                  Cancel
                </span>
              </div>
            )}
          </div>
          <div className="grid gap-2 sm:grid-cols-2 text-sm">
            <div>
              <span className="text-universe-slate text-xs">Display Name:</span>
              {!editingName ? (
                <div className="font-semibold text-white">{profile.displayName || 'Not configured'}</div>
              ) : (
                <input
                  type="text"
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  placeholder="Your full name"
                  className="mt-1 w-full rounded-lg border border-white/[0.12] bg-space-900 px-3 py-1.5 text-sm text-white outline-none focus:border-cyan-400"
                />
              )}
            </div>
            <div>
              <span className="text-universe-slate text-xs">Email:</span>
              <div className="font-mono text-white">{profile.email || userEmail || 'Verified Supabase User'}</div>
            </div>
          </div>
        </div>

        {/* Learner Data Details */}
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

        {/* Organization Memberships */}
        <div className="rounded-2xl bg-space-950/60 border border-white/[0.08] p-5 space-y-3">
          <span className="text-xs uppercase tracking-wider font-mono text-universe-slate">Organization Memberships</span>
          {profile.memberships.length === 0 ? (
            <p className="text-xs text-universe-slate">No institutional memberships active. Operating as an individual learner.</p>
          ) : (
            <div className="space-y-2">
              {profile.memberships.map((m) => (
                <div key={m.membership_id} className="flex items-center justify-between rounded-xl bg-space-900 border border-white/[0.06] p-3 text-xs">
                  <span className="font-semibold text-white">{m.org_name}</span>
                  <span className="font-mono font-bold px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-400/20">{m.role}</span>
                </div>
              ))}
            </div>
          )}

          {/* Accept Invitation */}
          <div className="pt-2 border-t border-white/[0.06] space-y-2">
            <label className="block text-xs text-universe-slate">Have an invitation code from your school or teacher?</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={inviteToken}
                onChange={(e) => setInviteToken(e.target.value)}
                placeholder="Enter invite token..."
                className="flex-1 rounded-xl border border-white/[0.12] bg-space-900 px-3 py-2 text-xs text-white outline-none focus:border-cyan-400"
              />
              <span
                role="button"
                tabIndex={0}
                onClick={handleAcceptInvite}
                className="rounded-xl border border-cyan-400/30 bg-cyan-500/10 hover:bg-cyan-500/20 px-3 py-2 text-xs font-semibold text-cyan-300 cursor-pointer flex items-center"
              >
                Accept Invite
              </span>
            </div>
            {inviteFeedback && <p className="text-xs text-cyan-300 mt-1">{inviteFeedback}</p>}
          </div>
        </div>

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

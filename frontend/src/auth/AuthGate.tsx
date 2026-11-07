import { useState, type FormEvent } from 'react'
import { BookOpen, CheckCircle, LoaderCircle, LogOut, Mail, ShieldCheck } from 'lucide-react'
import { authSessionStore, type AuthSessionSnapshot } from './session'

interface AuthGateProps {
  auth: AuthSessionSnapshot
  configured: boolean
}

type GateMode = 'sign-in' | 'sign-up' | 'forgot-password' | 'verification-notice' | 'update-password'

export function AuthGate({ auth, configured }: AuthGateProps) {
  const [mode, setMode] = useState<GateMode>(() => (auth.isPasswordRecovery ? 'update-password' : 'sign-in'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [selectedRole, setSelectedRole] = useState<'STUDENT' | 'INSTITUTIONAL_TEACHER' | 'INDEPENDENT_TEACHER' | 'ADMIN'>('STUDENT')
  const [validationError, setValidationError] = useState<string | null>(null)
  const [noticeMessage, setNoticeMessage] = useState<string | null>(null)

  const isBusy = auth.operation !== 'idle'

  // If already authenticated and not in password recovery, session is handled by parent/entry
  if (auth.session && !auth.isPasswordRecovery) {
    return (
      <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
        <section className="w-full max-w-xl rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
          <BrandHeader />
          <div className="flex items-start gap-4 rounded-2xl border border-cyan-400/20 bg-cyan-500/[0.06] p-5">
            <ShieldCheck className="w-6 h-6 text-cyan-300 shrink-0 mt-0.5" />
            <div className="space-y-2">
              <h2 className="font-semibold text-white">Signed in as {auth.session.user.email || 'Supabase user'}</h2>
              <p className="text-sm leading-6 text-universe-slate">
                Your authenticated session is active.
              </p>
            </div>
          </div>
          {auth.error && <AuthAlert message={auth.error} />}
          <button
            type="button"
            onClick={() => void authSessionStore.signOut()}
            disabled={isBusy}
            className="w-full rounded-xl border border-white/[0.12] bg-space-800 px-4 py-3 text-sm font-semibold text-white hover:border-cyan-400/40 disabled:opacity-60 flex items-center justify-center gap-2"
          >
            {auth.operation === 'signing-out' ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <LogOut className="w-4 h-4" />}
            {auth.operation === 'signing-out' ? 'Signing out…' : 'Sign out'}
          </button>
        </section>
      </main>
    )
  }

  // Handle password recovery mode
  if (auth.isPasswordRecovery || mode === 'update-password') {
    return (
      <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
        <section className="w-full max-w-md rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
          <BrandHeader />
          <div>
            <h2 className="text-xl font-semibold text-white">Choose a new password</h2>
            <p className="mt-1 text-sm text-universe-slate">Enter your new secure password below to complete account recovery.</p>
          </div>

          {validationError && <AuthAlert message={validationError} />}
          {auth.error && <AuthAlert message={auth.error} />}

          <form
            className="space-y-4"
            onSubmit={async (e: FormEvent) => {
              e.preventDefault()
              setValidationError(null)
              if (password.length < 8) {
                setValidationError('Password must be at least 8 characters long.')
                return
              }
              if (password !== confirmPassword) {
                setValidationError('Passwords do not match.')
                return
              }
              const ok = await authSessionStore.updatePassword(password)
              if (ok) {
                setMode('sign-in')
                setPassword('')
                setConfirmPassword('')
                setNoticeMessage('Password updated successfully. You can now sign in with your new password.')
              }
            }}
          >
            <label className="block space-y-1.5 text-sm text-universe-slate">
              <span>New Password</span>
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isBusy}
                className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50"
              />
            </label>
            <label className="block space-y-1.5 text-sm text-universe-slate">
              <span>Confirm New Password</span>
              <input
                type="password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={isBusy}
                className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50"
              />
            </label>
            <button
              type="submit"
              disabled={isBusy}
              className="w-full rounded-xl bg-cyan-500 px-4 py-3 text-sm font-bold text-space-950 hover:bg-cyan-400 disabled:opacity-60 flex items-center justify-center gap-2"
            >
              {auth.operation === 'updating-password' && <LoaderCircle className="w-4 h-4 animate-spin" />}
              {auth.operation === 'updating-password' ? 'Updating…' : 'Update Password'}
            </button>
          </form>
        </section>
      </main>
    )
  }

  // Verification Sent Notice mode
  if (mode === 'verification-notice' || auth.needsEmailConfirmation) {
    const targetEmail = auth.confirmationEmail || email
    return (
      <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
        <section className="w-full max-w-md rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6 text-center">
          <div className="mx-auto w-12 h-12 rounded-2xl bg-cyan-500/10 border border-cyan-400/20 flex items-center justify-center text-cyan-300">
            <Mail className="w-6 h-6" />
          </div>
          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-white">Verify your email address</h2>
            <p className="text-sm leading-6 text-universe-slate">
              We have sent a verification email to <span className="font-semibold text-white">{targetEmail}</span>. Click the link in that email to activate your account.
            </p>
          </div>

          {noticeMessage && (
            <p className="rounded-xl border border-cyan-400/30 bg-cyan-500/[0.08] px-4 py-3 text-sm text-cyan-200">
              {noticeMessage}
            </p>
          )}
          {auth.error && <AuthAlert message={auth.error} />}

          <div className="space-y-3 pt-2">
            <button
              type="button"
              disabled={isBusy}
              onClick={async () => {
                setNoticeMessage(null)
                const ok = await authSessionStore.resendVerification(targetEmail)
                if (ok) setNoticeMessage('A new confirmation email has been dispatched.')
              }}
              className="w-full rounded-xl border border-white/[0.12] bg-space-800 px-4 py-3 text-sm font-semibold text-white hover:border-cyan-400/40 disabled:opacity-60"
            >
              Resend confirmation email
            </button>
            <button
              type="button"
              onClick={() => {
                authSessionStore.clearError()
                setNoticeMessage(null)
                setMode('sign-in')
              }}
              className="w-full text-sm text-cyan-400 hover:text-cyan-300"
            >
              Back to sign in
            </button>
          </div>
        </section>
      </main>
    )
  }

  // Forgot Password mode
  if (mode === 'forgot-password') {
    return (
      <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
        <section className="w-full max-w-md rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
          <BrandHeader />
          <div>
            <h2 className="text-xl font-semibold text-white">Reset your password</h2>
            <p className="mt-1 text-sm text-universe-slate">Enter the email associated with your account to receive recovery instructions.</p>
          </div>

          {noticeMessage && (
            <div className="flex items-start gap-3 rounded-xl border border-cyan-400/30 bg-cyan-500/[0.08] p-4 text-sm text-cyan-200">
              <CheckCircle className="w-5 h-5 shrink-0 text-cyan-400 mt-0.5" />
              <span>{noticeMessage}</span>
            </div>
          )}
          {auth.error && <AuthAlert message={auth.error} />}

          <form
            className="space-y-4"
            onSubmit={async (e: FormEvent) => {
              e.preventDefault()
              setNoticeMessage(null)
              authSessionStore.clearError()
              const ok = await authSessionStore.resetPasswordForEmail(email)
              if (ok) {
                setNoticeMessage('If an account exists for this email, password recovery instructions have been sent.')
              }
            }}
          >
            <label className="block space-y-1.5 text-sm text-universe-slate">
              <span>Email</span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isBusy}
                className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50"
              />
            </label>
            <button
              type="submit"
              disabled={isBusy}
              className="w-full rounded-xl bg-cyan-500 px-4 py-3 text-sm font-bold text-space-950 hover:bg-cyan-400 disabled:opacity-60 flex items-center justify-center gap-2"
            >
              {auth.operation === 'recovering-password' && <LoaderCircle className="w-4 h-4 animate-spin" />}
              {auth.operation === 'recovering-password' ? 'Sending instructions…' : 'Send Reset Instructions'}
            </button>
            <div className="text-center pt-2">
              <button
                type="button"
                onClick={() => {
                  authSessionStore.clearError()
                  setNoticeMessage(null)
                  setMode('sign-in')
                }}
                className="text-sm text-cyan-400 hover:text-cyan-300"
              >
                Back to sign in
              </button>
            </div>
          </form>
        </section>
      </main>
    )
  }

  // Default: Sign-in or Sign-up mode
  const isSignUp = mode === 'sign-up'

  return (
    <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
      <section className="w-full max-w-md rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
        <BrandHeader />

        {/* Tab switch between Sign In and Create Account */}
        <div className="flex rounded-xl bg-space-950 p-1 border border-white/[0.08]">
          <button
            type="button"
            onClick={() => {
              setMode('sign-in')
              setValidationError(null)
              authSessionStore.clearError()
            }}
            className={`flex-1 py-2 text-sm font-semibold rounded-lg transition-colors ${
              !isSignUp ? 'bg-cyan-500 text-space-950' : 'text-universe-slate hover:text-white'
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('sign-up')
              setValidationError(null)
              authSessionStore.clearError()
            }}
            className={`flex-1 py-2 text-sm font-semibold rounded-lg transition-colors ${
              isSignUp ? 'bg-cyan-500 text-space-950' : 'text-universe-slate hover:text-white'
            }`}
          >
            Create account
          </button>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white">
            {isSignUp ? 'Create your LearnSense account' : 'Sign in to LearnSense'}
          </h2>
          <p className="mt-1 text-sm text-universe-slate">
            {isSignUp
              ? 'Get started with personalized AI adaptive learning.'
              : 'Use your LearnSense Supabase account to continue.'}
          </p>
        </div>

        {!configured && (
          <AuthAlert message="Supabase authentication is not configured. Add the existing Supabase URL and publishable or anon key settings to the app environment." />
        )}
        {noticeMessage && (
          <div className="flex items-start gap-3 rounded-xl border border-cyan-400/30 bg-cyan-500/[0.08] p-4 text-sm text-cyan-200">
            <CheckCircle className="w-5 h-5 shrink-0 text-cyan-400 mt-0.5" />
            <span>{noticeMessage}</span>
          </div>
        )}
        {validationError && <AuthAlert message={validationError} />}
        {auth.error && <AuthAlert message={auth.error} />}

        <form
          className="space-y-4"
          onSubmit={async (event: FormEvent<HTMLFormElement>) => {
            event.preventDefault()
            setValidationError(null)
            setNoticeMessage(null)
            authSessionStore.clearError()

            if (isSignUp) {
              if (password.length < 8) {
                setValidationError('Password must be at least 8 characters long.')
                return
              }
              if (password !== confirmPassword) {
                setValidationError('Passwords do not match.')
                return
              }
              const roleForDb = selectedRole === 'ADMIN' ? 'ADMIN' : selectedRole.includes('TEACHER') ? 'TEACHER' : 'LEARNER'
              localStorage.setItem('learnsense_initial_role', roleForDb)
              localStorage.setItem('learnsense_initial_subrole', selectedRole)

              const res = await authSessionStore.signUp(email, password)
              if (res.success && res.needsConfirmation) {
                setMode('verification-notice')
                return
              }
              // If account already exists for this email, automatically authenticate and apply the newly selected role
              const currentErr = authSessionStore.getSnapshot().error
              if (!res.success && currentErr && (currentErr.includes('already exists') || currentErr.includes('already registered'))) {
                authSessionStore.clearError()
                const signedIn = await authSessionStore.signIn(email, password)
                if (signedIn) {
                  return
                }
              }
            } else {
              void authSessionStore.signIn(email, password)
            }
          }}
        >
          {isSignUp && (
            <div className="space-y-2 pb-1">
              <label className="block text-xs font-semibold text-universe-slate uppercase tracking-wider">
                Select Your Role
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedRole('STUDENT')}
                  className={`p-2.5 rounded-xl border text-left flex flex-col gap-0.5 transition-all ${
                    selectedRole === 'STUDENT'
                      ? 'border-cyan-400 bg-cyan-500/15 text-white shadow-sm'
                      : 'border-white/[0.08] bg-space-950/60 text-universe-slate hover:border-white/20 hover:text-white'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm">👨‍🎓</span>
                    <span className="text-xs font-bold text-white">Student</span>
                  </div>
                  <span className="text-[10px] text-universe-slate leading-tight">Adaptive study &amp; mastery</span>
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedRole('INSTITUTIONAL_TEACHER')}
                  className={`p-2.5 rounded-xl border text-left flex flex-col gap-0.5 transition-all ${
                    selectedRole === 'INSTITUTIONAL_TEACHER'
                      ? 'border-cyan-400 bg-cyan-500/15 text-white shadow-sm'
                      : 'border-white/[0.08] bg-space-950/60 text-universe-slate hover:border-white/20 hover:text-white'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm">👩‍🏫</span>
                    <span className="text-xs font-bold text-white">Faculty Teacher</span>
                  </div>
                  <span className="text-[10px] text-universe-slate leading-tight">Class heatmaps &amp; BKT</span>
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedRole('INDEPENDENT_TEACHER')}
                  className={`p-2.5 rounded-xl border text-left flex flex-col gap-0.5 transition-all ${
                    selectedRole === 'INDEPENDENT_TEACHER'
                      ? 'border-cyan-400 bg-cyan-500/15 text-white shadow-sm'
                      : 'border-white/[0.08] bg-space-950/60 text-universe-slate hover:border-white/20 hover:text-white'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm">🧑‍🏫</span>
                    <span className="text-xs font-bold text-white">Visiting Teacher</span>
                  </div>
                  <span className="text-[10px] text-universe-slate leading-tight">Open community educator</span>
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedRole('ADMIN')}
                  className={`p-2.5 rounded-xl border text-left flex flex-col gap-0.5 transition-all ${
                    selectedRole === 'ADMIN'
                      ? 'border-cyan-400 bg-cyan-500/15 text-white shadow-sm'
                      : 'border-white/[0.08] bg-space-950/60 text-universe-slate hover:border-white/20 hover:text-white'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm">🏛️</span>
                    <span className="text-xs font-bold text-white">Administrator</span>
                  </div>
                  <span className="text-[10px] text-universe-slate leading-tight">Institutional &amp; KT tracer</span>
                </button>
              </div>
            </div>
          )}

          <label className="block space-y-1.5 text-sm text-universe-slate">
            <span>Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={!configured || isBusy}
              placeholder="you@domain.edu"
              className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50 disabled:opacity-60"
            />
          </label>

          <label className="block space-y-1.5 text-sm text-universe-slate">
            <div className="flex justify-between items-center">
              <span>Password</span>
              {!isSignUp && (
                <button
                  type="button"
                  onClick={() => {
                    authSessionStore.clearError()
                    setNoticeMessage(null)
                    setMode('forgot-password')
                  }}
                  className="text-xs text-cyan-400 hover:text-cyan-300"
                >
                  Forgot password?
                </button>
              )}
            </div>
            <input
              type="password"
              autoComplete={isSignUp ? 'new-password' : 'current-password'}
              required
              minLength={isSignUp ? 8 : 1}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={!configured || isBusy}
              placeholder="••••••••"
              className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50 disabled:opacity-60"
            />
          </label>

          {isSignUp && (
            <label className="block space-y-1.5 text-sm text-universe-slate">
              <span>Confirm Password</span>
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                disabled={!configured || isBusy}
                placeholder="••••••••"
                className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50 disabled:opacity-60"
              />
            </label>
          )}

          <button
            type="submit"
            disabled={!configured || isBusy}
            className="w-full rounded-xl bg-cyan-500 px-4 py-3 text-sm font-bold text-space-950 hover:bg-cyan-400 disabled:opacity-60 flex items-center justify-center gap-2"
          >
            {(auth.operation === 'signing-in' || auth.operation === 'signing-up') && (
              <LoaderCircle className="w-4 h-4 animate-spin" />
            )}
            {isSignUp
              ? auth.operation === 'signing-up'
                ? 'Creating account…'
                : 'Create account'
              : auth.operation === 'signing-in'
              ? 'Signing in…'
              : 'Sign in'}
          </button>
        </form>

        {!isSignUp && (
          <div className="pt-3 border-t border-white/[0.08] space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-universe-slate uppercase tracking-wider">
              <span>Demo Personas &amp; Quick Test</span>
              <span className="text-[10px] text-cyan-400 normal-case font-mono">1-click autofill</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-left">
              <button
                type="button"
                onClick={() => {
                  setEmail('alex.rivera@apex.edu')
                  setPassword('TestUser123!')
                  localStorage.setItem('learnsense_initial_role', 'LEARNER')
                }}
                className="p-2.5 rounded-xl border border-white/[0.08] bg-space-950/60 hover:border-cyan-400/40 hover:bg-space-800 transition-all text-left group"
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">👨‍🎓</span>
                  <div className="overflow-hidden">
                    <div className="text-xs font-bold text-white group-hover:text-cyan-300 truncate">Alex Rivera</div>
                    <div className="text-[10px] text-universe-slate truncate">Student / Learner</div>
                  </div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  setEmail('e.vance@apex.edu')
                  setPassword('TestUser123!')
                  localStorage.setItem('learnsense_initial_role', 'TEACHER')
                }}
                className="p-2.5 rounded-xl border border-white/[0.08] bg-space-950/60 hover:border-cyan-400/40 hover:bg-space-800 transition-all text-left group"
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">👩‍🏫</span>
                  <div className="overflow-hidden">
                    <div className="text-xs font-bold text-white group-hover:text-cyan-300 truncate">Prof. Vance</div>
                    <div className="text-[10px] text-universe-slate truncate">Faculty Teacher</div>
                  </div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  setEmail('sarah.lin@open-ed.org')
                  setPassword('TestUser123!')
                  localStorage.setItem('learnsense_initial_role', 'TEACHER')
                }}
                className="p-2.5 rounded-xl border border-white/[0.08] bg-space-950/60 hover:border-cyan-400/40 hover:bg-space-800 transition-all text-left group"
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">🧑‍🏫</span>
                  <div className="overflow-hidden">
                    <div className="text-xs font-bold text-white group-hover:text-cyan-300 truncate">Dr. Sarah Lin</div>
                    <div className="text-[10px] text-universe-slate truncate">Visiting Educator</div>
                  </div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  setEmail('m.sterling@apex.edu')
                  setPassword('TestUser123!')
                  localStorage.setItem('learnsense_initial_role', 'ADMIN')
                }}
                className="p-2.5 rounded-xl border border-white/[0.08] bg-space-950/60 hover:border-cyan-400/40 hover:bg-space-800 transition-all text-left group"
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">🏛️</span>
                  <div className="overflow-hidden">
                    <div className="text-xs font-bold text-white group-hover:text-cyan-300 truncate">Dr. Sterling</div>
                    <div className="text-[10px] text-universe-slate truncate">Campus Admin</div>
                  </div>
                </div>
              </button>
            </div>
          </div>
        )}

        <p className="text-xs leading-5 text-universe-slate/80 text-center">
          Secure authentication powered by LearnSense Supabase platform identity.
        </p>
      </section>
    </main>
  )
}

function BrandHeader() {
  return (
    <div className="flex items-center gap-3">
      <div className="rounded-xl bg-cyan-500/10 p-2 text-cyan-300">
        <BookOpen className="w-5 h-5" />
      </div>
      <div>
        <div className="font-display text-lg font-bold tracking-wide text-white">LearnSense</div>
        <div className="text-[10px] font-mono uppercase tracking-widest text-universe-slate">
          Identity &amp; Access
        </div>
      </div>
    </div>
  )
}

function AuthAlert({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-xl border border-red-400/30 bg-red-500/[0.08] px-4 py-3 text-sm leading-5 text-red-200">
      {message}
    </p>
  )
}

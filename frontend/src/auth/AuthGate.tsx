import { useState, type FormEvent } from 'react'
import { BookOpen, LoaderCircle, LogOut, ShieldCheck } from 'lucide-react'
import { authSessionStore, type AuthSessionSnapshot } from './session'

interface AuthGateProps {
  auth: AuthSessionSnapshot
  configured: boolean
}

export function AuthGate({ auth, configured }: AuthGateProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const isBusy = auth.operation !== 'idle'

  if (auth.session) {
    return (
      <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
        <section className="w-full max-w-xl rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
          <BrandHeader />
          <div className="flex items-start gap-4 rounded-2xl border border-cyan-400/20 bg-cyan-500/[0.06] p-5">
            <ShieldCheck className="w-6 h-6 text-cyan-300 shrink-0 mt-0.5" />
            <div className="space-y-2">
              <h2 className="font-semibold text-white">Signed in as {auth.session.user.email || 'Supabase user'}</h2>
              <p className="text-sm leading-6 text-universe-slate">
                Your Supabase session is active. Learner features are unavailable until the backend can map this account to a trusted learner record. No demo persona will be used for this account.
              </p>
            </div>
          </div>
          {auth.error && <AuthMessage>{auth.error}</AuthMessage>}
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

  return (
    <main className="min-h-screen universe-canvas text-universe-text flex items-center justify-center p-5">
      <section className="w-full max-w-md rounded-3xl bg-space-900 border border-white/[0.12] p-8 shadow-2xl space-y-6">
        <BrandHeader />
        <div>
          <h2 className="text-xl font-semibold text-white">Sign in</h2>
          <p className="mt-1 text-sm text-universe-slate">Use your LearnSense Supabase account to continue.</p>
        </div>

        {!configured && (
          <AuthMessage>Supabase authentication is not configured. Add the existing Supabase URL and publishable or anon key settings to the app environment.</AuthMessage>
        )}
        {auth.error && <AuthMessage>{auth.error}</AuthMessage>}

        <form
          className="space-y-4"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault()
            void authSessionStore.signIn(email.trim(), password)
          }}
        >
          <label className="block space-y-1.5 text-sm text-universe-slate">
            <span>Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={!configured || isBusy}
              className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50 disabled:opacity-60"
            />
          </label>
          <label className="block space-y-1.5 text-sm text-universe-slate">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={!configured || isBusy}
              className="w-full rounded-xl border border-white/[0.12] bg-space-950 px-4 py-3 text-white outline-none focus:border-cyan-400/50 disabled:opacity-60"
            />
          </label>
          <button
            type="submit"
            disabled={!configured || isBusy}
            className="w-full rounded-xl bg-cyan-500 px-4 py-3 text-sm font-bold text-space-950 hover:bg-cyan-400 disabled:opacity-60 flex items-center justify-center gap-2"
          >
            {auth.operation === 'signing-in' && <LoaderCircle className="w-4 h-4 animate-spin" />}
            {auth.operation === 'signing-in' ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="text-xs leading-5 text-universe-slate/80">
          Demo persona selection is disabled in the normal app flow. Learner data will remain unavailable until trusted account-to-learner mapping is implemented.
        </p>
      </section>
    </main>
  )
}

function BrandHeader() {
  return (
    <div className="flex items-center gap-3">
      <div className="rounded-xl bg-cyan-500/10 p-2 text-cyan-300"><BookOpen className="w-5 h-5" /></div>
      <div>
        <div className="font-display text-lg font-bold tracking-wide text-white">LearnSense</div>
        <div className="text-[10px] font-mono uppercase tracking-widest text-universe-slate">Identity &amp; Access</div>
      </div>
    </div>
  )
}

function AuthMessage({ children }: { children: string }) {
  return <p role="alert" className="rounded-xl border border-red-400/30 bg-red-500/[0.08] px-4 py-3 text-sm leading-5 text-red-200">{children}</p>
}

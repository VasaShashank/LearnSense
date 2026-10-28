import { describe, expect, it, vi } from 'vitest'
import type { AuthChangeEvent, Session } from '@supabase/supabase-js'
import { AuthSessionStore } from './session'

function makeSession(email = 'learner@example.test'): Session {
  return {
    access_token: 'test-only-token',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: 4_000_000_000,
    refresh_token: 'test-only-refresh-token',
    user: { id: 'user-123', email } as Session['user'],
  }
}

function makeClient(initialSession: Session | null = null) {
  let authListener: ((event: AuthChangeEvent, session: Session | null) => void) | undefined
  const auth = {
    onAuthStateChange: vi.fn((callback: typeof authListener) => {
      authListener = callback
      return { data: { subscription: { unsubscribe: vi.fn() } } }
    }),
    getSession: vi.fn().mockResolvedValue({ data: { session: initialSession }, error: null }),
    signInWithPassword: vi.fn().mockResolvedValue({ data: { session: null }, error: null }),
    signOut: vi.fn().mockResolvedValue({ error: null }),
  }
  const client = { auth } as unknown as ConstructorParameters<typeof AuthSessionStore>[0]
  return {
    client,
    auth,
    emit: (event: AuthChangeEvent, session: Session | null) => authListener?.(event, session),
  }
}

describe('AuthSessionStore', () => {
  it('represents a missing Supabase configuration as signed out', () => {
    const store = new AuthSessionStore(null)

    expect(store.configured).toBe(false)
    store.start()
    expect(store.getSnapshot()).toMatchObject({ loading: false, session: null })
  })

  it('restores the existing Supabase session on initialization', async () => {
    const session = makeSession()
    const fake = makeClient(session)
    const store = new AuthSessionStore(fake.client)
    store.start()

    await vi.waitFor(() => expect(store.getSnapshot().session).toBe(session))
    expect(store.getSnapshot().loading).toBe(false)
  })

  it('updates identity on sign-in, refresh, and sign-out auth events', () => {
    const fake = makeClient()
    const store = new AuthSessionStore(fake.client)
    store.start()
    const first = makeSession()
    const refreshed = makeSession('refreshed@example.test')

    fake.emit('SIGNED_IN', first)
    expect(store.getSnapshot().session).toBe(first)
    fake.emit('TOKEN_REFRESHED', refreshed)
    expect(store.getSnapshot().session).toBe(refreshed)
    fake.emit('SIGNED_OUT', null)
    expect(store.getSnapshot().session).toBeNull()
  })

  it('sets the session after successful password sign-in', async () => {
    const fake = makeClient()
    const session = makeSession()
    fake.auth.signInWithPassword.mockResolvedValue({ data: { session }, error: null })
    const store = new AuthSessionStore(fake.client)

    await expect(store.signIn('learner@example.test', 'not-a-real-password')).resolves.toBe(true)
    expect(fake.auth.signInWithPassword).toHaveBeenCalledWith({ email: 'learner@example.test', password: 'not-a-real-password' })
    expect(store.getSnapshot()).toMatchObject({ session, operation: 'idle', error: null })
  })

  it('clears session state only after successful sign-out', async () => {
    const session = makeSession()
    const fake = makeClient(session)
    const store = new AuthSessionStore(fake.client)
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().session).toBe(session))

    await expect(store.signOut()).resolves.toBe(true)
    expect(fake.auth.signOut).toHaveBeenCalledOnce()
    expect(store.getSnapshot()).toMatchObject({ session: null, operation: 'idle', error: null })
  })

  it('reports failed sign-in without creating a session or exposing provider details', async () => {
    const fake = makeClient()
    fake.auth.signInWithPassword.mockResolvedValue({
      data: { session: null },
      error: { message: 'provider response with sensitive detail' },
    })
    const store = new AuthSessionStore(fake.client)

    await expect(store.signIn('learner@example.test', 'bad-password')).resolves.toBe(false)
    expect(store.getSnapshot()).toMatchObject({
      session: null,
      operation: 'idle',
      error: 'Sign-in failed. Check your email and password and try again.',
    })
    expect(store.getSnapshot().error).not.toContain('sensitive detail')
  })

  it('retains the confirmed session and reports failed sign-out', async () => {
    const session = makeSession()
    const fake = makeClient(session)
    fake.auth.signOut.mockResolvedValue({ error: { message: 'provider failure' } })
    const store = new AuthSessionStore(fake.client)
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().session).toBe(session))

    await expect(store.signOut()).resolves.toBe(false)
    expect(store.getSnapshot()).toMatchObject({
      session,
      operation: 'idle',
      error: 'Sign-out failed. Your session status could not be confirmed; please try again.',
    })
  })
})

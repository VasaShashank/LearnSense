import { useEffect, useState, useSyncExternalStore } from 'react'
import type { Session, SupabaseClient } from '@supabase/supabase-js'
import { supabase } from './supabase'

export type AuthOperation = 'idle' | 'signing-in' | 'signing-out'

export interface AuthSessionSnapshot {
  loading: boolean
  session: Session | null
  operation: AuthOperation
  error: string | null
}

type AuthClient = Pick<SupabaseClient, 'auth'>

const INITIAL_SNAPSHOT: AuthSessionSnapshot = {
  loading: true,
  session: null,
  operation: 'idle',
  error: null,
}

/** Owns the browser auth session lifecycle and exposes only session state to React. */
export class AuthSessionStore {
  private snapshot = INITIAL_SNAPSHOT
  private readonly listeners = new Set<() => void>()
  private lifecycle = 0
  private readonly client: AuthClient | null

  constructor(client: AuthClient | null) {
    this.client = client
  }

  get configured(): boolean {
    return this.client !== null
  }

  getSnapshot = (): AuthSessionSnapshot => this.snapshot

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private publish(update: Partial<AuthSessionSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...update }
    this.listeners.forEach((listener) => listener())
  }

  start = (): (() => void) => {
    const lifecycle = ++this.lifecycle
    if (!this.client) {
      this.publish({ loading: false, session: null })
      return () => {
        if (this.lifecycle === lifecycle) this.lifecycle += 1
      }
    }

    let receivedAuthEvent = false
    const { data: { subscription } } = this.client.auth.onAuthStateChange((_event, session) => {
      if (this.lifecycle !== lifecycle) return
      receivedAuthEvent = true
      this.publish({ loading: false, session, error: null })
    })

    void this.client.auth.getSession().then(({ data, error }) => {
      if (this.lifecycle !== lifecycle || receivedAuthEvent) return
      this.publish({
        loading: false,
        session: error ? null : data.session,
        error: error ? 'Unable to restore your Supabase session. Please try signing in again.' : null,
      })
    }).catch(() => {
      if (this.lifecycle !== lifecycle || receivedAuthEvent) return
      this.publish({
        loading: false,
        session: null,
        error: 'Unable to restore your Supabase session. Please try signing in again.',
      })
    })

    return () => {
      if (this.lifecycle === lifecycle) {
        this.lifecycle += 1
        subscription.unsubscribe()
      }
    }
  }

  async signIn(email: string, password: string): Promise<boolean> {
    if (!this.client) {
      this.publish({ error: 'Supabase authentication is not configured for this application.' })
      return false
    }

    this.publish({ operation: 'signing-in', error: null })
    try {
      const { data, error } = await this.client.auth.signInWithPassword({ email, password })
      if (error) {
        this.publish({ operation: 'idle', error: 'Sign-in failed. Check your email and password and try again.' })
        return false
      }
      if (!data.session) {
        this.publish({ operation: 'idle', error: 'Sign-in did not establish a session. Confirm your email if requested, then try again.' })
        return false
      }
      this.publish({ operation: 'idle', session: data.session, error: null, loading: false })
      return true
    } catch {
      this.publish({ operation: 'idle', error: 'Sign-in failed. Check your connection and try again.' })
      return false
    }
  }

  async signOut(): Promise<boolean> {
    if (!this.client) {
      this.publish({ error: 'Supabase authentication is not configured for this application.' })
      return false
    }

    this.publish({ operation: 'signing-out', error: null })
    try {
      const { error } = await this.client.auth.signOut()
      if (error) {
        this.publish({ operation: 'idle', error: 'Sign-out failed. Your session status could not be confirmed; please try again.' })
        try {
          const current = await this.client.auth.getSession()
          if (!current.error) this.publish({ session: current.data.session })
        } catch {
          // Preserve the last known session when its status cannot be confirmed.
        }
        return false
      }
      this.publish({ operation: 'idle', session: null, error: null, loading: false })
      return true
    } catch {
      this.publish({ operation: 'idle', error: 'Sign-out failed. Your session status could not be confirmed; please try again.' })
      return false
    }
  }
}

export const authSessionStore = new AuthSessionStore(supabase)

export function useSupabaseAuth(): AuthSessionSnapshot {
  const [store] = useState(() => authSessionStore)
  useEffect(() => store.start(), [store])
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
}

import { useEffect, useState, useSyncExternalStore } from 'react'
import type { Session, SupabaseClient } from '@supabase/supabase-js'
import { supabase } from './supabase'

export type AuthOperation =
  | 'idle'
  | 'signing-in'
  | 'signing-up'
  | 'signing-out'
  | 'recovering-password'
  | 'updating-password'

export interface AuthSessionSnapshot {
  loading: boolean
  session: Session | null
  operation: AuthOperation
  error: string | null
  isPasswordRecovery: boolean
  needsEmailConfirmation: boolean
  confirmationEmail: string | null
}

type AuthClient = Pick<SupabaseClient, 'auth'>

const INITIAL_SNAPSHOT: AuthSessionSnapshot = {
  loading: true,
  session: null,
  operation: 'idle',
  error: null,
  isPasswordRecovery: false,
  needsEmailConfirmation: false,
  confirmationEmail: null,
}

function mapAuthError(error: any, fallback: string): string {
  if (!error) return fallback
  const msg = (error.message || '').toLowerCase()
  const code = (error.code || '').toLowerCase()

  if (code === 'email_not_confirmed' || msg.includes('email not confirmed')) {
    return 'Your email address has not been confirmed yet. Please check your inbox for the confirmation link or click resend.'
  }
  if (code === 'user_already_exists' || msg.includes('already registered') || msg.includes('already exists')) {
    return 'An account with this email address already exists. Please sign in instead.'
  }
  if (code === 'weak_password' || msg.includes('password should be at least')) {
    return 'Password must be at least 8 characters long and contain a combination of letters and numbers.'
  }
  if (code === 'invalid_credentials' || msg.includes('invalid login credentials')) {
    return 'Invalid email or password. Please check your credentials and try again.'
  }
  if (code === 'over_email_send_rate_limit' || msg.includes('rate limit')) {
    return 'Too many email requests have been sent. Please wait a few minutes before trying again.'
  }
  return error.message || fallback
}

/** Owns the browser auth session lifecycle and exposes session state to React. */
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

  clearError = (): void => {
    this.publish({ error: null })
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
    const { data: { subscription } } = this.client.auth.onAuthStateChange((event, session) => {
      if (this.lifecycle !== lifecycle) return
      receivedAuthEvent = true

      if (event === 'PASSWORD_RECOVERY') {
        this.publish({ loading: false, session, error: null, isPasswordRecovery: true })
        return
      }

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
      const { data, error } = await this.client.auth.signInWithPassword({ email: email.trim(), password })
      if (error) {
        const msg = (error.message || '').toLowerCase()
        const code = (error.code || '').toLowerCase()
        if (code === 'email_not_confirmed' || msg.includes('email not confirmed')) {
          this.publish({ operation: 'idle', error: 'Your email address has not been confirmed yet. Please check your inbox for the confirmation link or click resend.' })
        } else {
          this.publish({ operation: 'idle', error: 'Sign-in failed. Check your email and password and try again.' })
        }
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

  async signUp(email: string, password: string): Promise<{ success: boolean; needsConfirmation: boolean }> {
    if (!this.client) {
      this.publish({ error: 'Supabase authentication is not configured for this application.' })
      return { success: false, needsConfirmation: false }
    }

    this.publish({ operation: 'signing-up', error: null })
    try {
      const trimmedEmail = email.trim()
      const origin = typeof window !== 'undefined' && window.location?.origin ? window.location.origin : 'http://localhost:5173'
      const { data, error } = await this.client.auth.signUp({
        email: trimmedEmail,
        password,
        options: {
          emailRedirectTo: origin,
        },
      })

      if (error) {
        this.publish({ operation: 'idle', error: mapAuthError(error, 'Registration failed. Please check your details.') })
        return { success: false, needsConfirmation: false }
      }

      if (data.session) {
        // Auto-confirmed or confirmations disabled
        this.publish({
          operation: 'idle',
          session: data.session,
          error: null,
          loading: false,
          needsEmailConfirmation: false,
        })
        return { success: true, needsConfirmation: false }
      }

      // Confirmation email required
      this.publish({
        operation: 'idle',
        session: null,
        error: null,
        loading: false,
        needsEmailConfirmation: true,
        confirmationEmail: trimmedEmail,
      })
      return { success: true, needsConfirmation: true }
    } catch {
      this.publish({ operation: 'idle', error: 'Registration failed. Check your connection and try again.' })
      return { success: false, needsConfirmation: false }
    }
  }

  async resetPasswordForEmail(email: string): Promise<boolean> {
    if (!this.client) {
      this.publish({ error: 'Supabase authentication is not configured for this application.' })
      return false
    }

    this.publish({ operation: 'recovering-password', error: null })
    const origin = typeof window !== 'undefined' && window.location?.origin ? window.location.origin : 'http://localhost:5173'
    try {
      const { error } = await this.client.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${origin}#type=recovery`,
      })
      if (error) {
        this.publish({ operation: 'idle', error: mapAuthError(error, 'Password reset request failed.') })
        return false
      }
      this.publish({ operation: 'idle', error: null })
      return true
    } catch {
      this.publish({ operation: 'idle', error: 'Password reset request failed. Check your connection.' })
      return false
    }
  }

  async updatePassword(newPassword: string): Promise<boolean> {
    if (!this.client) {
      this.publish({ error: 'Supabase authentication is not configured for this application.' })
      return false
    }

    this.publish({ operation: 'updating-password', error: null })
    try {
      const { error } = await this.client.auth.updateUser({ password: newPassword })
      if (error) {
        this.publish({ operation: 'idle', error: mapAuthError(error, 'Unable to update password.') })
        return false
      }
      this.publish({ operation: 'idle', error: null, isPasswordRecovery: false })
      return true
    } catch {
      this.publish({ operation: 'idle', error: 'Password update failed. Check your connection.' })
      return false
    }
  }

  async resendVerification(email: string): Promise<boolean> {
    if (!this.client) {
      this.publish({ error: 'Supabase authentication is not configured for this application.' })
      return false
    }

    try {
      const origin = typeof window !== 'undefined' && window.location?.origin ? window.location.origin : 'http://localhost:5173'
      const { error } = await this.client.auth.resend({
        type: 'signup',
        email: email.trim(),
        options: {
          emailRedirectTo: origin,
        },
      })
      if (error) {
        this.publish({ error: mapAuthError(error, 'Failed to resend confirmation email.') })
        return false
      }
      return true
    } catch {
      this.publish({ error: 'Failed to resend confirmation email. Check your connection.' })
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
      this.publish({
        operation: 'idle',
        session: null,
        error: null,
        loading: false,
        isPasswordRecovery: false,
        needsEmailConfirmation: false,
        confirmationEmail: null,
      })
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

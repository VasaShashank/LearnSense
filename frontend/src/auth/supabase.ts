import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.SUPABASE_URL?.trim()
const supabaseKey = (
  import.meta.env.SUPABASE_PUBLISHABLE_KEY || import.meta.env.SUPABASE_ANON_KEY || ''
).trim()

/** Browser client uses only the public project URL and publishable/anon key. */
export const supabase = supabaseUrl && supabaseKey
  ? createClient(supabaseUrl, supabaseKey, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    })
  : null

/** Return the current session token, refreshing an expired session through Supabase. */
export async function getCurrentAccessToken(): Promise<string | null> {
  if (!supabase) return null

  try {
    const { data, error } = await supabase.auth.getSession()
    const session = data.session
    if (error || !session?.access_token) return null
    if (session.expires_at && session.expires_at <= Math.floor(Date.now() / 1000)) return null
    return session.access_token
  } catch {
    // Auth errors must never fall back to a demo persona or be logged with token data.
    return null
  }
}

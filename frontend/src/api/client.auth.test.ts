import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'
import { getCurrentAccessToken } from '../auth/supabase'

vi.mock('../auth/supabase', () => ({
  getCurrentAccessToken: vi.fn(),
}))

const mockedGetCurrentAccessToken = vi.mocked(getCurrentAccessToken)

describe('API client Supabase bearer forwarding', () => {
  beforeEach(() => {
    mockedGetCurrentAccessToken.mockReset()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } })
    ))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('attaches the current Supabase session token to API requests', async () => {
    mockedGetCurrentAccessToken.mockResolvedValue('test-access-token')

    await ApiClient.getSubjects()

    const [, request] = vi.mocked(fetch).mock.calls[0]
    expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer test-access-token')
  })

  it('does not send an Authorization header when no session is available', async () => {
    mockedGetCurrentAccessToken.mockResolvedValue(null)

    await ApiClient.getSubjects()

    const [, request] = vi.mocked(fetch).mock.calls[0]
    expect(new Headers(request?.headers).has('Authorization')).toBe(false)
  })
})

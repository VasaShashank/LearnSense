import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'
import { getCurrentAccessToken } from '../auth/supabase'

vi.mock('../auth/supabase', () => ({
  getCurrentAccessToken: vi.fn(),
}))

const mockedGetCurrentAccessToken = vi.mocked(getCurrentAccessToken)

describe('API client learner initialization', () => {
  beforeEach(() => {
    mockedGetCurrentAccessToken.mockReset()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ learner_id: 'learner-123', status: 'ready', created: true, entry_state: 'SOURCE_SELECTION', subject_id: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    ))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts to the initialization endpoint with the Supabase bearer token', async () => {
    mockedGetCurrentAccessToken.mockResolvedValue('test-access-token')

    const result = await ApiClient.initializeCurrentLearner()

    expect(result.learner_id).toBe('learner-123')
    const [url, request] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('/learners/me/initialize')
    expect(request?.method).toBe('POST')
    expect(new Headers(request?.headers).get('Authorization')).toBe('Bearer test-access-token')
  })

  it('does not send an Authorization header when no session is available', async () => {
    mockedGetCurrentAccessToken.mockResolvedValue(null)

    await ApiClient.initializeCurrentLearner()

    const [, request] = vi.mocked(fetch).mock.calls[0]
    expect(new Headers(request?.headers).has('Authorization')).toBe(false)
  })

  it('propagates API errors from initialization', async () => {
    mockedGetCurrentAccessToken.mockResolvedValue('test-access-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid or expired access token' }), { status: 401, headers: { 'Content-Type': 'application/json' } })
    ))

    await expect(ApiClient.initializeCurrentLearner()).rejects.toThrow('Invalid or expired access token')
  })
})

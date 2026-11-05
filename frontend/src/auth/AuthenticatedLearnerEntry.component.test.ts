import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../api/client'
import { mount } from '../test/hookHarness'
import {
  AuthenticatedLearnerEntry,
  initializeAndResumeLearner,
  userMessageFor,
} from './AuthenticatedLearnerEntry'
import entrySource from './AuthenticatedLearnerEntry.tsx?raw'
import appSource from '../App.tsx?raw'

// Replace only the hooks the component uses with the hook-runtime harness; the real
// component function, its effects and its state logic are what run in these tests.
vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  const harness = await import('../test/hookHarness')
  return {
    ...actual,
    useState: harness.useState,
    useRef: harness.useRef,
    useCallback: harness.useCallback,
    useEffect: harness.useEffect,
  }
})

vi.mock('../api/client', () => ({
  ApiClient: { initializeCurrentLearner: vi.fn(), resumeLearner: vi.fn() },
}))

type Resume = Awaited<ReturnType<typeof ApiClient.resumeLearner>>
type Init = Awaited<ReturnType<typeof ApiClient.initializeCurrentLearner>>

const initMock = vi.mocked(ApiClient.initializeCurrentLearner)
const resumeMock = vi.mocked(ApiClient.resumeLearner)

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const settle = async () => {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0))
}

const init = (learnerId: string): Init => ({
  learner_id: learnerId, status: 'ready', created: false,
  entry_state: 'SOURCE_SELECTION', subject_id: null,
})

const resumed = (learnerId: string, entryState = 'SOURCE_SELECTION'): Resume =>
  ({
    learner_id: learnerId, has_state: true, is_onboarded: false,
    entry_state: entryState, subject_id: null,
  }) as unknown as Resume

const props = (overrides: Partial<{ userId: string; signingOut: boolean }> = {}) => ({
  userId: 'supabase-user-1',
  onSignOut: vi.fn(),
  signingOut: false,
  ...overrides,
})

beforeEach(() => {
  initMock.mockReset()
  resumeMock.mockReset()
})

describe('AuthenticatedLearnerEntry (component behavior)', () => {
  it('shows the loading state while initialization is pending', async () => {
    initMock.mockReturnValue(deferred<Init>().promise)
    const view = mount(AuthenticatedLearnerEntry, props())

    expect(view.text()).toContain('Preparing your learner workspace')
    expect(view.text()).not.toContain('Authenticated learner workspace')
    expect(initMock).toHaveBeenCalledTimes(1)
    expect(resumeMock).not.toHaveBeenCalled()
    expect(view.buttons().map((b) => b.label)).toEqual(['Sign out'])
    expect(view.text()).not.toMatch(/â€|Ã/) // no mojibake in rendered copy
  })

  it('initializes, then resumes with the backend-issued ID rather than the auth user ID', async () => {
    initMock.mockResolvedValue(init('canonical-learner-9'))
    resumeMock.mockResolvedValue(resumed('canonical-learner-9', 'NEEDS_CALIBRATION'))
    const view = mount(AuthenticatedLearnerEntry, props({ userId: 'supabase-user-1' }))
    await settle()

    expect(initMock).toHaveBeenCalledWith()               // no client-supplied identity
    expect(resumeMock).toHaveBeenCalledTimes(1)
    expect(resumeMock).toHaveBeenCalledWith('canonical-learner-9')
    expect(resumeMock).not.toHaveBeenCalledWith('supabase-user-1')
    expect(view.text()).toContain('Authenticated learner workspace')
    expect(view.text()).toContain('canonical-learner-9')
    expect(view.text()).toContain('NEEDS_CALIBRATION')
    expect(view.text()).toContain('complete the self-assessment')
    expect(view.buttons().map((b) => b.label)).toEqual(['Sign out'])
  })

  it('shows a safe message on initialization failure and recovers on retry', async () => {
    const internal = Object.assign(
      new Error('Could not reach the LearnSense backend at http://localhost:8000. (ECONNREFUSED 127.0.0.1)'),
      { status: 0, code: 'BACKEND_UNREACHABLE' },
    )
    initMock.mockRejectedValueOnce(internal)
    const view = mount(AuthenticatedLearnerEntry, props())
    await settle()

    expect(view.text()).toContain('Learner workspace unavailable')
    expect(view.text()).toContain('temporarily unreachable')
    expect(view.text()).not.toContain('localhost')
    expect(view.text()).not.toContain('ECONNREFUSED')
    expect(resumeMock).not.toHaveBeenCalled()

    initMock.mockResolvedValueOnce(init('learner-a'))
    resumeMock.mockResolvedValueOnce(resumed('learner-a'))
    view.click('Retry')
    expect(view.text()).toContain('Preparing your learner workspace')
    await settle()

    expect(initMock).toHaveBeenCalledTimes(2)
    expect(view.text()).toContain('Authenticated learner workspace')
    expect(view.text()).toContain('learner-a')
  })

  it('shows a safe message on resume failure and retries the whole sequence', async () => {
    initMock.mockResolvedValue(init('learner-b'))
    resumeMock.mockRejectedValueOnce(
      Object.assign(new Error('Traceback: KeyError at resume_learner_state line 9'), { status: 500 }),
    )
    const view = mount(AuthenticatedLearnerEntry, props())
    await settle()

    expect(view.text()).toContain('Learner workspace unavailable')
    expect(view.text()).not.toContain('Traceback')
    expect(view.text()).not.toContain('KeyError')

    resumeMock.mockResolvedValueOnce(resumed('learner-b'))
    view.click('Retry')
    await settle()

    expect(initMock).toHaveBeenCalledTimes(2)
    expect(resumeMock).toHaveBeenCalledTimes(2)
    expect(resumeMock).toHaveBeenLastCalledWith('learner-b')
    expect(view.text()).toContain('Authenticated learner workspace')
  })

  it('offers sign-out during initialization and disables it while signing out', async () => {
    initMock.mockReturnValue(deferred<Init>().promise)
    const first = props()
    const view = mount(AuthenticatedLearnerEntry, first)

    view.click('Sign out')
    expect(first.onSignOut).toHaveBeenCalledTimes(1)

    view.rerender({ ...first, signingOut: true })
    expect(view.buttons()).toEqual([{ label: 'Signing out…', disabled: true }])
    view.click('Signing out')
    expect(first.onSignOut).toHaveBeenCalledTimes(1) // disabled: no second sign-out
  })

  it('disables retry while a sign-out is in progress on the error screen', async () => {
    initMock.mockRejectedValue(new Error('boom'))
    const first = props()
    const view = mount(AuthenticatedLearnerEntry, first)
    await settle()
    view.rerender({ ...first, signingOut: true })

    expect(view.buttons().every((b) => b.disabled)).toBe(true)
    view.click('Retry')
    expect(initMock).toHaveBeenCalledTimes(1)
  })

  it('discards a superseded run when the signed-in user changes (stale resolves last)', async () => {
    const firstInit = deferred<Init>()
    const secondInit = deferred<Init>()
    initMock.mockReturnValueOnce(firstInit.promise).mockReturnValueOnce(secondInit.promise)
    resumeMock.mockImplementation(async (id: string) => resumed(id))

    const first = props({ userId: 'user-1' })
    const view = mount(AuthenticatedLearnerEntry, first)
    view.rerender({ ...first, userId: 'user-2' })
    expect(initMock).toHaveBeenCalledTimes(2)

    secondInit.resolve(init('learner-of-user-2'))
    await settle()
    expect(view.text()).toContain('learner-of-user-2')

    firstInit.resolve(init('learner-of-user-1'))
    await settle()
    expect(view.text()).toContain('learner-of-user-2')
    expect(view.text()).not.toContain('learner-of-user-1')
  })

  it('does not show a superseded user result even if it resolves first', async () => {
    const firstInit = deferred<Init>()
    const secondInit = deferred<Init>()
    initMock.mockReturnValueOnce(firstInit.promise).mockReturnValueOnce(secondInit.promise)
    resumeMock.mockImplementation(async (id: string) => resumed(id))

    const first = props({ userId: 'user-1' })
    const view = mount(AuthenticatedLearnerEntry, first)
    view.rerender({ ...first, userId: 'user-2' })

    firstInit.resolve(init('learner-of-user-1'))
    await settle()
    expect(view.text()).toContain('Preparing your learner workspace')
    expect(view.text()).not.toContain('learner-of-user-1')

    secondInit.resolve(init('learner-of-user-2'))
    await settle()
    expect(view.text()).toContain('learner-of-user-2')
    expect(view.text()).not.toContain('learner-of-user-1')
  })

  it('ignores a stale failure after the user changed', async () => {
    const firstInit = deferred<Init>()
    initMock.mockReturnValueOnce(firstInit.promise).mockResolvedValueOnce(init('learner-2'))
    resumeMock.mockResolvedValue(resumed('learner-2'))

    const first = props({ userId: 'user-1' })
    const view = mount(AuthenticatedLearnerEntry, first)
    view.rerender({ ...first, userId: 'user-2' })
    await settle()
    firstInit.reject(new Error('late failure of the old session'))
    await settle()

    expect(view.text()).toContain('Authenticated learner workspace')
    expect(view.text()).not.toContain('unavailable')
  })

  it('makes no state updates when unmounted while requests are pending', async () => {
    const pendingInit = deferred<Init>()
    initMock.mockReturnValue(pendingInit.promise)
    resumeMock.mockResolvedValue(resumed('learner-late'))
    const view = mount(AuthenticatedLearnerEntry, props())

    view.unmount()
    pendingInit.resolve(init('learner-late'))
    await settle()

    expect(view.lateStateUpdates).toBe(0)
  })

  it('makes no state updates when unmounted before a pending request fails', async () => {
    const pendingInit = deferred<Init>()
    initMock.mockReturnValue(pendingInit.promise)
    const view = mount(AuthenticatedLearnerEntry, props())

    view.unmount()
    pendingInit.reject(new Error('late failure'))
    await settle()

    expect(view.lateStateUpdates).toBe(0)
  })
})

describe('error presentation policy', () => {
  it.each([
    [{ status: 401 }, 'no longer valid'],
    [{ status: 403 }, 'does not have access'],
    [{ status: 404 }, 'does not have access'],
    [{ status: 409 }, 'needs attention'],
    [{ status: 503 }, 'temporarily unreachable'],
    [{ status: 0, code: 'BACKEND_UNREACHABLE' }, 'temporarily unreachable'],
    [{ code: 'REQUEST_TIMEOUT' }, 'temporarily unreachable'],
    [{ status: 422 }, 'could not load'],
    [new Error('plain failure'), 'could not load'],
    ['a string', 'could not load'],
    [null, 'could not load'],
  ])('maps %j to a fixed message', (error, fragment) => {
    const message = userMessageFor(error)
    expect(message).toContain(fragment)
    expect(message).not.toMatch(/plain failure|http|localhost/i)
  })
})

describe('initializeAndResumeLearner integrity checks', () => {
  it('rejects an initialization response without a usable learner ID', async () => {
    const resume = vi.fn()
    await expect(initializeAndResumeLearner(async () => ({ learner_id: '' }), resume)).rejects.toThrow()
    await expect(
      initializeAndResumeLearner(async () => ({}) as { learner_id: string }, resume),
    ).rejects.toThrow()
    expect(resume).not.toHaveBeenCalled()
  })

  it('rejects a resume response for a different learner', async () => {
    await expect(
      initializeAndResumeLearner(async () => ({ learner_id: 'a' }), async () => resumed('b')),
    ).rejects.toThrow(/did not match/)
  })
})

describe('no demo-persona fallback in the authenticated path', () => {
  const personaTokens = /PRESET_PERSONAS|LoginPersonaModal|DemoPersonaWorkspace|currentPersona|student_alex|prof_vance/

  it('the authenticated entry component references no persona machinery', () => {
    expect(entrySource).not.toMatch(personaTokens)
  })

  it('the App entry mounts the authenticated component and no persona workspace', () => {
    const start = appSource.indexOf('export default function App()')
    const end = appSource.indexOf('export function DemoPersonaWorkspace')
    expect(start).toBeGreaterThan(-1)
    expect(end).toBeGreaterThan(start)
    const appEntry = appSource.slice(start, end)
    expect(appEntry).toContain('AuthenticatedLearnerEntry')
    expect(appEntry).not.toMatch(personaTokens)
  })

  it('the entry source contains no mojibake sequences', () => {
    expect(entrySource).not.toContain('â€')
  })
})

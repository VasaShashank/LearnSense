import { describe, expect, it, vi } from 'vitest'
import { initializeAndResumeLearner } from './AuthenticatedLearnerEntry'

describe('initializeAndResumeLearner', () => {
  it('initializes then resumes using the server-returned learner ID', async () => {
    const initialize = vi.fn().mockResolvedValue({ learner_id: 'learner-123', status: 'ready', created: true })
    const resume = vi.fn().mockResolvedValue({ learner_id: 'learner-123', entry_state: 'SOURCE_SELECTION' })

    const result = await initializeAndResumeLearner(initialize, resume)

    expect(initialize).toHaveBeenCalledTimes(1)
    expect(resume).toHaveBeenCalledWith('learner-123')
    expect(result).toEqual({ learnerId: 'learner-123', resume: { learner_id: 'learner-123', entry_state: 'SOURCE_SELECTION' } })
  })

  it('propagates initialization failures without calling resume', async () => {
    const initialize = vi.fn().mockRejectedValue(new Error('init failed'))
    const resume = vi.fn()

    await expect(initializeAndResumeLearner(initialize, resume)).rejects.toThrow('init failed')
    expect(resume).not.toHaveBeenCalled()
  })

  it('propagates resume failures after successful initialization', async () => {
    const initialize = vi.fn().mockResolvedValue({ learner_id: 'learner-123', status: 'ready', created: false })
    const resume = vi.fn().mockRejectedValue(new Error('resume failed'))

    await expect(initializeAndResumeLearner(initialize, resume)).rejects.toThrow('resume failed')
    expect(initialize).toHaveBeenCalledTimes(1)
    expect(resume).toHaveBeenCalledWith('learner-123')
  })
})

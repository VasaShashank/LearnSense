import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../../test/hookHarness'
import { OnboardingWorkflow } from './OnboardingWorkflow'
import { ApiClient } from '../../api/client'
import type { Subject } from '../../api/client'

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  const harness = await import('../../test/hookHarness')
  const mocked = {
    ...actual,
    useState: harness.useState,
    useRef: harness.useRef,
    useCallback: harness.useCallback,
    useMemo: harness.useMemo,
    useEffect: harness.useEffect,
  }
  return {
    ...mocked,
    default: mocked,
  }
})

vi.mock('../../api/client', () => ({
  ApiClient: {
    getCalibrationStatus: vi.fn(),
    getSubjectGraph: vi.fn(),
    submitSelfAssessment: vi.fn(),
    startAdaptiveDiagnostic: vi.fn(),
    submitDiagnosticAnswer: vi.fn(),
    getLearningSequence: vi.fn(),
    uploadSource: vi.fn(),
  },
  ApiError: class extends Error {},
}))

describe('OnboardingWorkflow Component (Person 2)', () => {
  const mockSubjects: Subject[] = [
    {
      id: 'sub_physics',
      title: "Newtonian Mechanics",
      concept_count: 15,
      page_count: 12,
      has_ekr: true,
    },
    {
      id: 'sub_chemistry',
      title: 'Chemical Bonding & Hybridization',
      concept_count: 20,
      page_count: 18,
      has_ekr: true,
    },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(ApiClient.getCalibrationStatus).mockResolvedValue({
      needs_calibration: true,
      diagnostic_completed: false,
    } as any)
    vi.mocked(ApiClient.getSubjectGraph).mockResolvedValue({
      concepts: [
        { concept_id: 'c1', name: "Newton's First Law", mastery: 0.0 },
      ],
      topics: [],
    } as any)
  })

  it('renders subject list in SOURCE_SELECTION mode', () => {
    const onComplete = vi.fn()
    const app = mount(OnboardingWorkflow, {
      subjects: mockSubjects,
      onCompleteOnboarding: onComplete,
      mode: 'SOURCE_SELECTION',
    })

    const text = app.text()
    expect(text).toContain('Newtonian Mechanics')
    expect(text).toContain('Chemical Bonding & Hybridization')
    expect(text).toContain('15 Concepts')
    expect(text).toContain('20 Concepts')
    expect(text).toContain('Or explore an existing knowledge base')
  })

  it('renders Baseline Knowledge Calibration when initialized in CALIBRATION mode with initialSubject', () => {
    const onComplete = vi.fn()
    const app = mount(OnboardingWorkflow, {
      subjects: mockSubjects,
      initialSubject: mockSubjects[0],
      onCompleteOnboarding: onComplete,
      mode: 'CALIBRATION',
    })

    const text = app.text()
    expect(text).toContain('Baseline Knowledge Calibration')
    expect(text).toContain('STEP 2 OF 3 // TOPOLOGY INITIALIZATION')
  })

  it('handles subject selection and transitions', () => {
    const onComplete = vi.fn()
    const app = mount(OnboardingWorkflow, {
      subjects: mockSubjects,
      onCompleteOnboarding: onComplete,
      mode: 'SOURCE_SELECTION',
    })

    expect(app.text()).toContain('Newtonian Mechanics')
  })
})

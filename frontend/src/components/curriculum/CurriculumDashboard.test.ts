import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../../test/hookHarness'
import { CurriculumDashboard } from './CurriculumDashboard'
import { ApiClient } from '../../api/client'
import type { Persona } from '../common/LoginPersonaModal'

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  const harness = await import('../../test/hookHarness')
  return {
    ...actual,
    useState: harness.useState,
    useRef: harness.useRef,
    useCallback: harness.useCallback,
    useMemo: harness.useMemo,
    useEffect: harness.useEffect,
  }
})

vi.mock('../../api/client', () => ({
  ApiClient: {
    getCurriculumStatus: vi.fn(),
    validateCurriculumGraph: vi.fn(),
    getSubjects: vi.fn(),
    listSubjects: vi.fn(),
    getDocumentReview: vi.fn(),
    getDocumentPageEvidence: vi.fn(),
    reviewDocumentConcept: vi.fn(),
    batchApproveDocument: vi.fn(),
    listCurriculumConcepts: vi.fn(),
    listCurriculumRelationships: vi.fn(),
    listCanonicalConcepts: vi.fn(),
    listCanonicalRelationships: vi.fn(),
    listCurriculumVersions: vi.fn(),
    publishCurriculumRelease: vi.fn(),
    rollbackCurriculumRelease: vi.fn(),
  },
}))

describe('CurriculumDashboard Component (Person 2)', () => {
  const mockTeacherPersona: Persona = {
    id: 'fac_vance',
    name: 'Prof. Vance',
    role: 'TEACHER',
    title: 'Professor of Physics',
    avatar: '👨‍🏫',
    org_name: 'Apex Institute',
    email: 'vance@apex.edu',
  }

  const mockStudentPersona: Persona = {
    id: 'stud_alex',
    name: 'Alex Rivera',
    role: 'LEARNER',
    title: 'Undergraduate Learner',
    avatar: '👨‍🎓',
    org_name: 'Apex Institute',
    email: 'alex@apex.edu',
  }

  const mockCurriculumStatus = {
    active_version: 'v1.0.0',
    total_canonical_concepts: 48,
    total_canonical_relationships: 72,
    pending_document_reviews: 2,
    is_dag: true,
    last_validated_at: '2026-11-08T18:00:00Z',
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(ApiClient.getCurriculumStatus).mockResolvedValue(mockCurriculumStatus as any)
    vi.mocked(ApiClient.validateCurriculumGraph).mockResolvedValue({
      is_valid: true,
      error_count: 0,
      cycle_count: 0,
      cycles: [],
      disconnected_count: 0,
    } as any)
    vi.mocked(ApiClient.getSubjects).mockResolvedValue([])
    vi.mocked(ApiClient.listCurriculumConcepts).mockResolvedValue({ concepts: [], total: 0 } as any)
    vi.mocked(ApiClient.listCurriculumRelationships).mockResolvedValue({ relationships: [], total: 0 } as any)
    vi.mocked(ApiClient.listCurriculumVersions).mockResolvedValue({ versions: [], current_version: 'v1.0.0' } as any)
  })

  it('renders read-only warning badge when user is a student', () => {
    const app = mount(CurriculumDashboard, {
      currentPersona: mockStudentPersona,
      onNavigateToAtlas: vi.fn(),
    })

    const text = app.text()
    expect(text).toContain('Read-Only Mode')
    expect(text).toContain('You are signed in as a student persona')
    expect(text).toContain('RESTRICTED')
  })

  it('renders full authorized header and status cards for teacher persona', () => {
    const app = mount(CurriculumDashboard, {
      currentPersona: mockTeacherPersona,
      onNavigateToAtlas: vi.fn(),
    })

    const text = app.text()
    expect(text).not.toContain('Read-Only Mode')
    expect(text).toContain('Curriculum & Concept Governance')
    expect(text).toContain('Prof. Vance')
    expect(text).toContain('Overview')
    expect(text).toContain('Pending Review Queue')
    expect(text).toContain('Concept Management')
    expect(text).toContain('Relationship Review')
    expect(text).toContain('Publishing & Version History')
  })

  it('allows switching between dashboard tabs', () => {
    const app = mount(CurriculumDashboard, {
      currentPersona: mockTeacherPersona,
      onNavigateToAtlas: vi.fn(),
    })

    const buttons = app.buttons()
    const pendingTab = buttons.find(b => b.label.includes('Pending Review Queue'))
    expect(pendingTab).toBeDefined()
    if (pendingTab) {
      app.click(pendingTab.label)
      expect(app.text()).toContain('Pending Review Queue')
    }
  })

  it('triggers validate curriculum graph on button click', async () => {
    const app = mount(CurriculumDashboard, {
      currentPersona: mockTeacherPersona,
      onNavigateToAtlas: vi.fn(),
    })

    const buttons = app.buttons()
    const validateBtn = buttons.find(b => b.label.includes('Validate DAG') || b.label.includes('Validate Graph') || b.label.includes('Strict DAG'))
    if (validateBtn) {
      app.click(validateBtn.label)
      expect(ApiClient.validateCurriculumGraph).toHaveBeenCalled()
    }
  })
})

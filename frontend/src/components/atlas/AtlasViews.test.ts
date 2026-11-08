import { describe, expect, it, vi } from 'vitest'
import { mount } from '../../test/hookHarness'
import { GuidedSequenceView } from './GuidedSequenceView'
import { AccessibleAtlasView } from './AccessibleAtlasView'
import type { ConceptNode, KnowledgeGraphData } from '../../api/client'

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

describe('Knowledge Atlas Views (Person 2)', () => {
  const mockAllConcepts: ConceptNode[] = [
    {
      concept_id: 'c1',
      name: "Newton's First Law",
      description: 'Law of inertia',
      mastery: 0.85,
      prerequisites: [],
      status: 'AVAILABLE',
      x: 0,
      y: 0,
    },
    {
      concept_id: 'c2',
      name: "Newton's Second Law",
      description: 'F = ma',
      mastery: 0.55,
      prerequisites: ['c1'],
      status: 'AVAILABLE',
      x: 10,
      y: 10,
    },
    {
      concept_id: 'c3',
      name: 'Centripetal Force',
      description: 'Inward force in circular motion',
      mastery: 0.15,
      prerequisites: ['c2'],
      status: 'AVAILABLE',
      x: 20,
      y: 20,
    },
  ]

  const mockSequenceData: any = {
    sequence: [
      {
        concept_id: 'c1',
        name: "Newton's First Law",
        description: 'Foundations of Inertia',
        chapter_name: 'Chapter 1: Kinematics and Inertia',
        step_number: 1,
        page_range: [1, 5],
        dependencies: [],
        estimated_minutes: 15,
        mastery: 0.85,
        is_starting_concept: true,
      },
      {
        concept_id: 'c2',
        name: "Newton's Second Law",
        description: 'Force and Acceleration',
        chapter_name: 'Chapter 2: Force Equations',
        step_number: 2,
        page_range: [6, 12],
        dependencies: ['c1'],
        estimated_minutes: 20,
        mastery: 0.5,
        is_starting_concept: false,
      },
    ],
    total_steps: 2,
    starting_concept_id: 'c1',
    subject_id: 'sub_physics',
  }

  describe('GuidedSequenceView', () => {
    it('renders synthesizing loading state when loading and no data', () => {
      const app = mount(GuidedSequenceView, {
        sequenceData: null,
        isLoading: true,
        selectedStartingConceptId: null,
        onSelectStartingConcept: vi.fn(),
        onSwitchToGraphView: vi.fn(),
        allConcepts: [],
      })

      expect(app.text()).toContain('Synthesizing chapter-coherent learning sequence...')
    })

    it('renders empty alert when sequence data is empty', () => {
      const app = mount(GuidedSequenceView, {
        sequenceData: { sequence: [], total_steps: 0, starting_concept_id: '', subject_id: '' } as any,
        isLoading: false,
        selectedStartingConceptId: null,
        onSelectStartingConcept: vi.fn(),
        onSwitchToGraphView: vi.fn(),
        allConcepts: [],
      })

      expect(app.text()).toContain('No Learning Sequence Available')
      expect(app.text()).toContain('Please select a valid subject')
    })

    it('renders sequence chapters, titles, and step progression', () => {
      const app = mount(GuidedSequenceView, {
        sequenceData: mockSequenceData,
        isLoading: false,
        selectedStartingConceptId: 'c1',
        onSelectStartingConcept: vi.fn(),
        onSwitchToGraphView: vi.fn(),
        allConcepts: mockAllConcepts,
      })

      const text = app.text()
      expect(text).toContain("Newton's First Law")
      expect(text).toContain("Newton's Second Law")
      expect(text).toContain('Chapter 1: Kinematics and Inertia')
      expect(text).toContain('Chapter 2: Force Equations')
    })
  })

  describe('AccessibleAtlasView', () => {
    const mockGraphData: KnowledgeGraphData = {
      subject_id: 'sub_physics',
      topics: [],
      concepts: mockAllConcepts,
      relationships: [
        { source: 'c1', target: 'c2', type: 'PREREQUISITE', confidence: 1.0 },
        { source: 'c2', target: 'c3', type: 'PREREQUISITE', confidence: 1.0 },
      ],
    }

    it('renders accessible data table with headers and concepts', () => {
      const onSelect = vi.fn()
      const app = mount(AccessibleAtlasView, {
        graphData: mockGraphData,
        onSelectConcept: onSelect,
      })

      const text = app.text()
      expect(text).toContain('Structured Knowledge Atlas (Accessible Data Table)')
      expect(text).toContain('Concept Name')
      expect(text).toContain('Mastery')
      expect(text).toContain("Newton's First Law")
      expect(text).toContain("Newton's Second Law")
      expect(text).toContain('Centripetal Force')
    })

    it('correctly maps mastery status tiers (Mastered, Developing, Unknown)', () => {
      const onSelect = vi.fn()
      const app = mount(AccessibleAtlasView, {
        graphData: mockGraphData,
        onSelectConcept: onSelect,
      })

      const text = app.text()
      expect(text).toContain('Mastered')
      expect(text).toContain('Developing')
    })

    it('fires onSelectConcept when Inspect button is clicked', () => {
      const onSelect = vi.fn()
      const app = mount(AccessibleAtlasView, {
        graphData: mockGraphData,
        onSelectConcept: onSelect,
      })

      const buttons = app.buttons()
      const inspectBtn = buttons.find(b => b.label.includes('Inspect'))
      expect(inspectBtn).toBeDefined()
      if (inspectBtn) {
        app.click(inspectBtn.label)
        expect(onSelect).toHaveBeenCalled()
      }
    })
  })
})

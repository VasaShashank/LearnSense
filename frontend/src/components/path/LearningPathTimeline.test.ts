import { describe, expect, it, vi } from 'vitest'
import { mount } from '../../test/hookHarness'
import { LearningPathTimeline } from './LearningPathTimeline'
import type { LearningPathNode, LearningTarget } from '../../api/client'

// Replace React hooks with hook-runtime harness
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

describe('LearningPathTimeline Component (Person 2)', () => {
  const mockNodes: LearningPathNode[] = [
    {
      concept_id: 'c1',
      name: "Newton's First Law",
      status: 'COMPLETED',
      mastery: 0.95,
      prerequisites: [],
    },
    {
      concept_id: 'c2',
      name: "Newton's Second Law",
      status: 'ACTIVE_TARGET',
      mastery: 0.5,
      prerequisites: ['c1'],
    },
    {
      concept_id: 'c3',
      name: "Newton's Third Law",
      status: 'AVAILABLE',
      mastery: 0.1,
      prerequisites: ['c1'],
    },
    {
      concept_id: 'c4',
      name: 'Friction and Drag Forces',
      status: 'BLOCKED',
      mastery: 0.0,
      prerequisites: ['c2', 'c3'],
    },
  ]

  const mockActiveTarget: LearningTarget = {
    concept_id: 'c2',
    name: "Newton's Second Law",
    reason: 'Highest marginal information gain based on recent diagnostic response',
  }

  it('renders learning path header, active target badge, and progression description', () => {
    const onSelect = vi.fn()
    const app = mount(LearningPathTimeline, {
      nodes: mockNodes,
      activeTarget: mockActiveTarget,
      onSelectConcept: onSelect,
    })

    const text = app.text()
    expect(text).toContain('Personalized Learning Path')
    expect(text).toContain('EXPEDITION VECTOR // KNOWLEDGE JOURNEY')
    expect(text).toContain("ACTIVE TARGET: Newton's Second Law")
    expect(text).toContain('NEXT STEP IN JOURNEY')
    expect(text).toContain('Highest marginal information gain based on recent diagnostic response')
  })

  it('renders all path nodes with corresponding status and mastery indicators', () => {
    const onSelect = vi.fn()
    const app = mount(LearningPathTimeline, {
      nodes: mockNodes,
      activeTarget: mockActiveTarget,
      onSelectConcept: onSelect,
    })

    const text = app.text()
    expect(text).toContain("Newton's First Law")
    expect(text).toContain("Newton's Second Law")
    expect(text).toContain("Newton's Third Law")
    expect(text).toContain('Friction and Drag Forces')
    expect(text).toContain('95%')
    expect(text).toContain('50%')
    expect(text).toContain('10%')
  })

  it('triggers onSelectConcept when a concept action button is clicked', () => {
    const onSelect = vi.fn()
    const app = mount(LearningPathTimeline, {
      nodes: mockNodes,
      activeTarget: mockActiveTarget,
      onSelectConcept: onSelect,
    })

    const buttons = app.buttons()
    expect(buttons.length).toBeGreaterThan(0)

    // Click on active target button
    const continueBtn = buttons.find(b => b.label.includes('Continue Journey'))
    expect(continueBtn).toBeDefined()
    if (continueBtn) {
      app.click(continueBtn.label)
      expect(onSelect).toHaveBeenCalledWith('c2')
    }
  })

  it('renders gracefully when activeTarget is null', () => {
    const onSelect = vi.fn()
    const app = mount(LearningPathTimeline, {
      nodes: mockNodes,
      activeTarget: null,
      onSelectConcept: onSelect,
    })

    const text = app.text()
    expect(text).toContain('Personalized Learning Path')
    expect(text).not.toContain('NEXT STEP IN JOURNEY')
  })
})

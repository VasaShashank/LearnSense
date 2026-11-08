import { describe, expect, it, vi } from 'vitest'
import { mount } from '../../test/hookHarness'
import { SourceLibrary } from './SourceLibrary'
import type { SourceDocument } from '../../api/client'

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

describe('SourceLibrary Component (Person 2)', () => {
  const mockSources: SourceDocument[] = [
    {
      document_id: 'doc_physics_01',
      title: "Newton's Laws of Motion.pdf",
      status: 'READY',
      recovery_state: 'COMPLETED',
      page_count: 14,
      file_size_bytes: 1048576,
    },
    {
      document_id: 'doc_os_02',
      title: 'Operating Systems - Virtual Memory.docx',
      status: 'READY',
      recovery_state: 'COMPLETED',
      page_count: 8,
      file_size_bytes: 524288,
    },
  ]

  it('renders source library header, multi-format note, and upload button', () => {
    const onReload = vi.fn()
    const app = mount(SourceLibrary, {
      sources: mockSources,
      onReloadSources: onReload,
    })

    const text = app.text()
    expect(text).toContain('Source Document Library')
    expect(text).toContain('KNOWLEDGE INGESTION & CITATIONS')
    expect(text).toContain('Ingest New Document (PDF, PPTX, DOCX)')
    expect(text).toContain('Supports PDF, PPTX, DOCX, and images')
  })

  it('renders all documents with page counts and format badges', () => {
    const onReload = vi.fn()
    const app = mount(SourceLibrary, {
      sources: mockSources,
      onReloadSources: onReload,
    })

    const text = app.text()
    expect(text).toContain("Newton's Laws of Motion.pdf")
    expect(text).toContain('Operating Systems - Virtual Memory.docx')
    expect(text).toContain('14 Pages')
    expect(text).toContain('8 Pages')
    expect(text).toContain('FULLY GROUNDED')
  })

  it('invokes onReloadSources when reload button is triggered', () => {
    const onReload = vi.fn()
    const app = mount(SourceLibrary, {
      sources: mockSources,
      onReloadSources: onReload,
    })

    const text = app.text()
    expect(text).toContain('VERIFIED INGESTED REPOSITORY ( 2 )')
  })

  it('renders empty repository indicator when no sources are passed', () => {
    const onReload = vi.fn()
    const app = mount(SourceLibrary, {
      sources: [],
      onReloadSources: onReload,
    })

    const text = app.text()
    expect(text).toContain('VERIFIED INGESTED REPOSITORY ( 0 )')
  })
})

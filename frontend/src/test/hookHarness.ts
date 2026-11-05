/**
 * Minimal React hook runtime for component-level tests without a DOM.
 *
 * Why this exists: the project has no jsdom/happy-dom/Testing Library, so real
 * mounting is unavailable. This harness executes the REAL component function with
 * working state, refs, callbacks and effects (including cleanup), lets tests inspect
 * the returned element tree and invoke handlers, and counts state updates attempted
 * after unmount. It is not a substitute for a browser: no StrictMode double-invoke,
 * scheduler timing, concurrent rendering or real DOM events.
 *
 * Tests install it with `vi.mock('react', ...)` replacing only the four hooks used.
 * This module must not import 'react'.
 */

interface EffectSlot {
  first: boolean
  deps: readonly unknown[] | undefined
  cleanup: (() => void) | undefined
}

interface Instance {
  hooks: unknown[]
  index: number
  pending: Array<() => void>
  effects: EffectSlot[]
  dirty: boolean
  rendering: boolean
  mounted: boolean
  lateStateUpdates: number
  flush: () => void
}

let current: Instance | null = null

function active(): Instance {
  if (!current) throw new Error('Hook called outside of a harness render')
  return current
}

function depsChanged(prev: readonly unknown[] | undefined, next: readonly unknown[] | undefined): boolean {
  if (!prev || !next) return true
  return next.length !== prev.length || next.some((value, i) => !Object.is(value, prev[i]))
}

export function useState<T>(initial: T | (() => T)): [T, (value: T | ((previous: T) => T)) => void] {
  const instance = active()
  const idx = instance.index++
  if (!(idx in instance.hooks)) {
    const slot = {
      value: typeof initial === 'function' ? (initial as () => T)() : initial,
      set: (_value: T | ((previous: T) => T)) => {},
    }
    slot.set = (value) => {
      if (!instance.mounted) {
        instance.lateStateUpdates += 1
        return
      }
      const next = typeof value === 'function' ? (value as (previous: T) => T)(slot.value) : value
      if (Object.is(next, slot.value)) return
      slot.value = next
      instance.dirty = true
      instance.flush()
    }
    instance.hooks[idx] = slot
  }
  const slot = instance.hooks[idx] as { value: T; set: (value: T | ((previous: T) => T)) => void }
  return [slot.value, slot.set]
}

export function useRef<T>(initial: T): { current: T } {
  const instance = active()
  const idx = instance.index++
  if (!(idx in instance.hooks)) instance.hooks[idx] = { current: initial }
  return instance.hooks[idx] as { current: T }
}

export function useCallback<F extends (...args: never[]) => unknown>(fn: F, deps: readonly unknown[]): F {
  const instance = active()
  const idx = instance.index++
  const slot = instance.hooks[idx] as { fn: F; deps: readonly unknown[] } | undefined
  if (!slot || depsChanged(slot.deps, deps)) {
    instance.hooks[idx] = { fn, deps }
    return fn
  }
  return slot.fn
}

export function useEffect(effect: () => void | (() => void), deps?: readonly unknown[]): void {
  const instance = active()
  const idx = instance.index++
  if (!(idx in instance.hooks)) {
    const slot: EffectSlot = { first: true, deps: undefined, cleanup: undefined }
    instance.hooks[idx] = slot
    instance.effects.push(slot)
  }
  const slot = instance.hooks[idx] as EffectSlot
  if (slot.first || depsChanged(slot.deps, deps)) {
    instance.pending.push(() => {
      slot.cleanup?.()
      const cleanup = effect()
      slot.cleanup = typeof cleanup === 'function' ? cleanup : undefined
      slot.deps = deps
      slot.first = false
    })
  }
}

// --- Element inspection -----------------------------------------------------

export interface HarnessElement {
  type: unknown
  props: Record<string, unknown> & { children?: unknown }
}

function isElement(node: unknown): node is HarnessElement {
  return typeof node === 'object' && node !== null && 'props' in node && 'type' in node
}

function childrenOf(node: unknown): unknown[] {
  if (!isElement(node)) return []
  const { children } = node.props
  return Array.isArray(children) ? children.flat(Infinity) : children === undefined ? [] : [children]
}

export function textOf(node: unknown): string {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  return childrenOf(node).map(textOf).join(' ').replace(/\s+/g, ' ').trim()
}

export function findAll(node: unknown, predicate: (element: HarnessElement) => boolean): HarnessElement[] {
  const found: HarnessElement[] = []
  const visit = (candidate: unknown) => {
    if (!isElement(candidate)) return
    if (predicate(candidate)) found.push(candidate)
    childrenOf(candidate).forEach(visit)
  }
  visit(node)
  return found
}

// --- Mounting ---------------------------------------------------------------

export interface MountedComponent<P> {
  readonly output: unknown
  readonly lateStateUpdates: number
  text(): string
  buttons(): Array<{ label: string; disabled: boolean }>
  click(label: string): void
  rerender(props: P): void
  unmount(): void
}

export function mount<P>(component: (props: P) => unknown, initialProps: P): MountedComponent<P> {
  let props = initialProps
  let output: unknown = null

  const instance: Instance = {
    hooks: [],
    index: 0,
    pending: [],
    effects: [],
    dirty: false,
    rendering: false,
    mounted: true,
    lateStateUpdates: 0,
    flush: () => {},
  }

  const renderOnce = () => {
    instance.index = 0
    instance.pending = []
    current = instance
    try {
      output = component(props)
    } finally {
      current = null
    }
    instance.rendering = true
    try {
      // Effects run after render, like React's commit phase.
      instance.pending.forEach((run) => run())
    } finally {
      instance.rendering = false
    }
  }

  instance.flush = () => {
    if (instance.rendering) return // the loop below picks up the dirty flag
    let guard = 0
    while (instance.dirty && instance.mounted) {
      if (++guard > 50) throw new Error('Render loop did not settle')
      instance.dirty = false
      renderOnce()
    }
  }

  instance.dirty = true
  instance.flush()

  const buttons = () =>
    findAll(output, (element) => element.type === 'button').map((element) => ({
      label: textOf(element),
      disabled: Boolean(element.props.disabled),
      onClick: element.props.onClick as (() => void) | undefined,
    }))

  return {
    get output() {
      return output
    },
    get lateStateUpdates() {
      return instance.lateStateUpdates
    },
    text: () => textOf(output),
    buttons: () => buttons().map(({ label, disabled }) => ({ label, disabled })),
    click(label) {
      const button = buttons().find((candidate) => candidate.label.includes(label))
      if (!button) throw new Error(`No button labelled "${label}"`)
      if (button.disabled) return // a disabled button does not fire click
      button.onClick?.()
    },
    rerender(next) {
      props = next
      instance.dirty = true
      instance.flush()
    },
    unmount() {
      instance.mounted = false
      instance.effects.forEach((slot) => slot.cleanup?.())
    },
  }
}

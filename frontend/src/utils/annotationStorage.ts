/**
 * Personal Concept Annotation Storage Utility
 * Manages private, learner-scoped bookmarks and notes without altering canonical curriculum graph data.
 */

export interface PersonalAnnotation {
  conceptId: string;
  isBookmarked: boolean;
  note?: string;
  updatedAt: string;
}

const STORAGE_PREFIX = 'learnsense_concept_annotations_';
const MAX_NOTE_LENGTH = 280;

function getStorageKey(learnerId: string): string {
  return `${STORAGE_PREFIX}${learnerId || 'guest'}`;
}

export const AnnotationStorage = {
  /**
   * Get all personal annotations for a learner.
   */
  getAll(learnerId: string): Record<string, PersonalAnnotation> {
    try {
      const raw = localStorage.getItem(getStorageKey(learnerId));
      if (!raw) return {};
      return JSON.parse(raw) as Record<string, PersonalAnnotation>;
    } catch {
      return {};
    }
  },

  /**
   * Get a specific personal annotation for a concept.
   */
  get(learnerId: string, conceptId: string): PersonalAnnotation | null {
    const all = AnnotationStorage.getAll(learnerId);
    return all[conceptId] || null;
  },

  /**
   * Save or update a personal bookmark/note.
   */
  save(
    learnerId: string,
    conceptId: string,
    data: { isBookmarked?: boolean; note?: string }
  ): PersonalAnnotation {
    const all = AnnotationStorage.getAll(learnerId);
    const existing = all[conceptId] || {
      conceptId,
      isBookmarked: false,
      updatedAt: new Date().toISOString(),
    };

    let cleanedNote = existing.note;
    if (data.note !== undefined) {
      const trimmed = data.note.trim();
      cleanedNote = trimmed.length > 0 ? trimmed.slice(0, MAX_NOTE_LENGTH) : undefined;
    }

    const updated: PersonalAnnotation = {
      conceptId,
      isBookmarked: data.isBookmarked !== undefined ? data.isBookmarked : existing.isBookmarked,
      note: cleanedNote,
      updatedAt: new Date().toISOString(),
    };

    // If completely cleared (not bookmarked and no note), delete entry to conserve storage
    if (!updated.isBookmarked && !updated.note) {
      delete all[conceptId];
    } else {
      all[conceptId] = updated;
    }

    try {
      localStorage.setItem(getStorageKey(learnerId), JSON.stringify(all));
    } catch (e) {
      console.warn('Failed to persist concept annotation to localStorage', e);
    }

    return updated;
  },

  /**
   * Remove personal annotation for a concept.
   */
  remove(learnerId: string, conceptId: string): void {
    const all = AnnotationStorage.getAll(learnerId);
    if (all[conceptId]) {
      delete all[conceptId];
      try {
        localStorage.setItem(getStorageKey(learnerId), JSON.stringify(all));
      } catch (e) {
        console.warn('Failed to update localStorage', e);
      }
    }
  },
};

/**
 * Global cache of concept and topic name mappings so that even if a component
 * does not pass conceptMap explicitly, IDs can still resolve to human-readable names.
 */
let globalConceptNameMap: Record<string, string> = {};

export function registerConceptNameMap(map: Record<string, string>) {
  if (map && typeof map === 'object') {
    globalConceptNameMap = { ...globalConceptNameMap, ...map };
  }
}

export function getConceptDisplayName(
  conceptOrId:
    | string
    | {
        name?: string;
        concept_name?: string;
        canonical_name?: string;
        title?: string;
        concept_id?: string;
        id?: string;
      }
    | null
    | undefined,
  conceptMap?: Record<string, string>
): string {
  if (!conceptOrId) return 'Topic';

  const lookup = (id: string): string | null => {
    if (conceptMap && conceptMap[id]) return conceptMap[id];
    if (globalConceptNameMap[id]) return globalConceptNameMap[id];
    return null;
  };

  if (typeof conceptOrId === 'object') {
    if (conceptOrId.concept_name && !isRawConceptId(conceptOrId.concept_name)) {
      return conceptOrId.concept_name;
    }
    if (conceptOrId.name && !isRawConceptId(conceptOrId.name)) {
      return conceptOrId.name;
    }
    if (conceptOrId.canonical_name && !isRawConceptId(conceptOrId.canonical_name)) {
      return conceptOrId.canonical_name;
    }
    if (conceptOrId.title && !isRawConceptId(conceptOrId.title)) {
      return conceptOrId.title;
    }
    const id = conceptOrId.concept_id || (conceptOrId as any).id;
    if (id) {
      const found = lookup(id);
      if (found) return found;
      return cleanConceptId(id);
    }
  }

  if (typeof conceptOrId === 'string') {
    const found = lookup(conceptOrId);
    if (found) return found;
    return cleanConceptId(conceptOrId);
  }

  return 'Topic';
}

function isRawConceptId(val: string): boolean {
  return /^c_[a-f0-9]{6,}/i.test(val.trim());
}

function cleanConceptId(id: string): string {
  if (isRawConceptId(id)) {
    // If it's pure c_hex without any mapping, use shortened hex identifier rather than repeated generic text
    return `Concept ${id.slice(2, 8).toUpperCase()}`;
  }
  // Convert topic or subheading IDs (e.g. "subheading_01", "topic_limits")
  return id
    .replace(/^c_/i, '')
    .replace(/^topic_/i, 'Topic ')
    .replace(/^subheading_/i, 'Subheading ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}


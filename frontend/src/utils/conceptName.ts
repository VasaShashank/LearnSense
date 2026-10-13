/**
 * Utility to resolve human-readable topic names from concept IDs or concept objects.
 * Guarantees that raw concept IDs (e.g. "c_0693846ace40") are NEVER displayed in the UI.
 */

export function getConceptDisplayName(
  conceptOrId:
    | string
    | {
        name?: string;
        concept_name?: string;
        canonical_name?: string;
        title?: string;
        concept_id?: string;
      }
    | null
    | undefined,
  conceptMap?: Record<string, string>
): string {
  if (!conceptOrId) return 'Topic';

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
    if (conceptOrId.concept_id) {
      if (conceptMap && conceptMap[conceptOrId.concept_id]) {
        return conceptMap[conceptOrId.concept_id];
      }
      return cleanConceptId(conceptOrId.concept_id);
    }
  }

  if (typeof conceptOrId === 'string') {
    if (conceptMap && conceptMap[conceptOrId]) {
      return conceptMap[conceptOrId];
    }
    return cleanConceptId(conceptOrId);
  }

  return 'Topic';
}

function isRawConceptId(val: string): boolean {
  return /^c_[a-f0-9]{6,}/i.test(val.trim());
}

function cleanConceptId(id: string): string {
  if (isRawConceptId(id)) {
    // If it's pure c_hex without any mapping, show clean fallback rather than hexadecimal noise
    return 'Core Concept';
  }
  // Convert snake_case or slug to Title Case
  return id
    .replace(/^c_/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

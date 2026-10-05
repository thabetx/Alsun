// One state object per table row, kept by the front (the server keeps nothing):
//   {id, segments, source_blocks, merged_from?}   <- the same shape the backend uses
//   + originalText, aiEdited, history, mergedSnapshots?, mergedOriginalAtMerge?   <- only the front uses these
export const rowStates = new Map();

export const PLACEHOLDER = "Dummy translation text, to be replaced with the actual translation.";

// What the user sees for a segment. Same rule as paragraph_format.py in the backend:
// the quote marks belong to the quran part, they are never inside segment.text.
export function displayParts(segments) {
  return segments.map((segment) => ({
    id: segment.id,
    type: segment.type,
    text: segment.type === "quran" ? `"${segment.text}"` : segment.text,
  }));
}

// The text of a row as one line: the parts with text, one space between them
// (same as concatenate_paragraph_segements in the backend; a part with no text adds nothing).
export function joinDisplayText(segments) {
  return displayParts(segments)
    .map((part) => part.text)
    .filter(Boolean)
    .join(" ");
}

export function toRawRow(state) {
  const row = { id: state.id, segments: state.segments, source_blocks: state.source_blocks };
  if (state.merged_from) row.merged_from = state.merged_from;
  return row;
}

export function copy(value) {
  return JSON.parse(JSON.stringify(value));
}

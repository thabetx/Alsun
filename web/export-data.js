import { rowStates } from "./state.js";
import { getAllRows } from "./selection.js";

// The rows that exist NOW, in the order of the table. The final extraction must read from here:
// a deleted row is removed from the table and from the state, so it can't be in this list.
export function collectRowsForExtraction() {
  return getAllRows().map((tr) => {
    const state = rowStates.get(tr.dataset.id);
    return {
      id: state.id,
      original_text: state.originalText,
      segments: state.segments,
      source_blocks: state.source_blocks,
    };
  });
}

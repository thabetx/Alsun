import { rowStates, displayParts } from "./state.js";
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
      liveParts: livePartsOf(tr),
    };
  });
}

// What the user is typing in a cell right now, as display parts. The text he writes only reaches
// the segments when the cell loses the focus, and the live preview must not wait for that.
// Only the preview reads it: a download reads the segments, which the click has already updated.
function livePartsOf(tr) {
  const cell = tr.querySelector(".translated-text");
  if (!cell || document.activeElement !== cell) return null;
  // The cell is drawn as one .seg span per part. What the user types goes inside those spans, and
  // between them when he types where there was no part at all; both are read, in the order they
  // are drawn, so the preview shows what is on the screen. The text is read as text, never as
  // html, so nothing typed or pasted in the cell can become markup.
  const parts = [];
  [...cell.childNodes].forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent.replace(/\s+/g, " ");
      if (text.trim()) parts.push({ id: liveId(parts), type: "normal", text });
    } else if (node.classList && node.classList.contains("seg")) {
      parts.push({
        id: node.dataset.segId || liveId(parts),
        type: node.classList.contains("seg-quran") ? "quran" : "normal",
        text: node.textContent,
      });
    }
  });
  return displayParts(parts);
}

const liveId = (parts) => `live_${parts.length + 1}`;

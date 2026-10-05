import { postJson } from "./api.js";
import { rowStates } from "./state.js";
import { renderOriginalHighlights, toHighlightSegments } from "./translated-view.js";
import { showToast } from "./toast.js";

// how many rows are asked at the same time when a whole book is marked on load. the detector
// is one matcher shared by the server, so this mostly hides the round trip, not the work
const PARALLEL_DETECTIONS = 6;

// Marks the ayas of every row as soon as the book is loaded. The ocr text is already fixed
// by the llm on the server (see python/ocr.py), so the only thing left to do is this, and it
// costs nothing: no llm, no translation, only the marks in the original text.
export async function detectAyahsInRows(trs) {
  const queue = [...trs];
  if (!queue.length) return;

  // the rows waiting for their answer are dimmed, so the pass is visible while it runs
  queue.forEach((tr) => tr.classList.add("is-busy"));

  const worker = async () => {
    for (let tr = queue.shift(); tr; tr = queue.shift()) {
      try {
        await markAyahsInRow(tr);
      } finally {
        tr.classList.remove("is-busy");
      }
    }
  };

  await Promise.all(Array.from({ length: Math.min(PARALLEL_DETECTIONS, queue.length) }, worker));
}

// Finds the ayas of one row without translating it: the segments come straight from the
// detector, so the translation of the row is not touched. Only the marks in the original
// text change. There is no toast about the result: this runs for every row of the book at
// once, and a toast per row would bury the screen.
async function markAyahsInRow(tr) {
  const rowId = tr.dataset.id;
  const original = tr.querySelector(".original-text");
  const text = original.textContent.trim();
  if (!text) return;

  try {
    const data = await postJson("/detect-ayas", { text });

    // the row was deleted, or its text changed: the answer is about a text that is not there anymore
    if (!rowStates.has(rowId) || original.textContent.trim() !== text || !document.contains(tr)) return;

    // the detector gives the arabic as "text"; the marks are drawn from "original" like a translation
    renderOriginalHighlights(tr, toHighlightSegments(data.segments));
  } catch (error) {
    showToast(error.message, true);
  }
}
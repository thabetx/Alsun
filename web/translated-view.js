import { rowStates, displayParts, PLACEHOLDER } from "./state.js";
import { showToast } from "./toast.js";
import { finishTyping, typeTranslation } from "./pen-writer.js";
import { rebuildSegmentsFromCell, EDIT_REFUSED_MESSAGE, AYAH_DELETED_MESSAGE } from "./segment-sync.js";

// Draws the translation of a row from its segments: one <span> per segment (id + type),
// so a selection can be matched to a segment without counting characters in the whole text.
// A quran span is not editable, so the quran can't be changed by hand.
export function renderTranslated(tr, { animate = false } = {}) {
  finishTyping(tr);
  const state = rowStates.get(tr.dataset.id);
  const cell = tr.querySelector(".translated-text");
  cell.replaceChildren();

  // nothing to edit before the row is translated: the cell only tells the user what to do
  cell.contentEditable = state.segments.length ? "true" : "false";
  if (!state.segments.length) {
    const hint = document.createElement("span");
    hint.className = "translated-hint";
    hint.textContent = PLACEHOLDER;
    cell.append(hint);
  }
  let somethingBefore = false;
  displayParts(state.segments).forEach((part, index) => {
    // one space between two parts with text; a part with no text (a deleted ayah) is there but adds no space
    if (part.text && somethingBefore) cell.append(" ");
    const segment = state.segments[index];
    const span = document.createElement("span");
    span.className = `seg seg-${part.type}`;
    span.dataset.segId = part.id;
    span.textContent = part.text;
    if (part.type === "quran") span.contentEditable = "false";
    // text the user wrote where an ayah was: marked, so it is clear it is not the translation of the ayah
    if (segment.replaced_quran?.length) {
      span.classList.add("seg-replaced");
      span.title = `نص كتبه المستخدم بدل ترجمة آية: ${segment.replaced_quran.map(describeAyahRange).join("، ")}`;
    }
    cell.append(span);
    if (part.text) somethingBefore = true;
  });

  tr.querySelector(".ai-chip").hidden = !state.aiEdited;
  tr.querySelector(".merged-only").hidden = !state.merged_from;
  tr.classList.toggle("is-merged", Boolean(state.merged_from));
  renderOriginalHighlights(tr);
  // only for a fresh translation (not for the assistant, undo or merge)
  if (animate) typeTranslation(tr);
}

function describeAyahRange(segment) {
  const range = segment.aya_end !== segment.aya_start ? `${segment.aya_start}-${segment.aya_end}` : `${segment.aya_start}`;
  return `${segment.aya_name} (${range})`;
}


// The detector answers with the arabic in "text", but the marks in the original text are drawn
// from "original" like the segments of a translation, and they need an id. Used by the actions
// that find the ayahs without translating (the row menu and the ocr refinement).
export function toHighlightSegments(segments) {
  return segments.map((segment, index) => ({ ...segment, id: `seg_${index + 1}`, original: segment.text }));
}

// Marks in the ORIGINAL text what the detector took as quran, so a wrong detection is visible.
// The text itself is not changed (same characters, same spaces), only wrapped in spans.
// The segments to draw are the ones of the translation by default; the "detect ayas" action
// passes its own, since it detects without translating.
// If the words of the cell don't match the words the segments came from (the user changed the
// text after the translation), nothing is marked: a wrong mark is worse than no mark.
export function renderOriginalHighlights(tr, segments = rowStates.get(tr.dataset.id).segments) {
  const cell = tr.querySelector(".original-text");
  const text = cell.textContent;
  cell.replaceChildren(text);
  if (!segments.length) return;

  const cellWords = [...text.matchAll(/\S+/g)].map((match) => ({
    word: match[0],
    start: match.index,
    end: match.index + match[0].length,
  }));
  const segmentWords = segments.map((segment) => segment.original.split(/\s+/).filter(Boolean));
  const allSegmentWords = segmentWords.flat();
  const sameWords =
    allSegmentWords.length === cellWords.length &&
    allSegmentWords.every((word, index) => word === cellWords[index].word);
  if (!sameWords) return;

  const pieces = [];
  let cursor = 0;
  let wordNumber = 0;
  segments.forEach((segment, index) => {
    const count = segmentWords[index].length;
    if (segment.type === "quran" && count > 0) {
      const start = cellWords[wordNumber].start;
      const end = cellWords[wordNumber + count - 1].end;
      pieces.push(text.slice(cursor, start));
      const span = document.createElement("span");
      span.className = "orig-quran";
      span.title = describeAyahRange(segment);
      span.textContent = text.slice(start, end);
      pieces.push(span);
      cursor = end;
    }
    wordNumber += count;
  });
  pieces.push(text.slice(cursor));
  cell.replaceChildren(...pieces);
}

// Copies what the user typed in the cell back to the segments (see segment-sync.js for the rules).
export function syncRowFromDom(tr) {
  finishTyping(tr); // never read a half written text
  const state = rowStates.get(tr.dataset.id);
  if (!state.segments.length) return;

  const rebuilt = rebuildSegmentsFromCell(state.segments, tr.querySelector(".translated-text"));
  if (rebuilt.refused) {
    renderTranslated(tr); // the ayah goes back to what we wrote
    showToast(EDIT_REFUSED_MESSAGE, true);
    return;
  }

  state.segments = rebuilt.segments;
  if (rebuilt.changedStructure) {
    // an ayah was deleted or text was typed outside the parts: draw the cell again from the segments
    renderTranslated(tr);
    if (rebuilt.deletedAyahs) showToast(AYAH_DELETED_MESSAGE);
  }
}

function describeAyah(ayah) {
  const range = ayah.aya_end !== ayah.aya_start ? `${ayah.aya_start}-${ayah.aya_end}` : `${ayah.aya_start}`;
  return `${ayah.aya_name} (${range})`;
}

// Tells the user what happened to the ayahs after he changed the original text.
export function showReviewNote(tr, quranChanges, onRestore) {
  removeReviewNote(tr);

  const lines = [
    ...quranChanges.removed.map((ayah) => `آية محذوفة: ${describeAyah(ayah)}`),
    ...quranChanges.added.map((ayah) => `آية مضافة: ${describeAyah(ayah)}`),
    ...quranChanges.damaged.map(
      (ayah) => `كانت هنا آية ولم يعد النظام يتعرّف عليها (ربما خطأ إملائي): ${describeAyah(ayah)}`
    ),
  ];

  const note = document.createElement("div");
  note.className = "review-note";
  note.innerHTML = '<strong>يحتاج مراجعة بعد تعديل النص الأصلي</strong><ul></ul>' +
    '<button type="button" class="review-restore">استعادة النسخة السابقة</button>' +
    '<button type="button" class="review-dismiss">إغلاق</button>';
  const list = note.querySelector("ul");
  lines.forEach((line) => {
    const item = document.createElement("li");
    item.textContent = line;
    list.append(item);
  });
  note.querySelector(".review-restore").addEventListener("click", (event) => {
    event.stopPropagation();
    onRestore();
  });
  note.querySelector(".review-dismiss").addEventListener("click", (event) => {
    event.stopPropagation();
    note.remove();
  });
  tr.querySelector(".translated-cell").append(note);
}

export function removeReviewNote(tr) {
  tr.querySelector(".review-note")?.remove();
}

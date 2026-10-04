import { rowStates, displayParts, PLACEHOLDER } from "./state.js";
import { showToast } from "./toast.js";

// Draws the translation of a row from its segments: one <span> per segment (id + type),
// so a selection can be matched to a segment without counting characters in the whole text.
// A quran span is not editable, so the quran can't be changed by hand.
export function renderTranslated(tr) {
  const state = rowStates.get(tr.dataset.id);
  const cell = tr.querySelector(".translated-text");
  cell.replaceChildren();

  if (!state.segments.length) {
    cell.textContent = PLACEHOLDER;
  }
  displayParts(state.segments).forEach((part, index) => {
    if (index > 0) cell.append(" ");
    const span = document.createElement("span");
    span.className = `seg seg-${part.type}`;
    span.dataset.segId = part.id;
    span.textContent = part.text;
    if (part.type === "quran") span.contentEditable = "false";
    cell.append(span);
  });

  tr.querySelector(".ai-chip").hidden = !state.aiEdited;
  tr.querySelector(".merged-only").hidden = !state.merged_from;
  tr.classList.toggle("is-merged", Boolean(state.merged_from));
}

// Copies what the user typed in the normal spans back to the segments.
// If a quran span was deleted or changed, the row is drawn again from the segments.
export function syncRowFromDom(tr) {
  const state = rowStates.get(tr.dataset.id);
  if (!state.segments.length) return;

  const spans = new Map(
    [...tr.querySelectorAll(".translated-text .seg")].map((span) => [span.dataset.segId, span])
  );
  const quranBroken = state.segments.some((segment) => {
    if (segment.type !== "quran") return false;
    const span = spans.get(segment.id);
    return !span || span.textContent !== `"${segment.text}"`;
  });
  if (quranBroken) {
    renderTranslated(tr);
    showToast("الآيات لا يمكن تعديلها أو حذفها", true);
    return;
  }

  state.segments = state.segments.map((segment) =>
    segment.type === "normal"
      ? { ...segment, text: spans.has(segment.id) ? spans.get(segment.id).textContent : "" }
      : segment
  );
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

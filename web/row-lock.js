import { rowStates } from "./state.js";
import { showToast } from "./toast.js";
import { syncRowFromDom } from "./translated-view.js";

// The lock of a row: the user marks a row he finished, and nothing changes it until he opens the lock.
// It is a flag in the state of the row (state.locked), so it is saved with the rest of the work.
// What a locked row refuses (see the places that call isLocked): typing in both cells, translating again,
// the assistant, merging / unmerging, deleting, and the change of the quran translation.

export const LOCKED_MESSAGE = "هذا الصف مقفل. افتح القفل أولًا إن أردت تعديله.";

export const isLocked = (rowId) => Boolean(rowStates.get(rowId)?.locked);

// Draws the lock on the row from its state: the look, the button, and whether the cells can be typed in.
export function applyLock(tr) {
  const state = rowStates.get(tr.dataset.id);
  const locked = Boolean(state?.locked);

  tr.classList.toggle("is-locked", locked);
  // an attribute change is what the saving of the work watches (see saved-work.js)
  if (locked) tr.dataset.locked = "true";
  else delete tr.dataset.locked;

  const original = tr.querySelector(".original-text");
  const translated = tr.querySelector(".translated-text");
  original.contentEditable = locked ? "false" : "true";
  // a row that is not translated yet has nothing to type in (renderTranslated says the same)
  translated.contentEditable = !locked && state?.segments.length ? "true" : "false";

  const button = tr.querySelector(".lock-btn");
  if (button) {
    button.setAttribute("aria-pressed", String(locked));
    button.setAttribute("aria-label", locked ? "إلغاء علامة الانتهاء وفتح الصف" : "علّم الصف كمنتهٍ واقفله");
    button.title = locked ? "منتهٍ ومقفل، اضغط لإلغاء العلامة وفتح الصف" : "علّم الصف كمنتهٍ (يُقفل حتى لا يتغيّر)";
    button.firstElementChild.className = locked ? "fa-solid fa-check-double" : "fa-solid fa-check";
  }
}

export function toggleLock(tr) {
  const state = rowStates.get(tr.dataset.id);
  if (!state) return;
  if (!state.locked) {
    if (state.translating) return showToast("انتظر حتى تنتهي ترجمة الصف ثم اقفله", true);
    syncRowFromDom(tr); // what was typed and not left yet goes into the state before it is locked
  }
  state.locked = !state.locked;
  applyLock(tr);
  showToast(state.locked ? "تم تعليم الصف كمنتهٍ وقفله" : "تم إلغاء العلامة وفتح الصف");
  document.dispatchEvent(new CustomEvent("row-lock-changed")); // the buttons of the toolbar depend on it
}

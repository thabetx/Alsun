import { postJson } from "./api.js";
import { rowStates } from "./state.js";
import { renderTranslated } from "./translated-view.js";
import { beginLoading } from "./loading-overlay.js";
import { showToast } from "./toast.js";
import { LOCKED_MESSAGE } from "./row-lock.js";
import { targetLanguage } from "./target-language.js";
import { getGlossary, notAppliedTerms, notAppliedMessage } from "./glossary-store.js";
import { translationSettings } from "./settings-store.js";
import { fallbackMessage } from "./model-notice.js";

// Translates one row: "done", "error" or "skipped" (nothing to translate, already being translated,
// or the user changed the row while it was waiting, so the answer is thrown away).
// quiet = no toast ("translate all" writes one summary), onFallback(fallbacks) = told when another model answered
export async function translateRow(tr, { quiet = false, onFallback = null } = {}) {
  const rowId = tr.dataset.id;
  const state = rowStates.get(rowId);
  const original = tr.querySelector(".original-text");
  const text = original.textContent.trim();
  if (state.locked) {
    if (!quiet) showToast(LOCKED_MESSAGE, true);
    return "skipped";
  }
  if (!text || state.translating) return "skipped";

  state.translating = true;
  // the whole page shows the loading (the row keeps what it had until the new translation arrives)
  const stopLoading = beginLoading({ message: "جارٍ ترجمة الصف…" });
  try {
    const language = targetLanguage();
    const data = await postJson("/translate", {
      text, target_lang: language, glossary: getGlossary(language), ...translationSettings(language),
    });
    stopLoading();

    // the row was deleted while we waited
    if (!rowStates.has(rowId)) return "skipped";

    // the original was changed while we waited: this translation is of an old text
    if (original.textContent.trim() !== text || !document.contains(tr)) {
      renderTranslated(tr);
      return "skipped";
    }

    // keep the segments: they tell us what is quran and what is normal text
    state.segments = data.segments;
    state.originalText = text;
    state.aiEdited = false;
    renderTranslated(tr, { animate: true });
    // the backend asked the model for the terms of the glossary; tell the user about the ones it did not use
    const notApplied = notAppliedTerms(state.segments);
    if (data.fallbacks?.length) onFallback?.(data.fallbacks);
    if (!quiet) {
      const notes = [
        data.fallbacks?.length ? fallbackMessage(data.fallbacks) : "",
        notApplied.length ? notAppliedMessage(notApplied) : "",
      ].filter(Boolean);
      if (notes.length) showToast(notes.join(" "), notApplied.length > 0);
    }
    return "done";
  } catch (error) {
    stopLoading();
    if (rowStates.has(rowId)) renderTranslated(tr);
    showToast(error.message, true);
    return "error";
  } finally {
    state.translating = false;
  }
}

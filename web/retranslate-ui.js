import { postJson } from "./api.js";
import { rowStates } from "./state.js";
import { renderTranslated, syncRowFromDom, showReviewNote, removeReviewNote } from "./translated-view.js";
import { showToast } from "./toast.js";
import { beginLoading } from "./loading-overlay.js";
import { askConfirmation } from "./confirm-dialog.js";
import { targetLanguage } from "./target-language.js";
import { getGlossary, notAppliedTerms, notAppliedMessage } from "./glossary-store.js";
import { translationSettings } from "./settings-store.js";
import { fallbackMessage } from "./model-notice.js";

const CONFIRM_MESSAGE =
  "تعديل النص الأصلي سيعيد ترجمة هذا الصف، وستضيع تعديلاتك على الترجمة. " +
  "يمكنك استعادة النسخة السابقة بعد ذلك.";

// Called when the user leaves the original text of a row.
export async function handleOriginalEdited(tr, editedText) {
  const state = rowStates.get(tr.dataset.id);
  const original = tr.querySelector(".original-text");
  const newText = editedText.trim();
  if (newText === state.originalText) return;

  // nothing translated yet, so there is nothing to translate again
  if (!state.segments.length) {
    state.originalText = newText;
    return;
  }

  const confirmed = await askConfirmation({
    title: "إعادة ترجمة الصف",
    message: CONFIRM_MESSAGE,
    confirmLabel: "أعد الترجمة",
    icon: "fa-triangle-exclamation",
  });
  if (!confirmed) {
    original.textContent = state.originalText;
    return;
  }

  syncRowFromDom(tr);
  const previous = { segments: state.segments, originalText: state.originalText, aiEdited: state.aiEdited };
  tr.querySelector(".translated-text").replaceChildren();
  const stopLoading = beginLoading({ message: "جارٍ إعادة ترجمة الصف…" });

  try {
    const data = await postJson("/retranslate", {
      old_segments: state.segments, new_original_text: newText, target_lang: targetLanguage(),
      glossary: getGlossary(targetLanguage()), ...translationSettings(targetLanguage()),
    });
    stopLoading();
    if (!rowStates.has(tr.dataset.id)) return; // deleted while we waited
    if (data.fallbacks?.length) showToast(fallbackMessage(data.fallbacks));
    state.segments = data.segments;
    state.originalText = newText;
    state.aiEdited = false;
    renderTranslated(tr, { animate: true });
    removeReviewNote(tr);

    if (data.needs_review) {
      showReviewNote(tr, data.quran_changes, () => {
        state.segments = previous.segments;
        state.originalText = previous.originalText;
        state.aiEdited = previous.aiEdited;
        original.textContent = previous.originalText;
        renderTranslated(tr);
        removeReviewNote(tr);
      });
    }
  } catch (error) {
    stopLoading();
    if (!rowStates.has(tr.dataset.id)) return;
    state.segments = previous.segments;
    original.textContent = state.originalText;
    renderTranslated(tr);
    showToast(error.message, true);
  }
}

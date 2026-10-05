import { rowStates, displayParts } from "./state.js";
import { askConfirmation } from "./confirm-dialog.js";
import { showToast } from "./toast.js";
import { translateRow } from "./translate-ui.js";
import { askAssistantAboutRow } from "./assistant.js";
import { mergeRowsNow, explainNeighborMergeProblem, unmergeRow } from "./merge-ui.js";

// The menu of a row (the three dots). Delete is handled in app.js, it needs the pdf side too.

// Ready instructions for the assistant: the label is what the user sees, the instruction is what the model gets.
const ASSISTANT_SHORTCUTS = [
  { action: "assistant-summarize", label: "تلخيص", instructions: "Summarize this text in a few sentences, keeping its main meaning." },
  { action: "assistant-simplify", label: "تبسيط", instructions: "Simplify the language so it is easy to read, keeping the meaning." },
  { action: "assistant-formal", label: "صياغة رسمية", instructions: "Rewrite this text in a formal academic tone, keeping the meaning." },
];

export function rowMenuMarkup() {
  const shortcuts = ASSISTANT_SHORTCUTS.map(
    ({ action, label }) =>
      `<li><button class="dropdown-item" type="button" data-action="${action}">${label}</button></li>`
  ).join("\n            ");

  return `
            <li><button class="dropdown-item" type="button" data-action="translate">ترجمة</button></li>
            <li><hr class="dropdown-divider"></li>
            <li><h6 class="dropdown-header">اسأل المساعد الذكي</h6></li>
            ${shortcuts}
            <li><hr class="dropdown-divider"></li>
            <li><button class="dropdown-item" type="button" data-action="copy-translation">نسخ الترجمة</button></li>
            <li><button class="dropdown-item" type="button" data-action="copy-original">نسخ الأصل</button></li>
            <li><hr class="dropdown-divider"></li>
            <li><button class="dropdown-item" type="button" data-action="merge-next">دمج مع الصف التالي</button></li>
            <li class="merged-only" hidden><button class="dropdown-item" type="button" data-action="unmerge">فك الدمج</button></li>
            <li><hr class="dropdown-divider"></li>
            <li><button class="dropdown-item text-danger" type="button" data-action="delete">حذف</button></li>`;
}

// Called when the menu opens: the items show what is possible for this row now.
// The reason of a disabled item is the tooltip of its <li> (a disabled button gets no mouse events).
export function refreshRowMenu(tr) {
  const state = rowStates.get(tr.dataset.id);
  const translated = state.segments.length > 0;
  const hasOriginal = tr.querySelector(".original-text").textContent.trim().length > 0;
  const busy = Boolean(state.translating);

  const setItem = (action, { label, disabledReason = "" } = {}) => {
    const button = tr.querySelector(`[data-action="${action}"]`);
    if (label) button.textContent = label;
    button.disabled = Boolean(disabledReason);
    button.closest("li").title = disabledReason;
  };

  setItem("translate", {
    label: translated ? "إعادة الترجمة" : "ترجمة",
    disabledReason: busy ? "جارٍ الترجمة" : hasOriginal ? "" : "لا يوجد نص أصلي لترجمته",
  });

  const needsTranslation = busy ? "جارٍ الترجمة" : translated ? "" : "ترجم الصف أولاً";
  ASSISTANT_SHORTCUTS.forEach(({ action }) => setItem(action, { disabledReason: needsTranslation }));
  setItem("copy-translation", { disabledReason: needsTranslation });
  setItem("copy-original", { disabledReason: hasOriginal ? "" : "لا يوجد نص أصلي" });

  setItem("merge-next", { disabledReason: explainNeighborMergeProblem(tr, "next").problem ?? "" });
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (error) {
    // no permission or no focus: the old way
    const box = document.createElement("textarea");
    box.value = text;
    box.style.cssText = "position:fixed; opacity:0;";
    document.body.append(box);
    box.select();
    const copied = document.execCommand("copy");
    box.remove();
    if (!copied) throw new Error("تعذّر النسخ");
  }
}

async function retranslateAfterAsking(tr) {
  const state = rowStates.get(tr.dataset.id);
  // nothing to lose yet
  if (!state.segments.length) return translateRow(tr);

  const confirmed = await askConfirmation({
    title: "إعادة الترجمة",
    message: "ستُستبدل الترجمة الحالية بترجمة جديدة، وتضيع أي تعديلات عليها سواء يدوية أو من المساعد.",
    confirmLabel: "أعد الترجمة",
    icon: "fa-triangle-exclamation",
  });
  if (confirmed && rowStates.has(tr.dataset.id)) translateRow(tr);
}

// Runs the action of a menu item. Returns false if it isn't one of ours (app.js handles it).
export async function runRowMenuAction(tr, action) {
  const state = rowStates.get(tr.dataset.id);

  if (action === "translate") return retranslateAfterAsking(tr);

  const shortcut = ASSISTANT_SHORTCUTS.find((item) => item.action === action);
  if (shortcut) return askAssistantAboutRow(tr, shortcut.label, shortcut.instructions);

  if (action === "copy-translation") {
    const text = displayParts(state.segments).map((part) => part.text).join(" ");
    try {
      await copyToClipboard(text);
      showToast("تم نسخ الترجمة");
    } catch (error) {
      showToast(error.message, true);
    }
    return;
  }
  if (action === "copy-original") {
    try {
      await copyToClipboard(tr.querySelector(".original-text").textContent.trim());
      showToast("تم نسخ النص الأصلي");
    } catch (error) {
      showToast(error.message, true);
    }
    return;
  }

  if (action === "merge-next") {
    const { neighbor, problem } = explainNeighborMergeProblem(tr, "next");
    if (problem) return showToast(problem, true);
    return mergeRowsNow([tr, neighbor]);
  }

  if (action === "unmerge") return unmergeRow(tr);

  return false;
}

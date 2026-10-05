import { rowStates } from "./state.js";
import { notAppliedTerms } from "./glossary-store.js";
import { fallbackMessage } from "./model-notice.js";
import { getAllRows, getSelectedRows } from "./selection.js";
import { translateRow } from "./translate-ui.js";
import { showToast } from "./toast.js";
import { askConfirmation } from "./confirm-dialog.js";
import { beginLoading, setLoadingProgress } from "./loading-overlay.js";

const MAX_ERRORS_IN_A_ROW = 3; // a wrong key or a limit would otherwise fail every row

let running = false;
let stopRequested = false;

const button = () => document.getElementById("translate-all");

function needsTranslation(tr) {
  const state = rowStates.get(tr.dataset.id);
  return state && !state.segments.length && !state.translating && tr.querySelector(".original-text").textContent.trim();
}

function showIdle() {
  button().innerHTML = '<i class="fa-solid fa-language"></i> ترجمة الكل';
  button().title = "ترجمة الصفوف غير المترجمة واحدًا تلو الآخر";
}

function showProgress(done, total) {
  button().innerHTML = `<i class="fa-solid fa-stop"></i> إيقاف (${done}/${total})`;
  button().title = "إيقاف الترجمة بعد الصف الحالي";
  setLoadingProgress(`${done} من ${total}`);
}

function requestStop() {
  stopRequested = true;
  button().title = "جارٍ الإيقاف...";
}

// one row at a time; every await gives the browser back, so the page stays usable
async function translateAll() {
  // the checked rows if there are any, otherwise all the rows that are not translated yet
  const checked = getSelectedRows();
  const rows = (checked.length ? checked : getAllRows()).filter(needsTranslation);
  if (!rows.length) return showToast("لا توجد صفوف تحتاج إلى ترجمة");
  const confirmed = await askConfirmation({
    title: "ترجمة الصفوف",
    message: `سيتم ترجمة ${rows.length} صفًا واحدًا تلو الآخر، ويمكنك إيقاف العملية في أي وقت.`,
    confirmLabel: "ابدأ الترجمة",
    icon: "fa-language",
  });
  if (!confirmed) return;

  running = true;
  stopRequested = false;
  let done = 0;
  let errorsInARow = 0;
  let translated = 0;
  let glossaryMissed = 0; // terms of the glossary the model did not use
  let fallbackRows = 0; // rows another model answered
  let lastFallbacks = null;
  let stoppedByErrors = false;
  // the page is covered by the loading until the last row is translated (or the user stops it)
  const endLoading = beginLoading({ message: "جارٍ ترجمة الصفوف…", onStop: requestStop });
  showProgress(done, rows.length);

  for (const tr of rows) {
    if (stopRequested) break;
    if (!document.contains(tr) || !needsTranslation(tr)) {
      // merged, removed or translated by hand meanwhile
      done++;
      showProgress(done, rows.length);
      continue;
    }

    tr.scrollIntoView({ block: "center", behavior: "smooth" }); // so the translation is written in front of the user
    const result = await translateRow(tr, {
      quiet: true,
      onFallback: (fallbacks) => { fallbackRows++; lastFallbacks = fallbacks; },
    });
    done++;
    showProgress(done, rows.length);
    if (result === "done") {
      translated++;
      glossaryMissed += notAppliedTerms(rowStates.get(tr.dataset.id).segments).length;
    }
    errorsInARow = result === "error" ? errorsInARow + 1 : 0;
    if (errorsInARow >= MAX_ERRORS_IN_A_ROW) {
      stoppedByErrors = true;
      break;
    }
  }

  endLoading();
  const stopped = stopRequested;
  running = false;
  stopRequested = false;
  showIdle();
  if (stoppedByErrors) {
    showToast(`توقفت الترجمة بعد ${MAX_ERRORS_IN_A_ROW} أخطاء متتالية (تمت ترجمة ${translated} صفًا)`, true);
    return;
  }
  const summary = stopped ? `تم الإيقاف بعد ترجمة ${translated} صفًا` : `تمت ترجمة ${translated} صفًا`;
  const notes = [
    fallbackRows ? `${fallbackMessage(lastFallbacks)} (في ${fallbackRows} صف)` : "",
    glossaryMissed ? `لم تُطبَّق ${glossaryMissed} من مصطلحات قاموسك، راجعها يدويًا.` : "",
  ].filter(Boolean);
  showToast(notes.length ? `${summary}. ${notes.join(" ")}` : summary, glossaryMissed > 0);
}

export function initTranslateAll() {
  button().addEventListener("click", () => {
    if (running) {
      requestStop();
    } else {
      translateAll();
    }
  });
}

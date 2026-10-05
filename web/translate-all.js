import { rowStates } from "./state.js";
import { getAllRows, getSelectedRows } from "./selection.js";
import { translateRow } from "./translate-ui.js";
import { showToast } from "./toast.js";

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
}

// one row at a time; every await gives the browser back, so the page stays usable
async function translateAll() {
  // the checked rows if there are any, otherwise all the rows that are not translated yet
  const checked = getSelectedRows();
  const rows = (checked.length ? checked : getAllRows()).filter(needsTranslation);
  if (!rows.length) return showToast("لا توجد صفوف تحتاج إلى ترجمة");
  if (!window.confirm(`سيتم ترجمة ${rows.length} صفًا. هل تريد المتابعة؟`)) return;

  running = true;
  stopRequested = false;
  let done = 0;
  let errorsInARow = 0;
  let translated = 0;
  let stoppedByErrors = false;
  showProgress(done, rows.length);

  for (const tr of rows) {
    if (stopRequested) break;
    if (!document.contains(tr) || !needsTranslation(tr)) {
      // merged, removed or translated by hand meanwhile
      done++;
      showProgress(done, rows.length);
      continue;
    }

    const result = await translateRow(tr);
    done++;
    showProgress(done, rows.length);
    if (result === "done") translated++;
    errorsInARow = result === "error" ? errorsInARow + 1 : 0;
    if (errorsInARow >= MAX_ERRORS_IN_A_ROW) {
      stoppedByErrors = true;
      break;
    }
  }

  const stopped = stopRequested;
  running = false;
  stopRequested = false;
  showIdle();
  if (stoppedByErrors) {
    showToast(`توقفت الترجمة بعد ${MAX_ERRORS_IN_A_ROW} أخطاء متتالية (تمت ترجمة ${translated} صفًا)`, true);
    return;
  }
  showToast(stopped ? `تم الإيقاف بعد ترجمة ${translated} صفًا` : `تمت ترجمة ${translated} صفًا`);
}

export function initTranslateAll() {
  button().addEventListener("click", () => {
    if (running) {
      stopRequested = true;
      button().title = "جارٍ الإيقاف...";
    } else {
      translateAll();
    }
  });
}

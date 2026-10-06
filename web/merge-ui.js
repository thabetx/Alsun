import { postJson, translateError } from "./api.js";
import { rowStates, toRawRow, copy } from "./state.js";
import { syncRowFromDom } from "./translated-view.js";
import { getAllRows, getSelectedRows } from "./selection.js";
import { showToast } from "./toast.js";
import { isLocked, LOCKED_MESSAGE } from "./row-lock.js";

// app.js gives us the one function we need from it: replaceRows(oldRows, newStates)
let replaceRows = null;
let checkNumber = 0;

const originalTextOf = (tr) => tr.querySelector(".original-text").textContent.trim();

// The server only needs the ids and the order of the rows that are not selected.
function buildRowsForServer(selectedIds) {
  return getAllRows().map((tr) =>
    selectedIds.includes(tr.dataset.id)
      ? toRawRow(rowStates.get(tr.dataset.id))
      : { id: tr.dataset.id, segments: [], source_blocks: [] }
  );
}

export async function refreshMergeButton() {
  const button = document.getElementById("merge-rows");
  const thisCheck = ++checkNumber;
  const setState = (enabled, title) => {
    button.disabled = !enabled;
    button.title = title;
  };

  const rows = getSelectedRows();
  if (rows.length < 2) return setState(false, "حدّد صفين متجاورين على الأقل للدمج");

  // a merged row can't be half translated
  const translatedCount = rows.filter((tr) => rowStates.get(tr.dataset.id).segments.length).length;
  if (translatedCount && translatedCount < rows.length) {
    return setState(false, "ترجم كل الصفوف المحددة أولاً، أو ادمجها قبل الترجمة");
  }

  const ids = rows.map((tr) => tr.dataset.id);
  try {
    const { problem } = await postJson("/rows/merge-problem", {
      rows: buildRowsForServer([]),
      selected_row_ids: ids,
    });
    if (thisCheck !== checkNumber) return;
    setState(!problem, problem ? translateError(problem) : "دمج الصفوف المحددة في صف واحد");
  } catch (error) {
    if (thisCheck === checkNumber) setState(false, error.message);
  }
}

// The row before / after this one, and why they can't be merged (null = they can).
// They are next to each other by definition, so only the other rules are left.
export function explainNeighborMergeProblem(tr, direction) {
  const neighbor = direction === "previous" ? tr.previousElementSibling : tr.nextElementSibling;
  if (!neighbor || !neighbor.classList.contains("block-row")) {
    return { neighbor: null, problem: direction === "previous" ? "هذا هو الصف الأول" : "هذا هو الصف الأخير" };
  }
  if (neighbor.style.display === "none") {
    return { neighbor, problem: "الصف المجاور مخفي بنتيجة البحث" };
  }
  if (isLocked(tr.dataset.id) || isLocked(neighbor.dataset.id)) {
    return { neighbor, problem: "افتح قفل الصف أولًا" };
  }
  const translated = [tr, neighbor].map((row) => rowStates.get(row.dataset.id).segments.length > 0);
  if (translated[0] !== translated[1]) {
    return { neighbor, problem: "ترجم الصفين أولاً، أو ادمجهما قبل الترجمة" };
  }
  return { neighbor, problem: null };
}

async function mergeSelectedRows() {
  return mergeRowsNow(getSelectedRows());
}

// rows = the rows to merge, next to each other, in the order of the table
export async function mergeRowsNow(rows) {
  if (rows.some((tr) => isLocked(tr.dataset.id))) return showToast(LOCKED_MESSAGE, true);
  const ids = rows.map((tr) => tr.dataset.id);
  rows.forEach(syncRowFromDom);

  try {
    const { row } = await postJson("/rows/merge", {
      rows: buildRowsForServer(ids),
      selected_row_ids: ids,
    });

    // what each row looked like, to bring it back when the merge is undone
    const snapshots = rows.map((tr) => ({ ...copy(rowStates.get(tr.dataset.id)), originalText: originalTextOf(tr) }));
    const mergedOriginal = snapshots.map((snapshot) => snapshot.originalText).join(" ");
    replaceRows(rows, [{
      ...row,
      originalText: mergedOriginal,
      aiEdited: snapshots.some((snapshot) => snapshot.aiEdited),
      history: [],
      mergedSnapshots: snapshots,
      mergedOriginalAtMerge: mergedOriginal,
    }]);
    showToast("تم دمج الصفوف");
  } catch (error) {
    showToast(error.message, true);
  }
}

export async function unmergeRow(tr) {
  if (isLocked(tr.dataset.id)) return showToast(LOCKED_MESSAGE, true);
  const state = rowStates.get(tr.dataset.id);
  syncRowFromDom(tr);

  // the original text was changed after the merge, so the old texts don't match it anymore
  if (originalTextOf(tr) !== state.mergedOriginalAtMerge) {
    return showToast("لا يمكن فك الدمج بعد تعديل النص الأصلي", true);
  }

  try {
    const { rows } = await postJson("/rows/unmerge", { rows: [toRawRow(state)], merged_row_id: state.id });
    const restoredStates = rows.map((raw) => {
      const snapshot = state.mergedSnapshots.find((item) => item.id === raw.id);
      const restored = { ...snapshot, ...raw, aiEdited: snapshot.aiEdited || state.aiEdited, history: [] };
      if (!raw.merged_from) delete restored.merged_from;
      return restored;
    });
    replaceRows([tr], restoredStates);
    showToast("تم فك الدمج");
  } catch (error) {
    showToast(error.message, true);
  }
}

export function initMerge(dependencies) {
  replaceRows = dependencies.replaceRows;
  document.getElementById("merge-rows").addEventListener("click", mergeSelectedRows);
}

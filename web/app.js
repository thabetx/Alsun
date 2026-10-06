import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.min.mjs";
pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.worker.min.mjs";

import { rowStates, joinDisplayText } from "./state.js";
import { renderTranslated, syncRowFromDom } from "./translated-view.js";
import { protectAyahsInCell, EDIT_REFUSED_MESSAGE } from "./segment-sync.js";
import { handleOriginalEdited } from "./retranslate-ui.js";
import { initAssistant, refreshAssistantButton, forgetDeletedRow } from "./assistant.js";
import { initMerge, refreshMergeButton } from "./merge-ui.js";
import { rememberBlockKind } from "./row-kind.js";
import { highlightRowInPreview, initExportPreview, refreshExportPreview, watchExportPreview } from "./export-preview.js";
import { rowMenuMarkup, refreshRowMenu, runRowMenuAction } from "./row-menu.js";
import { detectAyahsInRows } from "./detect-ayas.js";
import { askConfirmation } from "./confirm-dialog.js";
import { getRowById, getSelectedRows } from "./selection.js";
import { normalizeArabic, matchesSearch } from "./arabic-text.js";
import { applyLock, toggleLock, isLocked, LOCKED_MESSAGE } from "./row-lock.js";
import { showToast } from "./toast.js";
import { initTranslateAll } from "./translate-all.js";
import { targetLanguageInArabic } from "./target-language.js";
import { initGlossary } from "./glossary-ui.js";
import { initSettings } from "./settings-ui.js";
import { beginLoading, setLoadingProgress } from "./loading-overlay.js";
import { getJson } from "./api.js";
import {
  fingerprintOf, loadSavedWork, clearSavedWork, enableSaving, pauseSaving, watchWork,
} from "./saved-work.js";
import { loadOcr, saveOcr } from "./ocr-store.js";

document.getElementById("translated-heading").textContent = `الترجمة إلى ${targetLanguageInArabic()}`;

const SVGNS = "http://www.w3.org/2000/svg";
const blockRows = document.getElementById("block-rows");
const pdfPages = document.getElementById("pdf-pages");
const checkAll = document.getElementById("check-all");
const pageInput = document.getElementById("page-input");
const pageTotal = document.getElementById("page-total");
const searchInput = document.getElementById("search-input");
const pageSheets = [];
// the drawn pages, kept to be drawn again when the width of the panel changes (see drawPage)
const renderedPages = [];
let totalPages = 0;

// pdf block id -> its polygon on the page, and pdf block id -> the row that shows it now
// (a merged row shows several blocks, so one row can be the answer for many ids)
const polygonsByBlockId = new Map();
const rowByBlockId = new Map();

// the checkbox in the header: empty = no row selected, dash = some rows, tick = all rows
function updateCheckAllState() {
  const checks = [...blockRows.querySelectorAll(".block-check")];
  const selected = checks.filter((check) => check.checked).length;
  checkAll.checked = checks.length > 0 && selected === checks.length;
  checkAll.indeterminate = selected > 0 && selected < checks.length;
}

function notifySelectionChanged() {
  updateCheckAllState();
  updateDeleteButton();
  refreshAssistantButton();
  refreshMergeButton();
  refreshExportPreview(); // what is in the table is what the book will be
}

function setRowHighlight(tr, on) {
  JSON.parse(tr.dataset.sourceBlocks).forEach((blockId) => {
    polygonsByBlockId.get(blockId)?.classList.toggle("highlight", on);
  });
  tr.classList.toggle("active", on);
}

// The mouse is in one of the three panels and the other two answer: the row lights up in the table
// and on the page, and the panels that are not under the mouse bring it into view. The panel the
// mouse is in already shows it, so nothing there is scrolled: a page that centres itself under the
// cursor would move the words out from under the pointer.
function revealRow(rowId, on, from) {
  const tr = rowId && getRowById(rowId);
  if (!tr) return;
  setRowHighlight(tr, on);
  if (from !== "book") highlightRowInPreview(rowId, on);
  if (!on) return;
  if (from !== "table") tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
  if (from !== "pdf") scrollPdfToRow(tr);
}

// the pdf panel turns to the page that holds the first block of the row
function scrollPdfToRow(tr) {
  const blockIds = JSON.parse(tr.dataset.sourceBlocks);
  polygonsByBlockId.get(blockIds[0])?.scrollIntoView({ block: "center", behavior: "smooth" });
}

// connects a row to the pdf blocks it shows (its state.source_blocks)
function registerRowBlocks(tr) {
  const blockIds = rowStates.get(tr.dataset.id).source_blocks.map((block) => block.id);
  tr.dataset.sourceBlocks = JSON.stringify(blockIds);
  blockIds.forEach((blockId) => rowByBlockId.set(blockId, tr));

  tr.addEventListener("mouseenter", () => revealRow(tr.dataset.id, true, "table"));
  tr.addEventListener("mouseleave", () => revealRow(tr.dataset.id, false, "table"));
}

// builds the row of a state (used when rows are merged or split again)
function createRowFromState(state) {
  const tr = makeRow({ id: state.id, text: state.originalText });
  rowStates.set(state.id, state);
  renderTranslated(tr);
  applyLock(tr);
  registerRowBlocks(tr);
  return tr;
}

// "صف", "صفين", "3 صفوف", "12 صفًا"
function rowsPhrase(count) {
  if (count === 1) return "صف واحد";
  if (count === 2) return "صفين";
  return count <= 10 ? `${count} صفوف` : `${count} صفًا`;
}

// Deletes rows for good: the table rows, their state, and everything that points to them on the pdf side.
// Nothing is kept, so the final extraction can't find them.
async function deleteRows(trs) {
  const lockedCount = trs.filter((tr) => isLocked(tr.dataset.id)).length;
  const rows = trs.filter((tr) => rowStates.has(tr.dataset.id) && !isLocked(tr.dataset.id));
  if (lockedCount) {
    showToast(rows.length ? `لن يُحذف ${lockedCount === 1 ? "الصف المقفل" : `${lockedCount} صفوف مقفلة`}، افتح القفل أولًا.` : LOCKED_MESSAGE, true);
  }
  if (!rows.length) return;

  let message;
  if (rows.length === 1) {
    const text = rows[0].querySelector(".original-text").textContent.trim().replace(/\s+/g, " ");
    const preview = text.length > 80 ? `${text.slice(0, 80)}…` : text;
    const mergedNote = rowStates.get(rows[0].dataset.id).merged_from ? " وهو صف مدموج، فسيُحذف بكل أجزائه." : "";
    message = `سيتم حذف هذا الصف نهائيًا ولن يظهر في الاستخراج النهائي.${mergedNote} «${preview}»`;
  } else {
    message = `سيتم حذف ${rowsPhrase(rows.length)} نهائيًا، ولن تظهر في الاستخراج النهائي.`;
  }

  const confirmed = await askConfirmation({
    title: rows.length === 1 ? "حذف الصف" : "حذف الصفوف",
    message,
    confirmLabel: "احذف نهائيًا",
    icon: "fa-trash-can",
    tone: "danger",
  });
  if (!confirmed) return;

  let deleted = 0;
  rows.forEach((tr) => {
    const rowId = tr.dataset.id;
    const state = rowStates.get(rowId);
    if (!state) return; // gone while the window was open (merged, or deleted twice)

    state.source_blocks.forEach((block) => {
      polygonsByBlockId.get(block.id)?.remove();
      polygonsByBlockId.delete(block.id);
      rowByBlockId.delete(block.id);
    });
    rowStates.delete(rowId);
    tr.remove();
    forgetDeletedRow(rowId);
    deleted++;
  });
  notifySelectionChanged();
  if (deleted) showToast(deleted === 1 ? "تم حذف الصف" : `تم حذف ${rowsPhrase(deleted)}`);
}

// the trash button of the toolbar: only for checked rows
function updateDeleteButton() {
  const button = document.getElementById("delete-rows");
  const count = getSelectedRows().length;
  button.disabled = count === 0;
  if (!count) button.title = "حدّد صفًا أو أكثر للحذف";
  else if (count === 1) button.title = "حذف الصف المحدد نهائيًا";
  else if (count === 2) button.title = "حذف الصفين المحددين نهائيًا";
  else button.title = `حذف الصفوف المحددة (${count}) نهائيًا`;
}

function replaceRows(oldRows, newStates) {
  const newRows = newStates.map(createRowFromState);
  oldRows[0].before(...newRows);
  const newIds = newStates.map((state) => state.id);
  oldRows.forEach((tr) => {
    if (!newIds.includes(tr.dataset.id)) rowStates.delete(tr.dataset.id);
    tr.remove();
  });
  checkAll.checked = false;
  notifySelectionChanged();
}

// The translations change (translate, edit, assistant, merge), so they are normalized when the user searches;
// the cache keeps the answer for a text that did not change, so typing a word does not redo every row.
const normalizedTranslations = new Map(); // text -> normalized text
function normalizedTranslation(text) {
  let normalized = normalizedTranslations.get(text);
  if (normalized === undefined) {
    if (normalizedTranslations.size > 3000) normalizedTranslations.clear();
    normalized = normalizeArabic(text);
    normalizedTranslations.set(text, normalized);
  }
  return normalized;
}

// What a search looks at in a row: the Arabic original (normalized when the row was made) and its translation.
// The translation comes from the state of the row, not from the cell, so the "not translated yet" message is not searched.
function searchableText(tr) {
  const segments = rowStates.get(tr.dataset.id)?.segments;
  if (!segments?.length) return tr.dataset.search;
  return `${tr.dataset.search} ${normalizedTranslation(joinDisplayText(segments))}`;
}

function applySearch() {
  const q = searchInput.value.trim();
  blockRows.querySelectorAll("tr.block-row").forEach((tr) => {
    const hit = !q || matchesSearch(searchableText(tr), q);
    tr.style.display = hit ? "" : "none";
  });
}

function setPageIndicator(page) {
  if (pageInput && document.activeElement !== pageInput) {
    pageInput.value = String(page);
  }
}

function updatePageFromScroll() {
  const container = pdfPages;
  const mid = container.scrollTop + container.clientHeight / 2;
  let current = 1;
  pageSheets.forEach((sheet, i) => {
    const top = sheet.offsetTop - container.scrollTop + sheet.offsetParent.scrollTop;
    if (top <= mid) current = i + 1;
  });
  setPageIndicator(current);
}

function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function stripHtml(html) {
  const div = document.createElement("div");
  div.innerHTML = html || "";
  return div.textContent.trim();
}

function collectBlocks(node, out = []) {
  for (const child of node.children || []) {
    if (child.block_type !== "Page") out.push(child);
    collectBlocks(child, out);
  }
  return out;
}

function makeRow(b) {
  const tr = document.createElement("tr");
  tr.className = "block-row";
  tr.dataset.id = b.id;

  // a row made by a merge has its own text (b.text), a pdf block has html
  const text = b.text !== undefined ? b.text : stripHtml(b.html);
  const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  tr.dataset.search = normalizeArabic(text); // the search ignores tashkeel, hamza forms, taa marbuta ...

  // the state of the row: what we know about its translation (the segments) and where it comes from
  rowStates.set(b.id, {
    id: b.id,
    segments: [],
    source_blocks: [{ id: b.id }],
    originalText: text,
    aiEdited: false,
    history: [],
  });
  // the kind the ocr gave this block (a section header, a footnote...) is what the export makes of it
  rememberBlockKind(b.id, b.block_type);

  tr.innerHTML = `
    <td class="col-check text-center">
      <input class="form-check-input block-check" type="checkbox" data-id="${b.id}">
    </td>
    <td class="col-lock text-center">
      <button class="lock-btn" type="button" aria-pressed="false" aria-label="علّم الصف كمنتهٍ واقفله"
              title="علّم الصف كمنتهٍ (يُقفل حتى لا يتغيّر)"><i class="fa-solid fa-check"></i></button>
    </td>
    <td class="col-original">
      <div class="original-text" contenteditable="true" dir="rtl"
           data-id="${b.id}" aria-label="النص الأصلي">${escaped}</div>
    </td>
    <td class="translated-cell">
      <div class="translated-text" contenteditable="true" dir="ltr"
           data-id="${b.id}" aria-label="الترجمة"></div>
      <span class="ai-chip" hidden>معدّل بالذكاء الاصطناعي</span>
    </td>
    <td class="col-actions text-center">
      <div class="row-actions">
        <div class="dropdown dropend">
          <button class="btn btn-dots" type="button"
                  data-bs-toggle="dropdown" aria-expanded="false"
                  aria-label="إجراءات" title="إجراءات">&#8942;</button>
          <ul class="dropdown-menu">${rowMenuMarkup()}
          </ul>
        </div>
      </div>
    </td>`;

  const check = tr.querySelector(".block-check");
  const checkTd = tr.querySelector(".col-check");
  const original = tr.querySelector(".original-text");
  const translated = tr.querySelector(".translated-text");
  renderTranslated(tr); // not translated yet: the cell shows the hint
  check.addEventListener("change", () => {
    tr.classList.toggle("active", check.checked);
    notifySelectionChanged();
  });
  check.addEventListener("click", (e) => e.stopPropagation());
  tr.querySelector(".lock-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleLock(tr);
  });
  checkTd.addEventListener("click", () => {
    check.checked = !check.checked;
    tr.classList.toggle("active", check.checked);
    notifySelectionChanged();
  });

  const editClass = (on) => tr.classList.toggle("editing", on);
  original.addEventListener("focus", () => editClass(true));
  original.addEventListener("blur", () => {
    editClass(false);
    // a changed original means the row is translated again (and the ayahs are checked again)
    handleOriginalEdited(tr, original.textContent);
  });
  protectAyahsInCell(translated, { onRefused: () => showToast(EDIT_REFUSED_MESSAGE, true) });
  translated.addEventListener("focus", () => editClass(true));
  translated.addEventListener("blur", () => {
    editClass(false);
    syncRowFromDom(tr);
  });

  const dots = tr.querySelector(".btn-dots");
  const dropdown = tr.querySelector(".dropdown");
  const menu = tr.querySelector(".dropdown-menu");

  const closeMenu = () => {
    dropdown.classList.remove("show");
    menu.classList.remove("show");
    dots.setAttribute("aria-expanded", "false");
  };

  // the items show what is possible for this row at the moment the menu opens
  dots.addEventListener("click", () => refreshRowMenu(tr));

  tr.querySelectorAll(".dropdown-item").forEach((item) => {
    item.addEventListener("click", async (e) => {
      e.stopPropagation();
      closeMenu();
      if (item.dataset.action === "delete") deleteRows([tr]);
      else runRowMenuAction(tr, item.dataset.action);
    });
  });

  return tr;
}

// Puts back the work saved in the browser over the rows the OCR just gave:
// translations and edits, merged rows, and without the rows the user deleted. Returns true if something was put back.
function restoreSavedWork(filename, fingerprint) {
  const saved = loadSavedWork(filename, fingerprint);
  if (!saved) return false;

  // a pdf block that no saved row shows was deleted: its polygon goes too
  const shownBlockIds = new Set(saved.flatMap((state) => state.source_blocks.map((block) => block.id)));
  for (const [blockId, polygon] of polygonsByBlockId) {
    if (shownBlockIds.has(blockId)) continue;
    polygon.remove();
    polygonsByBlockId.delete(blockId);
    rowByBlockId.delete(blockId);
  }

  const oldRows = new Map([...blockRows.children].map((tr) => [tr.dataset.id, tr]));
  const rows = saved.map((state) => {
    const tr = oldRows.get(state.id);
    if (!tr || state.merged_from) return createRowFromState(state); // a merged row has to be built again
    rowStates.set(state.id, state);
    tr.querySelector(".original-text").textContent = state.originalText;
    tr.dataset.search = normalizeArabic(state.originalText);
    renderTranslated(tr);
    applyLock(tr);
    return tr;
  });
  blockRows.replaceChildren(...rows);
  notifySelectionChanged();
  return true;
}

// The pen covers the page while the book is read (the ocr can take a while) and the rows are drawn.
const BOOK_TIPS = [
  "آيات القرآن لا تُترجم بالذكاء الاصطناعي، بل تؤخذ من ترجمات منشورة وموثّقة.",
  "يُحفظ عملك تلقائيًا في متصفحك، فلا يضيع عند تحديث الصفحة.",
  "أضف مصطلحاتك وترجماتها المعتمدة من زر «القاموس»، وتُطبَّق في كل ترجمة.",
  "يمكنك اختيار النموذج ومرجع القرآن من زر «الإعدادات».",
  "عدّل أي فقرة مترجمة في مكانها، أو اطلب من المساعد الذكي تعديلها.",
];

async function loadBook(filename) {
  // the detector of the quran loads while the book is read (it is not loaded when the server starts)
  fetch("/warmup", { method: "POST" }).catch(() => {});
  const endLoading = beginLoading({ message: "جارٍ قراءة الكتاب…", tips: BOOK_TIPS });
  try {
    await readBook(filename);
  } finally {
    endLoading();
  }
}

// A book is read a few pages at a time: a long book is one request after the other (each one is short, and the
// pages the server already has are not paid for again), and the pen says how far it is.
const OCR_PAGES_PER_REQUEST = 5;

function showBookInTheSelect(info) {
  // an uploaded book is not one of the options of the page: it is added, with the name of its file
  let option = [...bookSelect.options].find((candidate) => candidate.value === info.id);
  if (!option) {
    option = new Option(info.name, info.id);
    bookSelect.append(option);
  }
  option.textContent = info.name;
  bookSelect.value = info.id;
  showBookName(info.name);
  document.title = `${info.name} — ألسن`;
}

// Gives {children: the pages read, error: the message if the reading stopped}. If the first request fails there is
// nothing to show, so the error is thrown; if a later one fails the pages that were read are still worth showing.
async function readPages(info) {
  const children = [];
  for (let first = 0; first < info.pages; first += OCR_PAGES_PER_REQUEST) {
    const last = Math.min(first + OCR_PAGES_PER_REQUEST, info.pages) - 1;
    setLoadingProgress(info.pages > 1 ? `${first} من ${info.pages} صفحة` : "");
    try {
      const data = await getJson(`/ocr?book=${encodeURIComponent(info.id)}&page_range=${first}-${last}`);
      children.push(...(data.children || []));
    } catch (error) {
      if (!children.length) throw error;
      return { children, error: `توقفت القراءة عند الصفحة ${first + 1}: ${error.message}` };
    }
  }
  return { children, error: null };
}

async function readBook(filename) {
  pauseSaving(); // the table is empty while it loads, that must not be saved
  blockRows.innerHTML = "";
  pdfPages.innerHTML = "";
  checkAll.checked = false;
  rowStates.clear();
  polygonsByBlockId.clear();
  rowByBlockId.clear();

  let data;
  let info;
  try {
    info = await getJson(`/books/${encodeURIComponent(filename)}`);
    showBookInTheSelect(info);

    // the book read before is kept in localStorage, so the server is not asked to run the ocr and the
    // llm again. "modified" of the book is what tells a pdf replaced under the same name apart.
    const stamp = info.modified ? String(info.modified) : null;
    const stored = loadOcr(filename, stamp);
    if (stored) {
      data = stored;
    } else {
      data = await readPages(info);
      // a book that does not fit in the storage is not an error, but it is read again every time
      if (stamp && !data.error && !saveOcr(filename, stamp, data)) showToast("تعذّر حفظ نتيجة OCR في المتصفح");
    }
  } catch (e) {
    blockRows.innerHTML =
      `<tr><td colspan="4" style="color:#b3402e">تعذّرت قراءة الكتاب: ${escapeHtml(e.message)}</td></tr>`;
    return;
  }
  if (data.error) showToast(data.error, true);

  let pdf;
  try {
    pdf = await pdfjsLib.getDocument(`/books/${encodeURIComponent(filename)}/pdf`).promise;
  } catch (e) {
    pdfPages.innerHTML = '<div class="block" style="color:#b3402e">تعذّر تحميل ملف الـ PDF.</div>';
    return;
  }

  const pages = (data.children || []).filter((c) => c.block_type === "Page");
  totalPages = pages.length;
  pageTotal.textContent = `/ ${totalPages}`;
  pageSheets.length = 0;
  renderedPages.length = 0;
  setPageIndicator(1);

  pages.forEach((page, pi) => {
    // ---- right: render PDF page with overlay ----
    const sheet = document.createElement("div");
    sheet.className = "page-sheet";
    pdfPages.appendChild(sheet);
    pageSheets.push(sheet);

    const canvas = document.createElement("canvas");
    canvas.className = "page-canvas";
    sheet.appendChild(canvas);

    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("class", "page-overlay");
    svg.setAttribute("preserveAspectRatio", "none");
    sheet.appendChild(svg);

    const [x0, y0, x1, y1] = page.bbox;
    svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);

    pdf.getPage(pi + 1).then((pdfPage) => {
      const entry = { page: pdfPage, canvas, svg };
      renderedPages.push(entry);
      drawPage(entry);
    });

    const blocks = collectBlocks(page);

    for (const b of blocks) {
      const tr = makeRow(b);
      blockRows.appendChild(tr);
      registerRowBlocks(tr);

      if (b.polygon && b.polygon.length) {
        const poly = addPolygon(svg, b.polygon);
        polygonsByBlockId.set(b.id, poly);

        // the row of this block may be a merged row by now, so it is looked up when the mouse comes
        poly.addEventListener("mouseenter", () => revealRow(rowByBlockId.get(b.id)?.dataset.id, true, "pdf"));
        poly.addEventListener("mouseleave", () => revealRow(rowByBlockId.get(b.id)?.dataset.id, false, "pdf"));
      }
    }
  });

  // the rows are ready: put back the saved work, then start saving again
  const fingerprint = fingerprintOf(
    [...blockRows.children].map((tr) => ({ id: tr.dataset.id, text: rowStates.get(tr.dataset.id).originalText }))
  );
  if (restoreSavedWork(filename, fingerprint)) showToast("تم استرجاع عملك المحفوظ");
  enableSaving(filename, fingerprint);

  checkAll.addEventListener("change", () => {
    blockRows.querySelectorAll(".block-check").forEach((c) => {
      c.checked = checkAll.checked;
      c.closest("tr").classList.toggle("active", checkAll.checked);
    });
    notifySelectionChanged();
  });

  // the text the server sent was already fixed by the llm. what is left is to find the
  // ayahs in it and mark them, which is the detector alone, no llm and no cost
  detectAyahsInRows([...blockRows.querySelectorAll("tr.block-row")]);
}

// A page is drawn to fit the panel instead of being cropped: a page wider than the view is drawn
// smaller, because the words on the canvas and the polygons over them are placed from the same
// viewport and must be the same size for the pointer to mean anything. On a wide screen the page is
// left at MAX_PDF_SCALE rather than blown up to a wall of pixels.
const MAX_PDF_SCALE = 1.5;

// the width the pages are drawn into: the panel without its padding (0 when it is hidden)
function pdfViewWidth() {
  if (!pdfPages.clientWidth) return 0;
  const style = getComputedStyle(pdfPages);
  return pdfPages.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
}

async function drawPage(entry) {
  // A drawing that is still going on is stopped first: two drawings on one canvas (the first one and the one
  // after the scrollbar changed the width) put one page over the other, and the page looks flipped and garbled.
  const turn = (entry.turn = (entry.turn ?? 0) + 1);
  if (entry.renderTask) {
    entry.renderTask.cancel();
    await entry.renderTask.promise.catch(() => {}); // it ends with "cancelled", which is what we wanted
    if (turn !== entry.turn) return; // a newer drawing was asked while we waited: it draws
  }

  const natural = entry.page.getViewport({ scale: 1 }).width;
  const width = pdfViewWidth();
  const scale = width ? Math.min(MAX_PDF_SCALE, width / natural) : MAX_PDF_SCALE;
  const viewport = entry.page.getViewport({ scale });
  entry.canvas.width = viewport.width;
  entry.canvas.height = viewport.height;
  entry.svg.setAttribute("width", viewport.width);
  entry.svg.setAttribute("height", viewport.height);
  entry.renderTask = entry.page.render({ canvasContext: entry.canvas.getContext("2d"), viewport });
  entry.renderTask.promise.catch((error) => {
    if (error?.name !== "RenderingCancelledException") console.error(error);
  });
}

// The window is resized, the pdf panel is shown again, and drawing a page can itself change the
// width left for it (a page that fills the panel brings a scrollbar), so the observer draws again
// until the size has settled.
function refitPages() {
  if (pdfViewWidth()) renderedPages.forEach(drawPage);
}

let refitTimer = null;
new ResizeObserver(() => {
  clearTimeout(refitTimer);
  refitTimer = setTimeout(refitPages, 100);
}).observe(pdfPages);

function addPolygon(svg, points) {
  const poly = document.createElementNS(SVGNS, "polygon");
  poly.setAttribute("points", points.map((p) => p.join(",")).join(" "));
  svg.appendChild(poly);
  return poly;
}

function jumpToPage(n) {
  n = Math.max(1, Math.min(totalPages, n));
  const sheet = pageSheets[n - 1];
  if (sheet) {
    sheet.scrollIntoView({ block: "start", behavior: "smooth" });
    setPageIndicator(n);
  }
}

pdfPages.addEventListener("scroll", updatePageFromScroll);
searchInput.addEventListener("input", applySearch);
document.addEventListener("row-lock-changed", notifySelectionChanged); // the toolbar buttons depend on the locks

const togglePdf = document.getElementById("toggle-pdf");
const pdfPanel = document.querySelector(".panel-pdf");
togglePdf.addEventListener("click", () => {
  const hidden = pdfPanel.style.display === "none";
  pdfPanel.style.display = hidden ? "" : "none";
  togglePdf.setAttribute("aria-pressed", String(hidden));
  if (hidden) refitPages(); // the panel has a width again, the pages must fill it
});

pageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const n = parseInt(pageInput.value, 10);
    if (!Number.isNaN(n)) jumpToPage(n);
    e.preventDefault();
  }
});
pageInput.addEventListener("focus", () => pageInput.select());
pageInput.addEventListener("blur", () => setPageIndicator(parseInt(pageInput.value, 10) || 1));

const bookSelect = document.getElementById("book-select");
// the header shows the name of the book (without ".pdf"); the select is hidden, the code reads the book from it
const bookNameLabel = document.getElementById("book-name");
function showBookName(name) {
  bookNameLabel.textContent = String(name || "").replace(/\.pdf$/i, "");
  bookNameLabel.title = String(name || "");
}
showBookName([...bookSelect.options].find((o) => o.value === (new URLSearchParams(location.search).get("book") || bookSelect.value))?.textContent);
// The book is in the address (/app?book=...): the sample books of the page, or the id of an uploaded one.
const currentBook = new URLSearchParams(location.search).get("book") || bookSelect.value;
bookSelect.addEventListener("change", () => {
  location.href = `/app?book=${encodeURIComponent(bookSelect.value)}`;
});

// the work is saved in the browser (see saved-work.js)
let warnedAboutSaving = false;
window.addEventListener("pagehide", () => {
  // a cell still being edited has not reached its state yet (that happens when it loses the focus)
  const cell = document.activeElement?.closest?.(".translated-text");
  if (cell) syncRowFromDom(cell.closest("tr"));
});
watchWork({
  table: blockRows,
  getRows: () => [...blockRows.querySelectorAll("tr.block-row")],
  onFailed: () => {
    if (warnedAboutSaving) return;
    warnedAboutSaving = true;
    showToast("تعذّر حفظ عملك في المتصفح، قد يضيع عند تحديث الصفحة", true);
  },
});

document.getElementById("restart-work").addEventListener("click", async () => {
  const confirmed = await askConfirmation({
    title: "البدء من جديد",
    message: "سيتم مسح الترجمات والتعديلات المحفوظة واسترجاع الصفوف المحذوفة والمدموجة، ولا يمكن التراجع عن ذلك.",
    confirmLabel: "امسح وابدأ من جديد",
    icon: "fa-rotate-left",
    tone: "danger",
  });
  if (!confirmed) return;
  clearSavedWork(currentBook);
  await loadBook(currentBook);
  showToast("تم مسح العمل المحفوظ");
});

// a checked row that gets translated (or loses its translation) changes what the toolbar can do
// (the assistant needs a translated row, merge needs rows that are all translated or all not): refresh the buttons
let toolbarRefreshWaiting = false;
blockRows.addEventListener("alsun:translated-changed", () => {
  if (toolbarRefreshWaiting) return; // several rows in a row (translate all, restore) are one refresh
  toolbarRefreshWaiting = true;
  setTimeout(() => {
    toolbarRefreshWaiting = false;
    notifySelectionChanged();
  }, 0);
});

loadBook(currentBook);

initAssistant();
initTranslateAll();
initGlossary();
initSettings();
document.getElementById("delete-rows").addEventListener("click", () => deleteRows(getSelectedRows()));
initMerge({ replaceRows });
initExportPreview({ onHoverRow: (rowId, on) => revealRow(rowId, on, "book") });
watchExportPreview(blockRows);
notifySelectionChanged();

import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.min.mjs";
pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.worker.min.mjs";

import { rowStates } from "./state.js";
import { renderTranslated, syncRowFromDom } from "./translated-view.js";
import { handleOriginalEdited } from "./retranslate-ui.js";
import { initAssistant, refreshAssistantButton } from "./assistant.js";
import { initMerge, refreshMergeButton, unmergeRow } from "./merge-ui.js";
import { translateRow } from "./translate-ui.js";
import { initTranslateAll } from "./translate-all.js";

const SVGNS = "http://www.w3.org/2000/svg";
const blockRows = document.getElementById("block-rows");
const pdfPages = document.getElementById("pdf-pages");
const checkAll = document.getElementById("check-all");
const pageInput = document.getElementById("page-input");
const pageTotal = document.getElementById("page-total");
const searchInput = document.getElementById("search-input");
const pageSheets = [];
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
  refreshAssistantButton();
  refreshMergeButton();
}

function setRowHighlight(tr, on) {
  JSON.parse(tr.dataset.sourceBlocks).forEach((blockId) => {
    polygonsByBlockId.get(blockId)?.classList.toggle("highlight", on);
  });
  tr.classList.toggle("active", on);
}

// connects a row to the pdf blocks it shows (its state.source_blocks)
function registerRowBlocks(tr) {
  const blockIds = rowStates.get(tr.dataset.id).source_blocks.map((block) => block.id);
  tr.dataset.sourceBlocks = JSON.stringify(blockIds);
  blockIds.forEach((blockId) => rowByBlockId.set(blockId, tr));

  tr.addEventListener("mouseenter", () => {
    setRowHighlight(tr, true);
    polygonsByBlockId.get(blockIds[0])?.scrollIntoView({ block: "center", behavior: "smooth" });
  });
  tr.addEventListener("mouseleave", () => setRowHighlight(tr, false));
}

// builds the row of a state (used when rows are merged or split again)
function createRowFromState(state) {
  const tr = makeRow({ id: state.id, text: state.originalText });
  rowStates.set(state.id, state);
  renderTranslated(tr);
  registerRowBlocks(tr);
  return tr;
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

function applySearch() {
  const q = searchInput.value.trim();
  blockRows.querySelectorAll("tr.block-row").forEach((tr) => {
    const hit = !q || tr.dataset.search.includes(q);
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
  tr.dataset.search = text;

  // the state of the row: what we know about its translation (the segments) and where it comes from
  rowStates.set(b.id, {
    id: b.id,
    segments: [],
    source_blocks: [{ id: b.id }],
    originalText: text,
    aiEdited: false,
    history: [],
  });

  tr.innerHTML = `
    <td class="col-check text-center">
      <input class="form-check-input block-check" type="checkbox" data-id="${b.id}">
    </td>
    <td class="col-original">
      <div class="original-text" contenteditable="true" dir="rtl"
           data-id="${b.id}" aria-label="النص الأصلي">${escaped}</div>
    </td>
    <td class="translated-cell">
      <div class="translated-text" contenteditable="true" dir="ltr"
           data-id="${b.id}" aria-label="الترجمة">Dummy translation text, to be replaced with the actual translation.</div>
      <span class="ai-chip" hidden>معدّل بالذكاء الاصطناعي</span>
    </td>
    <td class="col-actions text-center">
      <div class="row-actions">
        <div class="dropdown dropend">
          <button class="btn btn-dots" type="button"
                  data-bs-toggle="dropdown" aria-expanded="false"
                  aria-label="إجراءات" title="إجراءات">&#8942;</button>
          <ul class="dropdown-menu">
            <li><button class="dropdown-item" type="button" data-action="translate">ترجمة</button></li>
            <li><button class="dropdown-item" type="button" data-action="summarize">تلخيص</button></li>
            <li><button class="dropdown-item" type="button" data-action="revert">استعادة التغييرات</button></li>
            <li class="merged-only" hidden><button class="dropdown-item" type="button" data-action="unmerge">فك الدمج</button></li>
            <li><hr class="dropdown-divider"></li>
            <li><button class="dropdown-item text-danger" type="button" data-action="delete">حذف</button></li>
          </ul>
        </div>
      </div>
    </td>`;

  const check = tr.querySelector(".block-check");
  const checkTd = tr.querySelector(".col-check");
  const original = tr.querySelector(".original-text");
  const translated = tr.querySelector(".translated-text");
  check.addEventListener("change", () => {
    tr.classList.toggle("active", check.checked);
    notifySelectionChanged();
  });
  check.addEventListener("click", (e) => e.stopPropagation());
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

  tr.querySelectorAll(".dropdown-item").forEach((item) => {
    item.addEventListener("click", async (e) => {
      e.stopPropagation();
      closeMenu();
      if (item.dataset.action === "translate") {
        translateRow(tr);
      } else if (item.dataset.action === "unmerge") {
        unmergeRow(tr);
      } else {
        console.log(item.dataset.action, b.id);
      }
    });
  });

  return tr;
}

async function loadBook(filename) {
  blockRows.innerHTML = "";
  pdfPages.innerHTML = "";
  checkAll.checked = false;
  rowStates.clear();
  polygonsByBlockId.clear();
  rowByBlockId.clear();

  let data;
  try {
    const res = await fetch(`/ocr?filename=${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error(`OCR failed: ${res.status}`);
    data = await res.json();
  } catch (e) {
    blockRows.innerHTML =
      '<tr><td colspan="3" style="color:#ff8a80">تعذّر تشغيل OCR. ' +
      "افتح http://127.0.0.1:8000/ وتأكد من تشغيل الخادم.</td></tr>";
    return;
  }

  let pdf;
  try {
    pdf = await pdfjsLib.getDocument(`../data/${encodeURIComponent(filename)}`).promise;
  } catch (e) {
    pdfPages.innerHTML =
      `<div class="block" style="color:#ff8a80">تعذّر تحميل ../data/${filename} (يجب تقديمه عبر HTTP).</div>`;
    return;
  }

  const pages = (data.children || []).filter((c) => c.block_type === "Page");
  totalPages = pages.length;
  pageTotal.textContent = `/ ${totalPages}`;
  pageSheets.length = 0;
  setPageIndicator(1);
  const scale = 1.5;

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
      const viewport = pdfPage.getViewport({ scale });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      svg.setAttribute("width", viewport.width);
      svg.setAttribute("height", viewport.height);
      pdfPage.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
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
        poly.addEventListener("mouseenter", () => {
          const row = rowByBlockId.get(b.id);
          setRowHighlight(row, true);
          row.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
        poly.addEventListener("mouseleave", () => setRowHighlight(rowByBlockId.get(b.id), false));
      }
    }
  });

  checkAll.addEventListener("change", () => {
    blockRows.querySelectorAll(".block-check").forEach((c) => {
      c.checked = checkAll.checked;
      c.closest("tr").classList.toggle("active", checkAll.checked);
    });
    notifySelectionChanged();
  });
}

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

const togglePdf = document.getElementById("toggle-pdf");
const pdfPanel = document.querySelector(".panel-pdf");
togglePdf.addEventListener("click", () => {
  const hidden = pdfPanel.style.display === "none";
  pdfPanel.style.display = hidden ? "" : "none";
  togglePdf.setAttribute("aria-pressed", String(hidden));
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
bookSelect.addEventListener("change", () => loadBook(bookSelect.value));

loadBook(bookSelect.value);

initAssistant();
initTranslateAll();
initMerge({ replaceRows });
notifySelectionChanged();

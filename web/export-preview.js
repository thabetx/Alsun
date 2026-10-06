import { collectRowsForExtraction } from "./export-data.js";
import { bookHtml, bookMarkdown, bookWordHtml, translatedRows } from "./export-html.js";
import { showToast } from "./toast.js";
import { targetLanguage, targetLanguageCode } from "./target-language.js";

// The panel on the left of the pdf: the whole translation as one html page, drawn the way it will be
// saved, with a button that saves it as pdf, word or markdown. What it shows is built from the rows
// as they are now, so an edit in a cell shows up here as it is typed.

const REFRESH_DELAY_MS = 250; // long enough that a fast typist doesn't rebuild the page per letter
const EMPTY_NOTE = "لا يوجد نص مترجم بعد: ترجم صفًا واحدًا على الأقل لتظهر المعاينة هنا.";

// the formats the button writes to a file. pdf is not here: the browser prints it (see printAsPdf).
const FILES = {
  doc: { extension: "doc", mime: "application/msword;charset=utf-8", label: "Word" },
  md: { extension: "md", mime: "text/markdown;charset=utf-8", label: "Markdown" },
};

const el = (id) => document.getElementById(id);

let timer = null;
let lastHtml = "";
// row id -> the element of the book that row was written as, to connect the two views
const previewElements = new Map();
// what the table wants to hear about the mouse being in the book: (rowId, true|false)
let onRowHover = null;

// "yaqzan.pdf" -> "yaqzan"
function bookName() {
  return (el("book-select")?.value || "book").replace(/\.pdf$/i, "");
}

// the options the book is written with, whatever the format is
function documentOptions() {
  return { title: bookName(), lang: targetLanguageCode() };
}

// The frame is drawn again from scratch on every change, so this is where the book is connected to
// the table: which element is which row, what the table does when the mouse is over one of them, and
// the mark on the element itself.
function onPreviewLoad(frame, scrolled) {
  const doc = frame.contentDocument;
  if (!doc) return;
  previewElements.clear();
  doc.querySelectorAll("[data-row]").forEach((element) => previewElements.set(element.dataset.row, element));

  // The element the mouse is on is marked as well as the row it belongs to: a paragraph of the book
  // has to show where the mouse is even when the table is far away and its row is out of sight.
  // Moving between the words of one paragraph is not leaving that paragraph, so the row under the
  // mouse is remembered and only reported when it really changes.
  let hovered = null;
  doc.addEventListener("mouseover", (event) => {
    const element = event.target.closest?.("[data-row]");
    const row = element?.dataset.row ?? null;
    if (row === hovered) return;
    previewElements.get(hovered)?.classList.remove("row-hover");
    hovered = row;
    element?.classList.add("row-hover");
    onRowHover?.(row, true);
  });
  doc.addEventListener("mouseout", (event) => {
    const element = event.target.closest?.("[data-row]");
    // moving from one word of the paragraph to the next is not leaving that paragraph
    if (!element || element.contains(event.relatedTarget)) return;
    if (element.dataset.row !== hovered) return;
    element.classList.remove("row-hover");
    hovered = null;
    onRowHover?.(element.dataset.row, false);
  });

  if (scrolled) frame.contentWindow.scrollTo(0, scrolled);
}

// The row is under the mouse in the table: the book turns to its place and marks it, the same way
// the pdf panel turns to the page of that row. The frame is scrolled without a "smooth": from the
// page outside the frame that ask is ignored and the book would not move at all.
export function highlightRowInPreview(rowId, on) {
  const element = previewElements.get(rowId);
  if (!element) return;
  element.classList.toggle("row-hover", on);
  if (on) element.scrollIntoView({ block: "center" });
}

// Draws the book again from the rows as they are now. The frame keeps the place it was scrolled to:
// a long book must not jump back to its top every time a word is typed.
export function refreshExportPreview() {
  const frame = el("export-preview");
  if (!frame) return;
  clearTimeout(timer);
  timer = null;

  const rows = collectRowsForExtraction();
  const written = translatedRows(rows).length;
  const count = el("export-count");
  if (count) count.textContent = written ? `${written} من ${rows.length}` : "";

  const html = bookHtml(rows, { ...documentOptions(), emptyNote: EMPTY_NOTE, preview: true });
  if (html === lastHtml) return; // nothing changed: don't reload the frame for nothing
  lastHtml = html;

  const scrolled = frame.contentWindow ? frame.contentWindow.scrollY : 0;
  frame.onload = () => onPreviewLoad(frame, scrolled);
  frame.srcdoc = html;
}

function scheduleRefresh() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    refreshExportPreview();
  }, REFRESH_DELAY_MS);
}

// Everything that can change the book: a row added or removed (a new book, a merge, a delete), a
// translation arriving, a text typed in a cell, the ayah marks moving. The same watching as the
// work saved in the browser (see saved-work.js).
export function watchExportPreview(table) {
  const changed = { childList: true, subtree: true, characterData: true };
  new MutationObserver(scheduleRefresh).observe(table, changed);
  table.addEventListener("input", scheduleRefresh);
  table.addEventListener("focusout", scheduleRefresh);
}

function saveFile(name, content, mime) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// The browser is the pdf maker here: the book goes to an invisible frame and print() opens the
// window where the user picks "save as pdf". No library, and the text stays text, so the words the
// user sees in the preview are the words that reach the page.
function printAsPdf(html) {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  // over the whole window and invisible, so it is laid out (a frame of no size prints nothing)
  // while it neither covers the app nor takes a click
  frame.style.cssText =
    "position:fixed;inset:0;width:100%;height:100%;border:0;opacity:0;pointer-events:none;z-index:-1";
  frame.onload = () => {
    // the book is printed in the face it is written in, so the printing waits for that face to be
    // in: printing before the font arrives would put a fallback serif on every page of the pdf
    Promise.resolve(frame.contentDocument?.fonts?.ready)
      .catch(() => {})
      .then(() => {
        frame.contentWindow.focus();
        frame.contentWindow.print();
      });
    setTimeout(() => frame.remove(), 60000); // in case the print window is left open
  };
  document.body.append(frame);
  frame.srcdoc = html;
}

function download() {
  const rows = collectRowsForExtraction();
  if (!translatedRows(rows).length) return showToast("لا يوجد نص مترجم لحفظه بعد", true);

  const format = el("export-format").value;
  const name = `${bookName()}-${targetLanguage()}`;

  if (format === "pdf") {
    printAsPdf(bookHtml(rows, documentOptions()));
    return showToast("اختر «حفظ كـ PDF» من نافذة الطباعة");
  }

  const { extension, mime, label } = FILES[format];
  const content = format === "md" ? bookMarkdown(rows) : bookWordHtml(rows, documentOptions());
  saveFile(`${name}.${extension}`, content, mime);
  showToast(`تم حفظ الملف بصيغة ${label}`);
}

// the show / hide button, the same way the pdf one works: the panel is the state, aria-pressed
// is only its mirror for the reader
function initToggle() {
  const toggle = el("toggle-preview");
  const panel = document.querySelector(".panel-preview");
  toggle.addEventListener("click", () => {
    const hidden = panel.style.display === "none";
    panel.style.display = hidden ? "" : "none";
    toggle.setAttribute("aria-pressed", String(hidden));
  });
}

export function initExportPreview({ onHoverRow = null } = {}) {
  onRowHover = onHoverRow;
  initToggle();
  el("export-download").addEventListener("click", download);
  refreshExportPreview();
}
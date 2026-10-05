import { rowStates, copy } from "./state.js";
import { targetLanguage } from "./target-language.js";

// Keeps the work of the user in localStorage, so a refresh doesn't lose it:
// the translations, the manual and assistant edits, the edited original texts, the merged rows and the deleted rows.
// What is saved is the state of every row, in the order of the table (the same state the front keeps in memory).
// The key has the book and the language: a row translated into French is not the same work as one translated into English.

const SAVE_DELAY_MS = 1000; // wait until the user stops, so we don't save on every letter
const FORMAT_VERSION = 1;

let enabled = false; // off while a book is loading, or the empty table would be saved over the work
let timer = null;
let findRows = () => [];
let currentBook = null;
let currentFingerprint = "";
let onSaveFailed = () => {};

const keyOf = (book) => `alsun:work:v${FORMAT_VERSION}:${book}:${targetLanguage()}`;

// A short fingerprint of the rows the OCR gave. If the book gives other rows one day, the saved work doesn't fit it.
export function fingerprintOf(rows) {
  const text = rows.map((row) => `${row.id}|${row.text}`).join("\n");
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return `${rows.length}:${hash}`;
}

// the states saved for this book, or null (nothing saved, or saved for other OCR rows)
export function loadSavedWork(book, fingerprint) {
  try {
    const saved = JSON.parse(localStorage.getItem(keyOf(book)));
    if (!saved || saved.version !== FORMAT_VERSION || saved.fingerprint !== fingerprint) return null;
    return Array.isArray(saved.rows) && saved.rows.length ? saved.rows : null;
  } catch (error) {
    return null; // not json, or no access to the storage
  }
}

export function clearSavedWork(book) {
  clearTimeout(timer);
  timer = null;
  try {
    localStorage.removeItem(keyOf(book));
  } catch (error) {
    // nothing to clear
  }
}

function writeNow() {
  timer = null;
  if (!enabled || !currentBook) return;
  const rows = findRows()
    .map((tr) => rowStates.get(tr.dataset.id))
    .filter(Boolean)
    .map((state) => {
      const { translating, ...saved } = copy(state); // "translating" is only true while we wait for the server
      return saved;
    });
  try {
    localStorage.setItem(keyOf(currentBook), JSON.stringify({ version: FORMAT_VERSION, fingerprint: currentFingerprint, rows }));
  } catch (error) {
    onSaveFailed(); // the storage is full, or blocked
  }
}

// call it with the book and the fingerprint once its rows are ready (and the saved work was applied)
export function enableSaving(book, fingerprint) {
  currentBook = book;
  currentFingerprint = fingerprint;
  enabled = true;
}

export function pauseSaving() {
  enabled = false;
  clearTimeout(timer);
  timer = null;
}

function scheduleSave() {
  if (!enabled) return;
  clearTimeout(timer);
  timer = setTimeout(() => writeNow(), SAVE_DELAY_MS);
}

// saves at once what is waiting (when the page is closed)
export function saveNowIfWaiting() {
  if (timer !== null) {
    clearTimeout(timer);
    writeNow();
  }
}

// Watches the table: a row added, removed or drawn again, a text typed, the "edited by the assistant" chip.
// The state of a text typed by hand reaches the row when the cell loses the focus, so that is watched too.
export function watchWork({ table, getRows, onFailed }) {
  findRows = getRows;
  onSaveFailed = onFailed;
  new MutationObserver(scheduleSave).observe(table, {
    childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden"],
  });
  table.addEventListener("focusout", scheduleSave);
  window.addEventListener("pagehide", saveNowIfWaiting);
}

// The glossary of the user: Arabic terms and the translation he wants for each one.
// It is kept in the browser (localStorage), one list for every language he translates to, and it is sent with every
// translation (see python/glossary.py, which checks it again). The limits are the same as in the backend.

const STORAGE_KEY = "alsun:glossary:v1";
export const MAX_TERMS = 2000;
export const MAX_ARABIC_CHARS = 100;
export const MAX_TRANSLATION_CHARS = 200;
export const MAX_FILE_BYTES = 200 * 1024;

const ARABIC_LETTER = /[ء-ي]/;
const HEADER_WORDS = new Set(["المصطلح", "مصطلح", "العربية", "عربي", "arabic", "term"]);

// the same term written with other tashkeel, alef or yaa is the same term
const termKey = (arabic) =>
  arabic
    .replace(/[ً-ٰـ]/g, "")
    .replace(/[أإآٱ]/g, "ا")
    .replace(/ة/g, "ه")
    .replace(/ى/g, "ي")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");

// ---------- one term ----------

// what is wrong with this term, as a message for the user, or null
export function checkTerm(arabic, translation) {
  if (!arabic.trim()) return "اكتب المصطلح بالعربية";
  if (!ARABIC_LETTER.test(arabic)) return "المصطلح يجب أن يكون بالحروف العربية";
  if (!translation.trim()) return "اكتب الترجمة";
  if (arabic.trim().length > MAX_ARABIC_CHARS) return `المصطلح أطول من ${MAX_ARABIC_CHARS} حرفًا`;
  if (translation.trim().length > MAX_TRANSLATION_CHARS) return `الترجمة أطول من ${MAX_TRANSLATION_CHARS} حرفًا`;
  if (/[\r\n]/.test(arabic) || /[\r\n]/.test(translation)) return "المصطلح وترجمته يجب أن يكونا في سطر واحد";
  return null;
}

// ---------- the list, per language ----------

function readAll() {
  try {
    const all = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return all && typeof all === "object" ? all : {};
  } catch (error) {
    return {}; // not json, or no access to the storage
  }
}

function writeAll(all) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
    return true;
  } catch (error) {
    return false; // the storage is full, or blocked
  }
}

// [{arabic, translation}] of this language (a copy)
export function getGlossary(language) {
  const list = readAll()[language];
  return Array.isArray(list) ? list.map((item) => ({ arabic: item.arabic, translation: item.translation })) : [];
}

function saveGlossary(language, list) {
  const all = readAll();
  all[language] = list;
  return writeAll(all);
}

// returns {error} or {ok: true}. `replacingArabic` is the term being edited (it may keep its own spelling).
export function addTerm(language, arabic, translation, replacingArabic = null) {
  const problem = checkTerm(arabic, translation);
  if (problem) return { error: problem };

  const list = getGlossary(language);
  const editedKey = replacingArabic === null ? null : termKey(replacingArabic);
  const rest = list.filter((item) => termKey(item.arabic) !== editedKey);
  if (rest.some((item) => termKey(item.arabic) === termKey(arabic))) return { error: "هذا المصطلح موجود بالفعل، عدّله من القائمة" };
  if (rest.length >= MAX_TERMS) return { error: `لا يمكن إضافة أكثر من ${MAX_TERMS} مصطلح` };

  // an edited term stays where it was
  const entry = { arabic: arabic.trim(), translation: translation.trim() };
  const at = editedKey === null ? -1 : list.findIndex((item) => termKey(item.arabic) === editedKey);
  if (at >= 0) list[at] = entry;
  else list.push(entry);
  return saveGlossary(language, list) ? { ok: true } : { error: "تعذّر الحفظ في المتصفح" };
}

export function deleteTerm(language, arabic) {
  const key = termKey(arabic);
  return saveGlossary(language, getGlossary(language).filter((item) => termKey(item.arabic) !== key));
}

// ---------- csv ----------

// "a,b" / "a;b" / "a<tab>b", with "quoted, fields" and "" for a quote inside. Gives rows of cells.
export function parseCsv(text) {
  const clean = text.replace(/^﻿/, "");
  const firstLine = clean.split(/\r?\n/, 1)[0];
  const delimiter = firstLine.includes("\t")
    ? "\t"
    : (firstLine.match(/;/g) || []).length > (firstLine.match(/,/g) || []).length ? ";" : ",";

  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < clean.length; i++) {
    const char = clean[i];
    if (quoted) {
      if (char === '"' && clean[i + 1] === '"') { cell += '"'; i++; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === delimiter) { row.push(cell); cell = ""; }
    else if (char === "\n" || char === "\r") {
      if (char === "\r" && clean[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      rows.push(row); row = [];
    } else cell += char;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((cells) => cells.some((value) => value.trim() !== ""));
}

// Reads a csv file (two columns: the term, its translation; a first line with titles is fine).
// Nothing is saved if the file itself is wrong. Gives {error} or {added, skipped: [{line, reason}]}.
export async function importCsv(language, file) {
  if (!/\.(csv|txt)$/i.test(file.name)) return { error: "الملف يجب أن يكون بصيغة CSV" };
  if (file.size > MAX_FILE_BYTES) return { error: `حجم الملف أكبر من ${MAX_FILE_BYTES / 1024} كيلوبايت` };

  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
  } catch (error) {
    return { error: "الملف ليس بترميز UTF-8، احفظه من Excel بصيغة CSV UTF-8" };
  }

  const rows = parseCsv(text);
  if (!rows.length) return { error: "الملف فارغ" };
  // the file has the wrong shape (one column, or another separator): refused. A single bad line is only skipped, below
  if (!rows.some((cells) => cells.length >= 2)) return { error: "الملف يجب أن يحتوي على عمودين: المصطلح ثم الترجمة" };
  if (rows.length > MAX_TERMS + 1) return { error: `الملف فيه أكثر من ${MAX_TERMS} مصطلح` };

  // a first line with titles ("المصطلح, الترجمة") is not a term
  let firstLine = 1;
  const firstCell = rows[0][0].trim().toLowerCase();
  if (!ARABIC_LETTER.test(firstCell) || HEADER_WORDS.has(firstCell)) {
    rows.shift();
    firstLine = 2;
  }

  const list = getGlossary(language);
  const known = new Set(list.map((item) => termKey(item.arabic)));
  const skipped = [];
  let added = 0;
  rows.forEach((cells, index) => {
    const line = firstLine + index;
    if (cells.length < 2) return skipped.push({ line, reason: "ينقصه عمود الترجمة" });
    const arabic = cells[0].trim();
    const translation = cells[1].trim();
    const problem = checkTerm(arabic, translation);
    if (problem) return skipped.push({ line, reason: problem });
    if (known.has(termKey(arabic))) return skipped.push({ line, reason: "موجود بالفعل" });
    if (list.length >= MAX_TERMS) return skipped.push({ line, reason: "تجاوز الحد الأقصى" });
    known.add(termKey(arabic));
    list.push({ arabic, translation });
    added++;
  });
  if (added && !saveGlossary(language, list)) return { error: "تعذّر الحفظ في المتصفح" };
  return { added, skipped };
}

// the glossary as a csv text (with a BOM, so Excel reads the arabic right)
export function exportCsv(language) {
  const quote = (value) => `"${value.replace(/"/g, '""')}"`;
  const lines = getGlossary(language).map((item) => `${quote(item.arabic)},${quote(item.translation)}`);
  return `﻿"المصطلح","الترجمة"\r\n${lines.join("\r\n")}`;
}

// The terms of the glossary the translation did not use (the backend tells it in segment.glossary).
export function notAppliedTerms(segments) {
  return segments.flatMap((segment) => (segment.glossary || []).filter((term) => !term.used)).map((term) => term.arabic);
}

export function notAppliedMessage(terms) {
  const shown = terms.slice(0, 3).map((term) => `«${term}»`).join("، ");
  return `لم تُطبَّق ترجمة ${terms.length === 1 ? "مصطلح" : `${terms.length} مصطلحات`} من قاموسك: ${shown}${terms.length > 3 ? "…" : ""}. راجعها يدويًا.`;
}

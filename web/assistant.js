import { postJson } from "./api.js";
import { rowStates, joinDisplayText, copy } from "./state.js";
import { renderTranslated, syncRowFromDom } from "./translated-view.js";
import { getRowById, getSelectedRows } from "./selection.js";
import { showToast } from "./toast.js";
import { mountPenScribble } from "./pen-writer.js";
import { modelSettings } from "./settings-store.js";
import { getGlossary } from "./glossary-store.js";
import { fallbackMessage } from "./model-notice.js";
import { targetLanguage } from "./target-language.js";

// What the assistant works on:
//   {kind: "fragment", rowId, segId, start, end, text}   a part of one normal segment (from the tooltip)
//   {kind: "rows", rowIds}                               the checked rows
let context = null;
let pendingSelection = null; // what the tooltip will open the assistant with

const el = (id) => document.getElementById(id);
const closestElement = (node, selector) =>
  (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)?.closest(selector) ?? null;

// ---------- tooltip on the selection of the translated text ----------

function hideTooltip() {
  el("selection-tooltip").hidden = true;
  pendingSelection = null;
}

function offsetInSpan(span, container, offset) {
  const range = document.createRange();
  range.selectNodeContents(span);
  range.setEnd(container, offset);
  return range.toString().length;
}

// The tooltip shows only for a selection inside ONE normal part of the translated text.
// Any selection that touches the quran (the quotes included) gets no tooltip at all.
function readSelection() {
  const selection = window.getSelection();
  if (!selection.rangeCount || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);

  const cell = closestElement(range.commonAncestorContainer, ".translated-text");
  if (!cell) return null;
  const tr = cell.closest("tr");
  const state = rowStates.get(tr.dataset.id);
  if (!state || !state.segments.length) return null;
  if (cell.querySelector(".untyped")) return null; // the pen is still writing this text

  for (const quranSpan of cell.querySelectorAll(".seg-quran")) {
    if (range.intersectsNode(quranSpan)) return null;
  }

  const span = closestElement(range.startContainer, ".seg-normal");
  if (!span || span !== closestElement(range.endContainer, ".seg-normal")) return null;

  const text = range.toString();
  if (!text.trim()) return null;
  return {
    rowId: tr.dataset.id,
    segId: span.dataset.segId,
    start: offsetInSpan(span, range.startContainer, range.startOffset),
    end: offsetInSpan(span, range.endContainer, range.endOffset),
    text,
    rect: range.getBoundingClientRect(),
  };
}

function updateTooltip() {
  const found = readSelection();
  if (!found) return hideTooltip();

  pendingSelection = found;
  const tooltip = el("selection-tooltip");
  tooltip.hidden = false;
  const { width, height } = tooltip.getBoundingClientRect();
  const left = found.rect.left + found.rect.width / 2 - width / 2;
  const top = found.rect.top - height - 8;
  tooltip.style.left = `${Math.min(Math.max(8, left), window.innerWidth - width - 8)}px`;
  tooltip.style.top = `${top < 8 ? found.rect.bottom + 8 : top}px`;
}

// ---------- the assistant dock ----------

function addBubble(kind, text) {
  const bubble = document.createElement("div");
  bubble.className = `bubble bubble-${kind}`;
  bubble.textContent = text;
  el("assistant-log").append(bubble);
  el("assistant-log").scrollTop = el("assistant-log").scrollHeight;
  return bubble;
}

function showContext() {
  const chip = document.createElement("span");
  chip.className = "context-chip";
  const icon = document.createElement("i");
  const label = document.createElement("span");
  label.className = "context-label";
  if (context.kind === "fragment") {
    icon.className = "fa-solid fa-quote-right";
    label.textContent = "النص المحدد";
  } else {
    icon.className = "fa-solid fa-list-check";
    label.textContent = `الصفوف المحددة: ${context.rowIds.length}`;
  }
  chip.append(icon, label);
  el("assistant-context").replaceChildren(chip);
  if (context.kind === "fragment") {
    // the selected text is in its own box (not mixed with the Arabic label), cut at the end if it is long
    const quote = document.createElement("p");
    quote.className = "context-quote";
    quote.dir = "auto";
    quote.textContent = context.text;
    el("assistant-context").append(quote);
  }
}

function openDock(newContext) {
  // a new target is a new conversation; follow-up questions keep the same context and the same log
  el("assistant-log").replaceChildren();
  context = newContext;
  el("assistant-dock").hidden = false;
  showContext();
  el("assistant-instructions").focus();
}

// Full screen (like a canvas) and back: the dock grows over the whole page and shrinks to its place.
function setDockExpanded(expanded) {
  const dock = el("assistant-dock");
  const button = el("assistant-expand");
  dock.classList.toggle("is-expanded", expanded);
  document.body.classList.toggle("assistant-expanded", expanded);
  button.setAttribute("aria-pressed", String(expanded));
  button.setAttribute("aria-label", expanded ? "تصغير" : "تكبير");
  button.title = expanded ? "تصغير" : "تكبير";
  button.firstElementChild.className = expanded ? "fa-solid fa-compress" : "fa-solid fa-expand";
  if (expanded) el("assistant-instructions").focus();
}

function closeDock() {
  setDockExpanded(false);
  el("assistant-dock").hidden = true;
  context = null;
}

function setBusy(busy) {
  el("assistant-send").disabled = busy;
  el("assistant-instructions").disabled = busy;
}

// A suggestion is only applied after the user accepts it.
// ---------- word-level difference between the text before and after (to review a suggestion quickly) ----------
const MAX_DIFF_CELLS = 400000; // words before x words after; above this the marks are skipped (it would be slow)

function wordKey(word) {
  return word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "").toLowerCase() || word;
}

// Which words of the two texts are the same in both (longest common subsequence of words).
function sameWordMasks(beforeWords, afterWords) {
  const a = beforeWords.map(wordKey);
  const b = afterWords.map(wordKey);
  const keepA = new Array(a.length).fill(true);
  const keepB = new Array(b.length).fill(true);
  if (a.length * b.length > MAX_DIFF_CELLS) return { keepA, keepB };

  const table = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  keepA.fill(false);
  keepB.fill(false);
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      keepA[i] = keepB[j] = true;
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      i++;
    } else {
      j++;
    }
  }
  return { keepA, keepB };
}

// Writes the text into `target`; the words that are not in the common part are inside <span class="diff-mark">.
function fillWithMarks(target, text, keep) {
  const tokens = text.split(/(\s+)/);
  let wordNumber = 0;
  const flags = tokens.map((token) => (token === "" || /^\s+$/.test(token) ? null : !keep[wordNumber++]));
  // the space between two changed words is marked too, so the mark is one block
  flags.forEach((flag, k) => {
    if (flag !== null || tokens[k] === "") return;
    let before = null;
    for (let p = k - 1; p >= 0 && before === null; p--) before = flags[p];
    let after = null;
    for (let n = k + 1; n < flags.length && after === null; n++) after = flags[n];
    flags[k] = before === true && after === true;
  });

  let run = null;
  const flush = () => {
    if (!run) return;
    if (run.changed) {
      const mark = document.createElement("span");
      mark.className = "diff-mark";
      mark.textContent = run.text;
      target.append(mark);
    } else {
      target.append(document.createTextNode(run.text));
    }
    run = null;
  };
  tokens.forEach((token, k) => {
    if (token === "") return;
    if (!run || run.changed !== flags[k]) {
      flush();
      run = { changed: flags[k], text: "" };
    }
    run.text += token;
  });
  flush();
}

function diffBox(label, className, text, keep) {
  const boxElement = document.createElement("div");
  boxElement.className = `diff-box ${className}`;
  const tag = document.createElement("span");
  tag.className = "diff-tag";
  tag.textContent = label;
  const body = document.createElement("p");
  body.className = "diff-text";
  body.dir = "auto"; // the text is in the target language (left to right); the label is not inside it
  fillWithMarks(body, text, keep);
  boxElement.append(tag, body);
  return boxElement;
}

// items: [{ title: "الصف 1" (optional), before, after }]
function addSuggestion({ title, items, onAccept }) {
  const box = document.createElement("div");
  box.className = "bubble bubble-assistant suggestion";
  const heading = document.createElement("strong");
  heading.className = "suggestion-title";
  heading.textContent = title;
  box.append(heading);

  const list = document.createElement("div");
  list.className = "suggestion-items";
  items.forEach(({ title: rowTitle, before, after }) => {
    const item = document.createElement("div");
    item.className = "suggestion-item";
    if (rowTitle) {
      const rowTag = document.createElement("span");
      rowTag.className = "suggestion-row-tag";
      rowTag.textContent = rowTitle;
      item.append(rowTag);
    }
    const { keepA, keepB } = sameWordMasks(
      before.split(/\s+/).filter(Boolean),
      after.split(/\s+/).filter(Boolean),
    );
    item.append(diffBox("قبل", "diff-before", before, keepA), diffBox("بعد", "diff-after", after, keepB));
    list.append(item);
  });
  box.append(list);

  const actions = document.createElement("div");
  actions.className = "suggestion-actions";
  const accept = document.createElement("button");
  accept.type = "button";
  accept.className = "btn btn-sm btn-success";
  accept.textContent = "قبول";
  const reject = document.createElement("button");
  reject.type = "button";
  reject.className = "btn btn-sm btn-outline-secondary";
  reject.textContent = "رفض";
  actions.append(accept, reject);
  box.append(actions);

  const finish = (message) => {
    actions.replaceChildren(Object.assign(document.createElement("span"), { textContent: message }));
  };
  reject.addEventListener("click", () => finish("تم الرفض"));
  accept.addEventListener("click", async () => {
    accept.disabled = reject.disabled = true;
    try {
      const undo = await onAccept();
      finish("تم التطبيق");
      if (undo) {
        const undoButton = document.createElement("button");
        undoButton.type = "button";
        undoButton.className = "btn btn-sm btn-link";
        undoButton.textContent = "تراجع";
        undoButton.addEventListener("click", () => {
          undo();
          actions.replaceChildren(Object.assign(document.createElement("span"), { textContent: "تم التراجع" }));
        });
        actions.append(undoButton);
      }
    } catch (error) {
      accept.disabled = reject.disabled = false;
      showToast(error.message, true);
    }
  });

  el("assistant-log").append(box);
  el("assistant-log").scrollTop = el("assistant-log").scrollHeight;
}

// ---------- a part of one segment ----------

async function suggestForFragment(instructions) {
  const row = getRowById(context.rowId);
  const state = rowStates.get(context.rowId);
  if (!row || !state) throw new Error("هذا الصف تم حذفه");
  syncRowFromDom(row);
  const segment = state.segments.find((item) => item.id === context.segId);
  if (!segment || segment.text.slice(context.start, context.end) !== context.text) {
    throw new Error("تغيّر النص بعد التحديد، حدّد الجزء مرة أخرى");
  }

  const { replacement, fallbacks } = await postJson("/assistant/suggest-fragment", {
    segment,
    fragment_start: context.start,
    fragment_end: context.end,
    instructions,
    glossary: getGlossary(targetLanguage()), // the assistant keeps the approved terms
    ...modelSettings(),
  });

  if (fallbacks?.length) addBubble("system", fallbackMessage(fallbacks));
  const fragment = { ...context }; // the part this suggestion was made for
  addSuggestion({
    title: "اقتراح لتعديل الجزء المحدد",
    items: [{ before: fragment.text, after: replacement }],
    onAccept: () => applyFragment(fragment, replacement),
  });
}

async function applyFragment(fragment, replacement) {
  const row = getRowById(fragment.rowId);
  const state = rowStates.get(fragment.rowId);
  if (!row || !state) throw new Error("هذا الصف تم حذفه");
  syncRowFromDom(row);
  const segment = state.segments.find((item) => item.id === fragment.segId);
  if (!segment) throw new Error("تغيّر النص بعد التحديد، حدّد الجزء مرة أخرى");

  const { segment: newSegment } = await postJson("/assistant/apply-fragment", {
    segment,
    fragment_start: fragment.start,
    fragment_end: fragment.end,
    expected_text: fragment.text,
    replacement,
  });

  const before = { segments: copy(state.segments), aiEdited: state.aiEdited };
  state.segments = state.segments.map((item) => (item.id === newSegment.id ? newSegment : item));
  state.aiEdited = true;
  renderTranslated(row);

  // the next question of the chat is about the new text
  const leadingSpaces = fragment.text.length - fragment.text.trimStart().length;
  const newText = replacement.trim();
  const previousContext = context && context.rowId === fragment.rowId ? { ...context } : null;
  if (previousContext && previousContext.start === fragment.start) {
    context = { ...context, start: fragment.start + leadingSpaces, end: fragment.start + leadingSpaces + newText.length, text: newText };
    showContext();
  }

  return () => {
    state.segments = before.segments;
    state.aiEdited = before.aiEdited;
    renderTranslated(row);
    if (previousContext) {
      context = previousContext;
      showContext();
    }
  };
}

// ---------- the checked rows ----------

async function suggestForRows(instructions) {
  const rows = context.rowIds.map(getRowById).filter(Boolean);
  if (!rows.length) throw new Error("الصفوف المحددة تم حذفها");
  rows.forEach(syncRowFromDom);
  const translatedRows = rows.filter((tr) => rowStates.get(tr.dataset.id).segments.length);
  if (!translatedRows.length) throw new Error("ترجم الصفوف المحددة أولاً");

  const sentSegments = translatedRows.map((tr) => copy(rowStates.get(tr.dataset.id).segments));
  const answer = await postJson("/assistant/modify-rows", {
    paragraphs: sentSegments, instructions, glossary: getGlossary(targetLanguage()), ...modelSettings(),
  });

  if (answer.fallbacks?.length) addBubble("system", fallbackMessage(answer.fallbacks));
  const quranOnly = answer.quran_only_rows.length;
  const items = [];
  // rows the model could not edit without changing an approved term of the glossary: they stay as they are
  const blocked = new Set(answer.glossary_blocked_rows || []);
  answer.unchanged_rows = [];
  answer.rows.forEach((newRow, index) => {
    if (answer.quran_only_rows.includes(index)) return;
    const oldText = joinDisplayText(sentSegments[index]);
    if (blocked.has(index) && newRow.paragraph === oldText) {
      answer.unchanged_rows.push(index);
      return;
    }
    items.push({ title: `الصف ${index + 1}`, before: oldText, after: newRow.paragraph });
  });
  if (quranOnly) {
    addBubble("system", `${quranOnly} من الصفوف المحددة آيات فقط، والآيات لا تُعدَّل.`);
  }
  if (blocked.size) {
    addBubble("system", `${blocked.size} من الصفوف لم يُعدَّل (أو لم يُعدَّل كله) لأن التعديل كان سيغيّر مصطلحًا معتمدًا من قاموسك.`);
  }
  if (!items.length) return;

  addSuggestion({
    title: "اقتراح لتعديل الصفوف المحددة",
    items,
    onAccept: () => applyToRows(translatedRows, sentSegments, answer),
  });
}

function applyToRows(trs, sentSegments, answer) {
  if (trs.some((tr) => !rowStates.has(tr.dataset.id))) throw new Error("تم حذف أحد الصفوف بعد الاقتراح");
  // refuse if a row changed after the suggestion was made
  trs.forEach((tr, index) => {
    syncRowFromDom(tr);
    if (JSON.stringify(rowStates.get(tr.dataset.id).segments) !== JSON.stringify(sentSegments[index])) {
      throw new Error("تغيّرت الصفوف بعد الاقتراح، اطلب التعديل مرة أخرى");
    }
  });

  const before = [];
  trs.forEach((tr, index) => {
    if (answer.quran_only_rows.includes(index) || answer.unchanged_rows.includes(index)) return;
    const state = rowStates.get(tr.dataset.id);
    before.push({ tr, segments: copy(state.segments), aiEdited: state.aiEdited });
    state.segments = answer.rows[index].segments;
    state.aiEdited = true;
    renderTranslated(tr);
  });

  return () => {
    before.forEach(({ tr, segments, aiEdited }) => {
      const state = rowStates.get(tr.dataset.id);
      state.segments = segments;
      state.aiEdited = aiEdited;
      renderTranslated(tr);
    });
  };
}

// ---------- the chat ----------

async function send(ready = null) {
  // ready = {instructions, shown}: an instruction from the row menu (the user sees the label, the model gets the instruction)
  const instructions = ready ? ready.instructions : el("assistant-instructions").value.trim();
  if (!instructions || !context || el("assistant-send").disabled) return;

  addBubble("user", ready ? ready.shown : instructions);
  el("assistant-instructions").value = "";
  setBusy(true);
  const waiting = addBubble("system", "");
  waiting.classList.add("bubble-waiting");
  const stopPen = mountPenScribble(waiting, { sweep: 60 });
  try {
    if (context.kind === "fragment") await suggestForFragment(instructions);
    else await suggestForRows(instructions);
  } catch (error) {
    addBubble("error", error.message);
  } finally {
    stopPen();
    waiting.remove();
    setBusy(false);
    el("assistant-instructions").focus();
  }
}

// From the row menu: the assistant opens on this row and answers a ready instruction.
// The answer is still only a suggestion that the user accepts or rejects.
export function askAssistantAboutRow(tr, label, instructions) {
  openDock({ kind: "rows", rowIds: [tr.dataset.id] });
  return send({ instructions, shown: label });
}

// A row was deleted: if the assistant was working on it, it stops.
export function forgetDeletedRow(rowId) {
  if (!context) return;
  if (context.kind === "fragment" && context.rowId === rowId) return closeDock();
  if (context.kind === "rows") {
    context.rowIds = context.rowIds.filter((id) => id !== rowId);
    if (context.rowIds.length) showContext();
    else closeDock();
  }
}

export function refreshAssistantButton() {
  const rows = getSelectedRows();
  const button = el("open-assistant-rows");
  const translated = rows.filter((tr) => rowStates.get(tr.dataset.id).segments.length);
  button.disabled = translated.length === 0;
  button.title = translated.length
    ? "المساعد الذكي على الصفوف المحددة"
    : "حدّد صفًا مترجمًا واحدًا على الأقل";
}

export function initAssistant() {
  const tooltipButton = el("selection-tooltip").querySelector("button");
  // mousedown would clear the selection before the click
  tooltipButton.addEventListener("mousedown", (event) => event.preventDefault());
  tooltipButton.addEventListener("click", () => {
    if (!pendingSelection) return;
    const { rowId, segId, start, end, text } = pendingSelection;
    syncRowFromDom(getRowById(rowId));
    hideTooltip();
    openDock({ kind: "fragment", rowId, segId, start, end, text });
  });

  let scheduled = false;
  document.addEventListener("selectionchange", () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      updateTooltip();
    });
  });
  window.addEventListener("scroll", hideTooltip, true);

  el("open-assistant-rows").addEventListener("click", () => {
    const rowIds = getSelectedRows().map((tr) => tr.dataset.id);
    if (rowIds.length) openDock({ kind: "rows", rowIds });
  });
  el("assistant-close").addEventListener("click", closeDock);
  el("assistant-expand").addEventListener("click", () => {
    setDockExpanded(!el("assistant-dock").classList.contains("is-expanded"));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && el("assistant-dock").classList.contains("is-expanded")) setDockExpanded(false);
  });
  el("assistant-send").addEventListener("click", () => send());
  el("assistant-instructions").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      send();
    }
  });
}

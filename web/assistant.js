import { postJson } from "./api.js";
import { rowStates, displayParts, copy } from "./state.js";
import { renderTranslated, syncRowFromDom } from "./translated-view.js";
import { getRowById, getSelectedRows } from "./selection.js";
import { showToast } from "./toast.js";

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
  const box = el("assistant-context");
  if (context.kind === "fragment") {
    box.textContent = `النص المحدد: «${context.text}»`;
  } else {
    box.textContent = `الصفوف المحددة: ${context.rowIds.length}`;
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

function closeDock() {
  el("assistant-dock").hidden = true;
  context = null;
}

function setBusy(busy) {
  el("assistant-send").disabled = busy;
  el("assistant-instructions").disabled = busy;
}

// A suggestion is only applied after the user accepts it.
function addSuggestion({ title, lines, onAccept }) {
  const box = document.createElement("div");
  box.className = "bubble bubble-assistant suggestion";
  const heading = document.createElement("strong");
  heading.textContent = title;
  box.append(heading);

  lines.forEach(({ label, text, className }) => {
    const row = document.createElement("div");
    row.className = `suggestion-line ${className}`;
    row.textContent = `${label} ${text}`;
    box.append(row);
  });

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
  syncRowFromDom(row);
  const segment = state.segments.find((item) => item.id === context.segId);
  if (!segment || segment.text.slice(context.start, context.end) !== context.text) {
    throw new Error("تغيّر النص بعد التحديد، حدّد الجزء مرة أخرى");
  }

  const { replacement } = await postJson("/assistant/suggest-fragment", {
    segment,
    fragment_start: context.start,
    fragment_end: context.end,
    instructions,
  });

  const fragment = { ...context }; // the part this suggestion was made for
  addSuggestion({
    title: "اقتراح لتعديل الجزء المحدد",
    lines: [
      { label: "قبل:", text: fragment.text, className: "line-before" },
      { label: "بعد:", text: replacement, className: "line-after" },
    ],
    onAccept: () => applyFragment(fragment, replacement),
  });
}

async function applyFragment(fragment, replacement) {
  const row = getRowById(fragment.rowId);
  const state = rowStates.get(fragment.rowId);
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
  rows.forEach(syncRowFromDom);
  const translatedRows = rows.filter((tr) => rowStates.get(tr.dataset.id).segments.length);
  if (!translatedRows.length) throw new Error("ترجم الصفوف المحددة أولاً");

  const sentSegments = translatedRows.map((tr) => copy(rowStates.get(tr.dataset.id).segments));
  const answer = await postJson("/assistant/modify-rows", { paragraphs: sentSegments, instructions });

  const quranOnly = answer.quran_only_rows.length;
  const lines = [];
  answer.rows.forEach((newRow, index) => {
    if (answer.quran_only_rows.includes(index)) return;
    const oldText = displayParts(sentSegments[index]).map((part) => part.text).join(" ");
    lines.push({ label: `الصف ${index + 1} قبل:`, text: oldText, className: "line-before" });
    lines.push({ label: "بعد:", text: newRow.paragraph, className: "line-after" });
  });
  if (quranOnly) {
    addBubble("system", `${quranOnly} من الصفوف المحددة آيات فقط، والآيات لا تُعدَّل.`);
  }
  if (!lines.length) return;

  addSuggestion({
    title: "اقتراح لتعديل الصفوف المحددة",
    lines,
    onAccept: () => applyToRows(translatedRows, sentSegments, answer),
  });
}

function applyToRows(trs, sentSegments, answer) {
  // refuse if a row changed after the suggestion was made
  trs.forEach((tr, index) => {
    syncRowFromDom(tr);
    if (JSON.stringify(rowStates.get(tr.dataset.id).segments) !== JSON.stringify(sentSegments[index])) {
      throw new Error("تغيّرت الصفوف بعد الاقتراح، اطلب التعديل مرة أخرى");
    }
  });

  const before = [];
  trs.forEach((tr, index) => {
    if (answer.quran_only_rows.includes(index)) return;
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

async function send() {
  const instructions = el("assistant-instructions").value.trim();
  if (!instructions || !context) return;

  addBubble("user", instructions);
  el("assistant-instructions").value = "";
  setBusy(true);
  const waiting = addBubble("system", "جارٍ التفكير...");
  try {
    if (context.kind === "fragment") await suggestForFragment(instructions);
    else await suggestForRows(instructions);
  } catch (error) {
    addBubble("error", error.message);
  } finally {
    waiting.remove();
    setBusy(false);
    el("assistant-instructions").focus();
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
  el("assistant-send").addEventListener("click", send);
  el("assistant-instructions").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      send();
    }
  });
}

// Reads the translated cell after the user typed in it and gives back the segments it means.
//
// The rules about the ayahs:
//   - the text of an ayah can't be changed: if it is not exactly what we wrote, the edit is refused
//   - the whole ayah can be deleted: the user may write anything in its place
// A deleted ayah is not forgotten: its segment becomes a normal one ("replaced_quran" remembers which ayah it was
// and "original" keeps its arabic words), so the words of the original text still match the segments.

const quoted = (segment) => `"${segment.text}"`;
const isSegmentSpan = (node) => node.nodeType === Node.ELEMENT_NODE && node.classList.contains("seg");
const isTypedText = (node) => node.nodeType === Node.TEXT_NODE && node.nodeValue.trim() !== "";

function describeAyah(segment) {
  return {
    aya_name: segment.aya_name,
    aya_start: segment.aya_start,
    aya_end: segment.aya_end,
    original: segment.original,
  };
}

// a deleted ayah that nobody wrote anything instead of
function emptyReplacement(segment) {
  return { id: segment.id, type: "normal", text: "", original: segment.original, replaced_quran: [describeAyah(segment)] };
}

function nextFreeId(segments) {
  const numbers = segments.map((segment) => Number(/^seg_(\d+)$/.exec(segment.id)?.[1] ?? 0));
  return Math.max(0, ...numbers) + 1;
}

// returns {refused: true} or {segments, changedStructure, deletedAyahs}
export function rebuildSegmentsFromCell(segments, cell) {
  const nodes = [...cell.childNodes];
  const order = new Map(segments.map((segment, index) => [segment.id, index]));
  const byId = new Map(segments.map((segment) => [segment.id, segment]));
  const presentIds = new Set(nodes.filter(isSegmentSpan).map((span) => span.dataset.segId));

  // an ayah that is still there but with another text: refused
  for (const span of nodes.filter(isSegmentSpan)) {
    const segment = byId.get(span.dataset.segId);
    if (segment?.type === "quran" && span.textContent !== quoted(segment)) return { refused: true };
  }

  const deleted = segments.filter((segment) => segment.type === "quran" && !presentIds.has(segment.id));
  const used = new Set(); // deleted ayahs already placed in the result
  const result = [];
  let lastIndex = -1; // position (in the old order) of the last part seen
  let nextNumber = nextFreeId(segments);
  let changedStructure = deleted.length > 0;

  // the deleted ayahs that were between the last part seen and the one at `beforeIndex`, and nobody wrote instead of them
  const placeEmptyReplacements = (beforeIndex) => {
    for (const segment of deleted) {
      const index = order.get(segment.id);
      if (!used.has(segment.id) && index > lastIndex && index < beforeIndex) {
        result.push(emptyReplacement(segment));
        used.add(segment.id);
      }
    }
  };

  const indexOfNextPart = (position) => {
    for (let i = position + 1; i < nodes.length; i++) {
      if (isSegmentSpan(nodes[i]) && byId.has(nodes[i].dataset.segId)) return order.get(nodes[i].dataset.segId);
    }
    return Infinity;
  };

  nodes.forEach((node, position) => {
    if (isSegmentSpan(node)) {
      const segment = byId.get(node.dataset.segId);
      if (!segment) return;
      const index = order.get(segment.id);
      placeEmptyReplacements(index);
      result.push(segment.type === "normal" ? { ...segment, text: node.textContent } : segment);
      lastIndex = index;
    } else if (isTypedText(node)) {
      // text typed outside every part: a new normal part; if it sits where an ayah was deleted, it is that ayah's replacement
      const nextIndex = indexOfNextPart(position);
      const replacedHere = deleted.filter(
        (segment) => !used.has(segment.id) && order.get(segment.id) > lastIndex && order.get(segment.id) < nextIndex
      );
      replacedHere.forEach((segment) => used.add(segment.id));
      result.push({
        id: `seg_${nextNumber++}`,
        type: "normal",
        text: node.nodeValue.trim(),
        original: replacedHere.map((segment) => segment.original).join(" "),
        ...(replacedHere.length ? { replaced_quran: replacedHere.map(describeAyah) } : {}),
      });
      changedStructure = true;
    }
  });
  placeEmptyReplacements(Infinity);

  return { segments: result, changedStructure, deletedAyahs: deleted.length };
}

export const EDIT_REFUSED_MESSAGE = "لا يمكن تعديل نص الآية، لكن يمكنك حذفها كاملة وكتابة ما تشاء مكانها";
export const AYAH_DELETED_MESSAGE = "تم حذف ترجمة الآية. أي نص تكتبه مكانها يُحفظ كنص من عندك";

// ---------- the keyboard in the translated cell ----------
// The text of an ayah can't be edited, so a click puts the caret inside it but Backspace would do nothing.
// So: Backspace / Delete with the caret inside an ayah, or right next to it, deletes the whole ayah.
// Typing inside an ayah is refused with a message.

const AYAH = ".seg-quran";
const parentElement = (node) => (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement);

// the ayah the caret is touching for this key (inside it, or next to it in the direction of the key)
function ayahTouchedByCaret(range, key) {
  const inside = parentElement(range.startContainer)?.closest(AYAH);
  if (inside) return inside;

  const { startContainer: node, startOffset: offset } = range;
  let neighbor = null;
  if (node.nodeType === Node.TEXT_NODE) {
    if (key === "Backspace" && offset === 0) neighbor = node.previousSibling;
    if (key === "Delete" && offset === node.nodeValue.length) neighbor = node.nextSibling;
  } else {
    neighbor = key === "Backspace" ? node.childNodes[offset - 1] : node.childNodes[offset];
  }
  return neighbor?.nodeType === Node.ELEMENT_NODE && neighbor.matches(AYAH) ? neighbor : null;
}

export function protectAyahsInCell(cell, { onRefused }) {
  cell.addEventListener("keydown", (event) => {
    if (event.key !== "Backspace" && event.key !== "Delete") return;
    const selection = window.getSelection();
    if (!selection.rangeCount || !cell.contains(selection.anchorNode)) return;
    const range = selection.getRangeAt(0);

    const touched = new Set([...cell.querySelectorAll(AYAH)].filter((ayah) => range.intersectsNode(ayah)));
    if (range.collapsed) {
      const next = ayahTouchedByCaret(range, event.key);
      if (next) touched.add(next);
    }
    if (!touched.size) return; // no ayah involved: the browser does what it always does

    event.preventDefault();
    // the whole ayah goes, never a part of it
    touched.forEach((ayah) => ayah.remove());
    if (!range.collapsed) range.deleteContents();
    range.collapse(true);
    // a space where the ayah was: the user types in it
    const place = document.createTextNode(" ");
    range.insertNode(place);
    selection.collapse(place, 1);
  });

  cell.addEventListener("beforeinput", (event) => {
    if (!event.inputType.startsWith("insert")) return;
    const selection = window.getSelection();
    if (!selection.rangeCount || !selection.isCollapsed || !cell.contains(selection.anchorNode)) return;
    if (parentElement(selection.anchorNode)?.closest(AYAH)) {
      event.preventDefault();
      onRefused();
    }
  });
}

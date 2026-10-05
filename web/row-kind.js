// The kind of the pdf block a row was made of. The OCR gives every block a kind:
// Text, SectionHeader, PageHeader, PageFooter, Footnote. In the export the kind decides the
// element the row becomes, so a section header is a heading and a footnote is small.
//
// The kinds are kept by block id, not by row: a merged row shows several blocks and a merge can
// be undone at any moment, so a row asks its blocks every time instead of carrying the kind with it.

const kindsByBlockId = new Map();

// Text is what a block without a kind of its own is: the ordinary body of the book.
const BODY_KIND = "Text";

export function rememberBlockKind(blockId, kind) {
  if (blockId && kind) kindsByBlockId.set(blockId, kind);
}

// A merged row takes the kind of its blocks when they all agree; when they don't, it is body
// text, which is what a header merged with the paragraph under it really is.
export function kindOfRow(state) {
  const kinds = (state.source_blocks || []).map((block) => kindsByBlockId.get(block.id)).filter(Boolean);
  if (!kinds.length) return BODY_KIND;
  const [first] = kinds;
  return kinds.every((kind) => kind === first) ? first : BODY_KIND;
}
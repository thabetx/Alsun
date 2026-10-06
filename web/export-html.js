import { displayParts, joinDisplayText } from "./state.js";
import { kindOfRow } from "./row-kind.js";

// The book as one document. The rows in the order of the table, each one the element its pdf block
// was: a section header is a heading, a footnote is small, an ordinary block is a paragraph.
// The quran parts keep their quotes and are marked, so they can be told from the translation
// around them. The same html is what the preview shows, what the pdf is printed from and what word
// opens, so what the user sees is what he downloads.

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// The element of each kind of block, and the class that gives it its size.
// Every kind is a h2 or a p: word reads the document too, and it only keeps those two.
const TAG_BY_KIND = {
  SectionHeader: "h2",
  PageHeader: "p",
  PageFooter: "p",
  Footnote: "p",
};
const CLASS_BY_KIND = {
  PageHeader: "page-header",
  PageFooter: "page-footer",
  Footnote: "footnote",
};

// The row as one line of text. When the user is typing in a cell, the parts of the cell are used
// instead of the segments (export-data.js puts them in liveParts): what he wrote only reaches the
// segments when he leaves the cell, and the preview must not wait for that.
export function rowText(row) {
  return joinDisplayText(row.liveParts || row.segments).replace(/\s+/g, " ").trim();
}

// What goes into the book: the rows that have a translation. A row that is not translated yet is
// not a hole in the book, it is simply not written yet.
export function translatedRows(rows) {
  return rows.filter((row) => rowText(row));
}

function partsToHtml(parts) {
  return parts
    .map((part) => {
      if (!part.text) return "";
      const text = escapeHtml(part.text);
      return part.type === "quran" ? `<span class="quran">${text}</span>` : text;
    })
    .filter(Boolean)
    .join(" ");
}

export function rowToHtml(row) {
  const inner = partsToHtml(row.liveParts || displayParts(row.segments));
  if (!inner.trim()) return "";
  const kind = kindOfRow(row);
  const tag = TAG_BY_KIND[kind] || "p";
  const className = CLASS_BY_KIND[kind];
  // data-row is the row this element was written from, so the preview can be connected to the
  // table and to the pdf: hovering a row brings its place in the book, and the other way round.
  const marker = ` data-row="${escapeHtml(row.id)}"`;
  return `<${tag}${className ? ` class="${className}"` : ""}${marker}>${inner}</${tag}>`;
}

export function bookBodyHtml(rows) {
  return rows.map(rowToHtml).filter(Boolean).join("\n");
}

// markdown has a size for a heading and nothing else, so the small blocks stay plain lines.
const MARKDOWN_BY_KIND = { SectionHeader: "## ", PageHeader: "_", PageFooter: "_" };

export function rowToMarkdown(row) {
  const text = rowText(row);
  if (!text) return "";
  const marker = MARKDOWN_BY_KIND[kindOfRow(row)];
  if (marker === "_") return `_${text}_`;
  return marker ? `${marker}${text}` : text;
}

export function bookMarkdown(rows) {
  const body = rows.map(rowToMarkdown).filter(Boolean).join("\n\n");
  return body ? `${body}\n` : "";
}

// One stylesheet for the preview, the pdf and the word document. It has to look like a printed
// page, since the size of each element here is what the reader sees in the book.
const PAGE_STYLE = `@page { size: A4; margin: 20mm 18mm; }
body { margin: 0; background: #fff; color: #1a1a1a; font-family: "EB Garamond", "Amiri", "Times New Roman", Georgia, serif; font-size: 15pt; line-height: 1.7; }
.page { max-width: 46em; margin: 0 auto; padding: 30px 34px; }
p { margin: 0 0 .85em; text-align: justify; hyphens: auto; }
h2 { margin: 1.5em 0 .6em; font-size: 1.5em; font-weight: 800; line-height: 1.4; }
p.page-header { margin: 0 0 1.5em; padding-bottom: .5em; border-bottom: 1px solid #d8d2c4; font-size: .8em; color: #6f6f6f; text-align: center; }
p.page-footer { margin: 1.6em 0 0; padding-top: .5em; border-top: 1px solid #d8d2c4; font-size: .8em; color: #6f6f6f; text-align: center; }
p.footnote { margin: .5em 0 .9em; font-size: .85em; color: #4a4a4a; text-align: start; }
.quran { font-style: italic; }
p.empty { color: #6f6f6f; font-style: italic; text-align: center; }
/* the row under the mouse is marked the same gold the table marks it with, so the eye that follows
   the row from one panel to the other never loses it */
.row-hover { background: #f8e6bf; border-radius: 2px; box-shadow: 0 0 0 4px #f8e6bf; }
@media print { .page { max-width: none; padding: 0; } }`;

// A book face: Garamond, cut in the sixteenth century and still the face of printed books. The heavy
// weight carries the section headings, the italic is kept for the quran parts. Amiri is behind it for
// arabic, and the ordinary serif after that so the document still reads well without the network.
const FONT_LINK =
  '<link rel="preconnect" href="https://fonts.googleapis.com">' +
  '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' +
  '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400..800;1,400&display=swap">';

// The preview is the same document, drawn edge to edge in its panel: the margins that make a
// printed page readable would only take the room away from the user here, who reads it on screen.
// The narrow panel is not a page of paper: the margins a printed page needs would eat a third of
// it, so the text is given a comfortable margin and no more.
const PREVIEW_STYLE = "body.preview { background: #f7f4ec; } body.preview .page { max-width: none; padding: 16px 22px; }";

export function bookHtml(rows, { title = "", lang = "en", emptyNote = "", preview = false } = {}) {
  const body = bookBodyHtml(rows) || (emptyNote ? `<p class="empty">${escapeHtml(emptyNote)}</p>` : "");
  return `<!DOCTYPE html>
<html lang="${lang}" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
${FONT_LINK}
<style>${PAGE_STYLE}${preview ? PREVIEW_STYLE : ""}</style>
</head>
<body${preview ? ' class="preview"' : ""}>
<div class="page">
${body}
</div>
</body>
</html>`;
}

// Word opens an html file as a document, so it gets the same html with the namespaces and the
// charset it expects. A .doc written this way is really html with a word extension, which is the
// only way to give the user a word document from a page without a library.
export function bookWordHtml(rows, { title = "", lang = "en" } = {}) {
  return bookHtml(rows, { title, lang })
    .replace("<html ", '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" ')
    .replace(
      '<meta charset="utf-8">',
      '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n' +
        "<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom></w:WordDocument></xml><![endif]-->"
    );
}
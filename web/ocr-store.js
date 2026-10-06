// Keeps the OCR result of a book in localStorage, next to the work of the user (see saved-work.js),
// so opening a book again does not make the server run the OCR and the llm again.
// The stamp is "modified" of the book (GET /books/{id}): the moment the pdf itself last changed. A
// file replaced under the same name is a different book, and what was stored for the old one must
// not be shown. Without a stamp the stored copy is not trusted at all.

const FORMAT_VERSION = 1;

const keyOf = (book) => `alsun:ocr:v${FORMAT_VERSION}:${book}`;

// The stored OCR of this book, or null (nothing stored, or the pdf changed since it was).
export function loadOcr(book, stamp) {
  if (!stamp) return null; // no way to tell a replaced pdf apart
  try {
    const saved = JSON.parse(localStorage.getItem(keyOf(book)));
    if (!saved || saved.version !== FORMAT_VERSION || saved.stamp !== stamp) return null;
    const data = saved.data;
    // a read that stopped in the middle is not worth keeping: it would be shown as the whole book
    return data && Array.isArray(data.children) && data.children.length && !data.error ? data : null;
  } catch (error) {
    return null; // not json, or no access to the storage
  }
}

// returns true when it was kept; false when the storage is full or blocked, which only means the
// next opening of the book asks the server again
export function saveOcr(book, stamp, data) {
  try {
    localStorage.setItem(keyOf(book), JSON.stringify({ version: FORMAT_VERSION, stamp, data }));
    return true;
  } catch (error) {
    return false;
  }
}


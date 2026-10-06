// Makes Arabic text comparable, so a search finds the word however it was written.
// Same idea as normalize_arabic() in python/arabic_text.py (used for the glossary), a little wider for searching.

// tashkeel (fatha ... sukun, shadda), the small alef above, tatweel, and the small marks of the Quran text
const MARKS = /[ً-ٰٟـۖ-ۭ]/g;

export function normalizeArabic(text) {
  return String(text ?? "")
    .normalize("NFKC") // the joined forms of a letter (and the ligature of the word Allah) become normal letters
    .replace(MARKS, "")
    .replace(/[أإآٱ]/g, "ا") // every kind of alef
    .replace(/[ؤئء]/g, "") // hamza (alone, or on waw / yaa): مسؤول = مسئول = مسول
    .replace(/ة/g, "ه") // taa marbuta = haa
    .replace(/[ىی]/g, "ي") // alef maqsura (and the persian yaa) = yaa
    .replace(/ک/g, "ك") // the persian kaf
    .replace(/[٠-٩]/g, (digit) => String(digit.charCodeAt(0) - 0x0660)) // arabic-indic digits
    .replace(/[۰-۹]/g, (digit) => String(digit.charCodeAt(0) - 0x06f0)) // persian digits
    .toLowerCase();
}

// Every word of the search must be in the text, in any order. `normalizedText` is already normalized
// (done once when the row is made), so a key press only normalizes the few words typed.
export function matchesSearch(normalizedText, query) {
  const words = normalizeArabic(query).split(/\s+/).filter(Boolean);
  return words.every((word) => normalizedText.includes(word));
}

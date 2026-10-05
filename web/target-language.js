// The language the user chose in the home page (saved there in sessionStorage when "ابدأ الترجمة" is pressed).
// Same names as QURAN_FILES in python/quran_detect.py.
const DEFAULT_LANGUAGE = "English";

// how the language is called in the screen (the keys are the names the backend knows)
const ARABIC_NAMES = {
  English: "الإنجليزية",
  French: "الفرنسية",
  German: "الألمانية",
  Turkish: "التركية",
  Spanish: "الإسبانية",
  Indonesian: "الإندونيسية",
};

// the code of the language, for the documents we write out (the lang attribute of the html)
const CODES = {
  English: "en",
  French: "fr",
  German: "de",
  Turkish: "tr",
  Spanish: "es",
  Indonesian: "id",
};

export function targetLanguageInArabic() {
  return ARABIC_NAMES[targetLanguage()] ?? targetLanguage();
}

export function targetLanguageCode() {
  return CODES[targetLanguage()] ?? "en";
}

export function targetLanguage() {
  try {
    return JSON.parse(sessionStorage.getItem("alsun_upload"))?.lang || DEFAULT_LANGUAGE;
  } catch (error) {
    return DEFAULT_LANGUAGE;
  }
}

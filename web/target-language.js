// The language the user chose in the home page (saved there in sessionStorage when "ابدأ الترجمة" is pressed).
// Same names as QURAN_FILES in python/quran_detect.py.
const DEFAULT_LANGUAGE = "English";

export function targetLanguage() {
  try {
    return JSON.parse(sessionStorage.getItem("alsun_upload"))?.lang || DEFAULT_LANGUAGE;
  } catch (error) {
    return DEFAULT_LANGUAGE;
  }
}

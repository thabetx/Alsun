// The window of the glossary: the user adds, edits and deletes his terms, imports a csv and saves a copy.
// The terms are for the language he translates to (see glossary-store.js).

import { targetLanguage, targetLanguageInArabic } from "./target-language.js";
import {
  getGlossary, addTerm, deleteTerm, importCsv, exportCsv, MAX_ARABIC_CHARS, MAX_TRANSLATION_CHARS,
} from "./glossary-store.js";

let openDialog = null;

const IMPORT_HINT =
  "ملف CSV بعمودين: المصطلح بالعربية ثم ترجمته (يمكن أن يبدأ بسطر عناوين). احفظه من Excel بصيغة CSV UTF-8.";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function iconButton(icon, label, className) {
  const button = element("button", `glossary-icon ${className}`);
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = `<i class="fa-solid ${icon}" aria-hidden="true"></i>`;
  return button;
}

export function openGlossary() {
  if (openDialog) return;
  const language = targetLanguage();
  let editing = null; // the Arabic term being edited, or null

  const dialog = element("dialog", "glossary-dialog");
  dialog.setAttribute("aria-labelledby", "glossary-title");

  // ----- head -----
  const head = element("div", "glossary-head");
  const title = element("h2", "glossary-title", `القاموس — ${targetLanguageInArabic()}`);
  title.id = "glossary-title";
  head.append(title, element("p", "glossary-sub", "مصطلحات تحدد أنت ترجمتها، وتُستخدم في كل ترجمة لاحقة."));

  // ----- form -----
  const arabicInput = element("input", "glossary-input");
  arabicInput.type = "text";
  arabicInput.dir = "rtl";
  arabicInput.maxLength = MAX_ARABIC_CHARS;
  arabicInput.placeholder = "المصطلح بالعربية";
  arabicInput.setAttribute("aria-label", "المصطلح بالعربية");

  const translationInput = element("input", "glossary-input");
  translationInput.type = "text";
  translationInput.dir = "ltr";
  translationInput.maxLength = MAX_TRANSLATION_CHARS;
  translationInput.placeholder = `الترجمة (${targetLanguageInArabic()})`;
  translationInput.setAttribute("aria-label", "الترجمة");

  const saveButton = element("button", "glossary-primary", "إضافة");
  saveButton.type = "button";
  const cancelEditButton = element("button", "glossary-secondary", "إلغاء التعديل");
  cancelEditButton.type = "button";
  cancelEditButton.hidden = true;

  const form = element("form", "glossary-form");
  form.append(arabicInput, translationInput, saveButton, cancelEditButton);

  const message = element("p", "glossary-message");
  message.setAttribute("role", "status");
  const showMessage = (text, isError = false) => {
    message.textContent = text;
    message.classList.toggle("is-error", isError);
  };

  // ----- list -----
  const searchInput = element("input", "glossary-input glossary-search");
  searchInput.type = "search";
  searchInput.placeholder = "ابحث في القاموس…";
  searchInput.setAttribute("aria-label", "بحث في القاموس");
  const counter = element("span", "glossary-counter");
  const listHead = element("div", "glossary-list-head");
  listHead.append(searchInput, counter);

  const list = element("ul", "glossary-list");

  // ----- footer -----
  const importInput = element("input");
  importInput.type = "file";
  importInput.accept = ".csv,.txt,text/csv";
  importInput.hidden = true;
  const importButton = element("button", "glossary-secondary");
  importButton.type = "button";
  importButton.title = IMPORT_HINT;
  importButton.innerHTML = '<i class="fa-solid fa-file-import" aria-hidden="true"></i> استيراد CSV';
  const exportButton = element("button", "glossary-secondary");
  exportButton.type = "button";
  exportButton.innerHTML = '<i class="fa-solid fa-file-export" aria-hidden="true"></i> حفظ نسخة';
  const closeButton = element("button", "glossary-primary", "إغلاق");
  closeButton.type = "button";
  const footer = element("div", "glossary-footer");
  footer.append(closeButton, importButton, exportButton, importInput);

  dialog.append(head, form, message, listHead, list, footer);

  // ----- behavior -----
  function render() {
    const all = getGlossary(language);
    const filter = searchInput.value.trim();
    const shown = filter ? all.filter((item) => item.arabic.includes(filter) || item.translation.toLowerCase().includes(filter.toLowerCase())) : all;
    counter.textContent = filter ? `${shown.length} من ${all.length}` : `${all.length} مصطلح`;

    list.replaceChildren();
    if (!shown.length) {
      list.append(element("li", "glossary-empty", all.length ? "لا توجد نتائج" : "لم تضف أي مصطلح بعد. أضف مصطلحًا أو استورد ملف CSV."));
      return;
    }
    shown.forEach((item) => {
      const row = element("li", "glossary-item");
      const arabic = element("span", "glossary-arabic", item.arabic);
      arabic.dir = "rtl";
      const translation = element("span", "glossary-translation", item.translation);
      translation.dir = "ltr";
      const edit = iconButton("fa-pen", "تعديل", "glossary-edit");
      const remove = iconButton("fa-trash-can", "حذف", "glossary-remove");
      edit.addEventListener("click", () => startEditing(item));
      remove.addEventListener("click", () => {
        if (editing === item.arabic) stopEditing();
        deleteTerm(language, item.arabic);
        showMessage("تم حذف المصطلح");
        render();
      });
      row.append(arabic, translation, edit, remove);
      list.append(row);
    });
  }

  function startEditing(item) {
    editing = item.arabic;
    arabicInput.value = item.arabic;
    translationInput.value = item.translation;
    saveButton.textContent = "حفظ";
    cancelEditButton.hidden = false;
    showMessage("");
    translationInput.focus();
  }

  function stopEditing() {
    editing = null;
    form.reset();
    saveButton.textContent = "إضافة";
    cancelEditButton.hidden = true;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const result = addTerm(language, arabicInput.value, translationInput.value, editing);
    if (result.error) return showMessage(result.error, true);
    const wasEditing = editing !== null;
    stopEditing();
    showMessage(wasEditing ? "تم حفظ التعديل" : "تمت إضافة المصطلح");
    searchInput.value = "";
    render();
    arabicInput.focus();
  });
  saveButton.addEventListener("click", () => form.requestSubmit());
  cancelEditButton.addEventListener("click", () => { stopEditing(); showMessage(""); });
  searchInput.addEventListener("input", render);

  importButton.addEventListener("click", () => importInput.click());
  importInput.addEventListener("change", async () => {
    const file = importInput.files[0];
    importInput.value = "";
    if (!file) return;
    const result = await importCsv(language, file);
    if (result.error) return showMessage(result.error, true);

    const skipped = result.skipped;
    let text = `تمت إضافة ${result.added} مصطلح`;
    if (skipped.length) {
      const first = skipped.slice(0, 3).map((item) => `السطر ${item.line}: ${item.reason}`).join("، ");
      text += `، وتم تخطي ${skipped.length} (${first}${skipped.length > 3 ? "…" : ""})`;
    }
    showMessage(text, result.added === 0 && skipped.length > 0);
    render();
  });

  exportButton.addEventListener("click", () => {
    if (!getGlossary(language).length) return showMessage("القاموس فارغ، لا يوجد ما يُحفظ", true);
    const url = URL.createObjectURL(new Blob([exportCsv(language)], { type: "text/csv;charset=utf-8" }));
    const link = element("a");
    link.href = url;
    link.download = `glossary-${language}.csv`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  const close = () => {
    if (dialog.open) dialog.close();
    dialog.remove();
    openDialog = null;
  };
  closeButton.addEventListener("click", close);
  dialog.addEventListener("click", (event) => { if (event.target === dialog) close(); });
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });

  document.body.append(dialog);
  openDialog = dialog;
  render();
  dialog.showModal();
  arabicInput.focus();
}

export function initGlossary() {
  document.getElementById("open-glossary").addEventListener("click", openGlossary);
}

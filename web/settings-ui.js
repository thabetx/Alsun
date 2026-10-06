// The settings window: the quran translation (for the language of the book), the trusted Islamic terms
// and the model (OpenAI or Cohere).
// What can be chosen comes from the server (GET /settings/options); the choices are kept in the browser (settings-store.js).

import { getJson, postJson } from "./api.js";
import { askConfirmation } from "./confirm-dialog.js";
import { rowStates } from "./state.js";
import { renderTranslated, syncRowFromDom } from "./translated-view.js";
import { getAllRows } from "./selection.js";
import { targetLanguage, targetLanguageInArabic } from "./target-language.js";
import {
  getModelChoice, setModelChoice, getQuranSource, setQuranSource, getTrustedTerms, setTrustedTerms,
} from "./settings-store.js";

let openDialog = null;

// the same as DEFAULT_MODEL in python/llm.py; choosing it means "no choice", so the server can change its default
const DEFAULT_MODEL = { provider: "openai", model: "gpt-4o-mini" };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// a name written by a provider or a publisher: shown exactly as it is, left to right
function nameLabel(text, className = "") {
  const label = element("span", `settings-name ${className}`.trim(), text);
  label.dir = "ltr";
  return label;
}

function section(title, hint) {
  const box = element("section", "settings-section");
  box.append(element("h3", "settings-section-title", title));
  if (hint) box.append(element("p", "settings-hint", hint));
  return box;
}

// ---------- the quran translation on rows that are already translated ----------

// The translated rows whose ayahs come from another quran translation than the chosen one
// (an ayah without a mark was written with the first translation of the language, the default one).
function rowsWithOtherQuranSource(sources, chosenId) {
  const defaultId = sources.find((source) => source.default).id;
  return getAllRows().filter((tr) => {
    const state = rowStates.get(tr.dataset.id);
    // a locked row keeps its ayahs as they are
    return state && !state.locked &&
      state.segments.some((segment) => segment.type === "quran" && (segment.quran_source ?? defaultId) !== chosenId);
  });
}

// report(text, isError) writes in the window (a toast would be behind it)
async function applyQuranSourceToRows(language, sources, chosenId, report) {
  const rows = rowsWithOtherQuranSource(sources, chosenId);
  if (!rows.length) return;

  const count = rows.length === 1 ? "صف واحد" : `${rows.length} صفوف`;
  const confirmed = await askConfirmation({
    title: "تغيير مرجع الآيات",
    message: `في ${count} مترجم آيات بمرجع آخر. هل تغيّرها إلى المرجع الذي اخترته؟ لن يتغير باقي النص.`,
    confirmLabel: "غيّر الآيات",
    cancelLabel: "للترجمات القادمة فقط",
    icon: "fa-book-quran",
  });
  if (!confirmed) return;

  rows.forEach(syncRowFromDom); // what the user typed and did not leave yet
  try {
    const answer = await postJson("/quran/swap-source", {
      target_lang: language,
      quran_source: chosenId,
      rows: rows.map((tr) => ({ id: tr.dataset.id, segments: rowStates.get(tr.dataset.id).segments })),
    });
    answer.rows.forEach((row) => {
      const tr = rows.find((candidate) => candidate.dataset.id === row.id);
      const state = rowStates.get(row.id);
      if (!tr || !state || !document.contains(tr)) return; // gone while we waited
      state.segments = row.segments;
      renderTranslated(tr);
    });
    report(`تم تغيير مرجع الآيات في ${count}`);
  } catch (error) {
    report(error.message, true);
  }
}

// ---------- the window ----------

export async function openSettings() {
  if (openDialog) return;
  const language = targetLanguage();

  const dialog = element("dialog", "settings-dialog");
  dialog.setAttribute("aria-labelledby", "settings-title");
  openDialog = dialog;

  const head = element("div", "settings-head");
  const title = element("h2", "settings-title", "الإعدادات");
  title.id = "settings-title";
  head.append(title, element("p", "settings-sub", `لغة الترجمة: ${targetLanguageInArabic()}`));

  const body = element("div", "settings-body");
  body.append(element("p", "settings-loading", "جارٍ التحميل…"));

  const message = element("p", "settings-message");
  message.setAttribute("role", "status");
  const closeButton = element("button", "glossary-primary", "إغلاق");
  closeButton.type = "button";
  const footer = element("div", "settings-footer");
  footer.append(closeButton, message);

  dialog.append(head, body, footer);

  const close = () => {
    if (dialog.open) dialog.close();
    dialog.remove();
    openDialog = null;
  };
  closeButton.addEventListener("click", close);
  dialog.addEventListener("click", (event) => { if (event.target === dialog) close(); });
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  document.body.append(dialog);
  dialog.showModal();

  let options;
  try {
    options = await getJson("/settings/options");
  } catch (error) {
    body.replaceChildren(element("p", "settings-error", "تعذّر تحميل الإعدادات من الخادم"));
    return;
  }
  if (openDialog !== dialog) return; // closed while loading

  const saved = (text, isError = false) => {
    message.textContent = text;
    message.classList.toggle("is-error", isError);
  };
  body.replaceChildren(
    ...[
      buildQuranSection(language, options.quran_sources[language] || [], saved),
      options.trusted_terms && buildTrustedTermsSection(language, options.trusted_terms, saved),
      buildModelSection(options.models, saved),
    ].filter(Boolean)
  );
}

function buildQuranSection(language, sources, saved) {
  const box = section("مرجع القرآن", "الترجمة التي تُكتب بها الآيات. لا يُترجم القرآن بالذكاء الاصطناعي أبدًا، وإنما يؤخذ من هذا المرجع.");
  if (!sources.length) {
    box.append(element("p", "settings-error", "لا يوجد مرجع للقرآن لهذه اللغة"));
    return box;
  }

  // one reference only: its name is shown and it can't be changed
  if (sources.length === 1) {
    const row = element("div", "settings-fixed");
    row.append(nameLabel(sources[0].name), element("span", "settings-lock", "مرجع واحد متاح لهذه اللغة"));
    box.append(row);
    return box;
  }

  const chosenId = getQuranSource(language) ?? sources.find((source) => source.default).id;
  const group = element("div", "settings-choices");
  sources.forEach((source) => {
    const label = element("label", "settings-choice");
    const radio = element("input");
    radio.type = "radio";
    radio.name = "quran-source";
    radio.value = source.id;
    radio.checked = source.id === chosenId;
    radio.addEventListener("change", async () => {
      setQuranSource(language, source.default ? null : source.id);
      saved("تم الحفظ");
      await applyQuranSourceToRows(language, sources, source.id, saved);
    });
    label.append(radio, nameLabel(source.name));
    if (source.default) label.append(element("span", "settings-tag", "الافتراضي"));
    group.append(label);
  });
  box.append(group);
  return box;
}

// ---------- the trusted Islamic terms ----------

function buildTrustedTermsSection(language, info, saved) {
  const box = section(
    "القاموس الشرعي",
    "مصطلحات شرعية بمقابلاتها من موسوعة موثوقة. عند تفعيله يلتزم النموذج بمقابل المصطلح حين يكون له المعنى نفسه في النص، " +
      "وإذا كان المصطلح في قاموسك الخاص فترجمتك هي المعتمدة. يسري هذا على الترجمات القادمة."
  );

  const count = info.terms[language] ?? 0;
  if (!count) {
    box.append(element("p", "settings-hint", "القاموس الشرعي غير متاح لهذه اللغة بعد."));
    return box;
  }

  const label = element("label", "settings-choice");
  const checkbox = element("input");
  checkbox.type = "checkbox";
  checkbox.checked = getTrustedTerms();
  checkbox.addEventListener("change", () => {
    setTrustedTerms(checkbox.checked);
    saved("تم الحفظ");
  });
  label.append(checkbox, element("span", "", "استخدام القاموس الشرعي في الترجمة"), element("span", "settings-tag", `${count} مصطلح`));

  const source = element("a", "settings-source", info.source);
  source.href = info.url;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  const sourceLine = element("p", "settings-hint settings-source-line", "المصدر: ");
  sourceLine.append(source);

  box.append(label, sourceLine);
  return box;
}

// the names people know (the backend sends the company names)
const PROVIDER_NAMES = { openai: "ChatGPT", cohere: "Cohere (Command)" };
const providerName = (provider) => PROVIDER_NAMES[provider.provider] ?? provider.label;

function buildModelSection(providers, saved) {
  const box = section(
    "نموذج الذكاء الاصطناعي",
    "اختر النموذج الذي تتم به الترجمة ويعمل به المساعد الذكي. وإذا لم يستجب النموذج المختار، ننتقل تلقائيًا إلى نموذج آخر ونُخبرك بذلك."
  );

  const stored = getModelChoice();
  const current = stored ?? DEFAULT_MODEL;
  const storedProvider = providers.find((provider) => provider.provider === current.provider);
  // a choice whose provider has no key now (the key was removed): the window says it
  const storedUsable = Boolean(storedProvider?.has_key);
  const shown = storedUsable ? current : DEFAULT_MODEL;
  if (stored && !storedUsable) {
    box.append(element("p", "settings-error", "اختيارك السابق لم يعد متاحًا، سيُستخدم النموذج الافتراضي حتى تختار غيره."));
  }

  const providerSelect = element("select", "settings-select");
  providerSelect.setAttribute("aria-label", "الشركة");
  providers.forEach((provider) => {
    const option = element("option", "", provider.has_key ? providerName(provider) : `${providerName(provider)} — غير متاح حاليًا`);
    option.value = provider.provider;
    option.disabled = !provider.has_key;
    providerSelect.append(option);
  });
  providerSelect.value = shown.provider;

  const modelSelect = element("select", "settings-select");
  modelSelect.setAttribute("aria-label", "الموديل");
  modelSelect.dir = "ltr";

  const note = element("p", "settings-hint settings-model-note");
  let items = [];
  const showNote = () => {
    const item = items.find((candidate) => candidate.id === modelSelect.value);
    note.textContent = item ? item.note : "لا يوجد موديل موصى به متاح لهذا المزوّد.";
  };
  const fillModels = (providerId, selectedModel) => {
    const provider = providers.find((candidate) => candidate.provider === providerId);
    items = [...provider.models];
    // the model chosen before may not be one of the recommended: it stays in the list
    if (selectedModel && !items.some((item) => item.id === selectedModel)) {
      items.push({ id: selectedModel, note: "اختيارك الحالي، وليس من الموديلات الموصى بها." });
    }
    modelSelect.replaceChildren(...items.map((item) => {
      const option = element("option", "", item.id); // exactly as the provider writes it
      option.value = item.id;
      return option;
    }));
    modelSelect.value = items.some((item) => item.id === selectedModel) ? selectedModel : items[0]?.id ?? "";
    showNote();
    failedNote.textContent = provider.list_failed ? "تعذّر قراءة قائمة الموديلات من المزوّد، المعروض هو الموديلات الموصى بها دون تحقق." : "";
  };
  const failedNote = element("p", "settings-hint");
  fillModels(shown.provider, shown.model);

  const save = () => {
    if (!modelSelect.value) return;
    const choice = { provider: providerSelect.value, model: modelSelect.value };
    const isDefault = choice.provider === DEFAULT_MODEL.provider && choice.model === DEFAULT_MODEL.model;
    setModelChoice(isDefault ? null : choice);
    saved("تم الحفظ");
  };
  providerSelect.addEventListener("change", () => { fillModels(providerSelect.value); save(); });
  modelSelect.addEventListener("change", () => { showNote(); save(); });

  const row = element("div", "settings-row");
  row.append(providerSelect, modelSelect);
  box.append(row, failedNote);
  return box;
}

export function initSettings() {
  document.getElementById("open-settings").addEventListener("click", openSettings);
}

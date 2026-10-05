// The settings of the user, kept in the browser (localStorage):
//   - the model he chose (OpenAI or Cohere) for the translation and the assistant; none = the default one of the server
//   - the quran translation he chose for each language; none = the first one of the language
// The keys of the providers are never here: they are in the .env file of the server.

const STORAGE_KEY = "alsun:settings:v1";

function readAll() {
  try {
    const all = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return all && typeof all === "object" ? all : {};
  } catch (error) {
    return {}; // not json, or no access to the storage
  }
}

function writeAll(all) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch (error) {
    // the storage is full or blocked: the choice lasts until the page is closed only
  }
}

// {provider, model} or null
export function getModelChoice() {
  const choice = readAll().model;
  return choice && typeof choice.provider === "string" && typeof choice.model === "string" ? choice : null;
}

export function setModelChoice(choice) {
  const all = readAll();
  if (choice) all.model = { provider: choice.provider, model: choice.model };
  else delete all.model;
  writeAll(all);
}

// the id of the quran translation chosen for this language, or null
export function getQuranSource(language) {
  const id = readAll().quranSources?.[language];
  return typeof id === "string" ? id : null;
}

export function setQuranSource(language, id) {
  const all = readAll();
  all.quranSources = { ...all.quranSources };
  if (id) all.quranSources[language] = id;
  else delete all.quranSources[language];
  writeAll(all);
}

// what is added to the body of a request to the server (translation, re-translation, assistant)
export function modelSettings() {
  const choice = getModelChoice();
  return choice ? { model: choice } : {};
}

export function translationSettings(language) {
  const source = getQuranSource(language);
  return { ...modelSettings(), ...(source ? { quran_source: source } : {}) };
}

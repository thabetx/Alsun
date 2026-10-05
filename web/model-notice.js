// The server tells when the model the user chose did not answer and another one did
// (answer.fallbacks = [{from, to, reason}], see python/llm.py). This is what the user reads.

const isolate = (name) => `\u2066${name}\u2069`; // a model name stays left to right inside the arabic text

export function fallbackMessage(fallbacks) {
  const first = fallbacks[0];
  const last = fallbacks[fallbacks.length - 1];
  return `تعذّر الرد من ${isolate(first.from)}، فأجاب ${isolate(last.to)} بدلًا منه.`;
}

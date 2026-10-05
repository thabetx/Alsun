// The pen of the logo (without the lines under it) writes for us, with ink the color of the text:
//   - while we wait for the translation: it scribbles on the spot (mountPenScribble)
//   - when the translation arrives: it writes it letter by letter and follows the end of the text (typeTranslation)

const INK_COLOR = "#231a19"; // the color of the text
const PEN_SCALE = 0.8;
const PEN_WIDTH = 38 * PEN_SCALE;
const PEN_HEIGHT = 44 * PEN_SCALE;
// where the nib is inside the pen drawing (the viewBox below puts it at 2, 42)
const NIB = { x: 2 * PEN_SCALE, y: 42 * PEN_SCALE };

// The pen writes at a calm speed (about 28 characters in a second) and stops for a moment after
// punctuation, like a person. A very long text speeds up smoothly after the calm part, so it never takes too long.
const MS_PER_CHARACTER = 35;
const PAUSE_AFTER_COMMA_MS = 120;
const PAUSE_AFTER_SENTENCE_MS = 220;
const CALM_MS = 6000; // the pen keeps the calm speed for the first 6 seconds
const SPEED_UP_SHARE = 0.4; // what is left to write after the calm part is written in 40% of its calm time (or less)
const MAX_TYPING_MS = 12000;

const writers = new WeakMap(); // row -> {finish}

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function createPen() {
  const pen = document.createElement("span");
  pen.className = "pen-writer";
  pen.setAttribute("aria-hidden", "true");
  // same drawing as web/logo-mark.svg, only the pen; the nib is at the origin of the group
  pen.innerHTML = `
    <svg viewBox="-2 -42 38 44" width="${PEN_WIDTH}" height="${PEN_HEIGHT}">
      <g transform="rotate(38)">
        <path d="M0 0C-2.2 -6 -6.5 -11 -6.5 -17H6.5C6.5 -11 2.2 -6 0 0Z" fill="#d1a63c"/>
        <path d="M0 -3V-11" stroke="#231a19" stroke-width="1" stroke-linecap="round"/>
        <circle cx="0" cy="-12.5" r="1.3" fill="#231a19"/>
        <rect x="-6.5" y="-21" width="13" height="4.2" rx="1.2" fill="#b8860b"/>
        <rect x="-6" y="-46" width="12" height="25.5" rx="3.2" fill="#231a19"/>
        <rect x="-3.6" y="-43" width="1.8" height="19" rx=".9" fill="#fff" opacity=".22"/>
      </g>
    </svg>`;
  return pen;
}

// a small dot of ink that leaves the nib, falls a little and fades (few and small, so they don't cover the text)
function spitInk(host, x, y) {
  const size = 1.5 + Math.random() * 1.5;
  const dot = document.createElement("i");
  dot.className = "ink-dot";
  dot.style.cssText = `left:${x}px; top:${y}px; width:${size}px; height:${size}px; background:${INK_COLOR};`;
  host.append(dot);
  const sideways = -8 + Math.random() * 12;
  const down = 4 + Math.random() * 5;
  dot.animate(
    [
      { transform: "translate(0, 0) scale(1)", opacity: 0.7 },
      { transform: `translate(${sideways}px, ${down}px) scale(0.3)`, opacity: 0 },
    ],
    { duration: 260 + Math.random() * 220, easing: "ease-out" }
  ).onfinish = () => dot.remove();
  // if the page is hidden the animation may never finish, so the dot is removed anyway
  setTimeout(() => dot.remove(), 1000);
}

function nibPositionInHost(pen, host) {
  const penBox = pen.getBoundingClientRect();
  const hostBox = host.getBoundingClientRect();
  return { x: penBox.left - hostBox.left + NIB.x, y: penBox.top - hostBox.top + NIB.y };
}

// ---------- waiting: the pen scribbles on the spot ----------

// host = the element the pen is drawn in (it gets position: relative from the css)
export function mountPenScribble(host, { sweep = 90 } = {}) {
  host.classList.add("pen-host");
  const pen = createPen();
  pen.classList.add("pen-scribbling");
  pen.style.setProperty("--pen-sweep", `${sweep}px`);
  host.append(pen);

  const reduced = prefersReducedMotion();
  const timer = reduced
    ? null
    : setInterval(() => {
        const nib = nibPositionInHost(pen, host);
        spitInk(host, nib.x, nib.y);
      }, 130);

  return () => {
    if (timer) clearInterval(timer);
    pen.remove();
  };
}

// the pen in the translated cell of a row
export function startPenLoading(tr) {
  return mountPenScribble(tr.querySelector(".translated-cell"));
}

// ---------- the translation arrives: the pen writes it ----------

// The calm schedule: for every character, the time (ms) at which the pen has finished writing it.
export function buildTypingSchedule(text) {
  const ends = new Array(text.length);
  let time = 0;
  for (let i = 0; i < text.length; i++) {
    time += MS_PER_CHARACTER;
    ends[i] = time;
    if (",;:،؛".includes(text[i])) time += PAUSE_AFTER_COMMA_MS;
    else if (".!?؟".includes(text[i])) time += PAUSE_AFTER_SENTENCE_MS;
  }
  return { ends, total: time };
}

// How long the whole writing takes (ms). Short texts: exactly the calm schedule.
export function typingDuration(calmTotal) {
  if (calmTotal <= CALM_MS) return calmTotal;
  const rest = calmTotal - CALM_MS;
  return CALM_MS + Math.min(rest * SPEED_UP_SHARE, MAX_TYPING_MS - CALM_MS);
}

// How much of the calm schedule is done after `elapsed` ms of real time.
// Short texts: the same time. Long texts: the same time for the calm part, then the speed grows smoothly.
export function calmTimeAt(elapsed, calmTotal) {
  if (calmTotal <= CALM_MS || elapsed <= CALM_MS) return elapsed;
  const rest = calmTotal - CALM_MS;
  const speedUpMs = typingDuration(calmTotal) - CALM_MS;
  const acceleration = (2 * (rest - speedUpMs)) / speedUpMs ** 2;
  const t = Math.min(elapsed - CALM_MS, speedUpMs);
  return CALM_MS + t + 0.5 * acceleration * t * t;
}

export function finishTyping(tr) {
  writers.get(tr)?.finish();
}

function isOnScreen(element) {
  const box = element.getBoundingClientRect();
  return box.bottom > 0 && box.top < window.innerHeight;
}

// Call it right after the row was drawn from its segments. The text is already all there (the part
// that is not written yet is transparent), so the page does not jump while the pen writes.
export function typeTranslation(tr) {
  finishTyping(tr);
  const host = tr.querySelector(".translated-cell");
  const spans = [...tr.querySelectorAll(".translated-text .seg")];
  const total = spans.reduce((sum, span) => sum + span.textContent.length, 0);
  // no animation for people who turned motion off, and for rows the user can't see anyway
  if (!total || prefersReducedMotion() || !isOnScreen(host)) return;

  host.classList.add("pen-host");
  const cell = tr.querySelector(".translated-text");
  cell.classList.add("is-typing");
  const parts = spans.map((span) => {
    const full = span.textContent;
    const typed = document.createElement("span");
    typed.className = "typed";
    const caret = document.createElement("i");
    caret.className = "type-caret";
    const untyped = document.createElement("span");
    untyped.className = "untyped";
    untyped.textContent = full;
    span.replaceChildren(typed, caret, untyped);
    return { span, full, typed, caret, untyped };
  });

  const pen = createPen();
  pen.classList.add("pen-typing");

  const schedule = buildTypingSchedule(parts.map((part) => part.full).join(""));
  const duration = typingDuration(schedule.total);
  const interaction = new AbortController();
  let startTime = null;
  let frame = 0;
  let lastInk = 0;
  let written = 0;
  let finished = false;

  // the pen stands at the end of what is written so far
  const placePen = () => {
    const active = parts.find((part) => part.untyped.textContent.length > 0) ?? parts[parts.length - 1];
    const caretBox = active.caret.getBoundingClientRect();
    const hostBox = host.getBoundingClientRect();
    const x = caretBox.left - hostBox.left;
    const y = caretBox.bottom - hostBox.top;
    pen.style.left = `${x - NIB.x}px`;
    pen.style.top = `${y - NIB.y + 2}px`;
    return { x, y };
  };
  placePen();
  host.append(pen);
  // it slides from letter to letter (not before the first one, so it doesn't fly in from the corner)
  setTimeout(() => pen.classList.add("pen-gliding"), 60);

  const setProgress = (count) => {
    let left = count;
    parts.forEach((part) => {
      const written = Math.max(0, Math.min(part.full.length, left));
      left -= written;
      part.typed.textContent = part.full.slice(0, written);
      part.untyped.textContent = part.full.slice(written);
    });
  };

  const finish = () => {
    if (finished) return;
    finished = true;
    cancelAnimationFrame(frame);
    interaction.abort();
    cell.classList.remove("is-typing");
    // the exact text again, as one text node, the way it was before the animation
    parts.forEach((part) => part.span.replaceChildren(document.createTextNode(part.full)));
    pen.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200 }).onfinish = () => pen.remove();
    setTimeout(() => pen.remove(), 500); // if the page is hidden the fade may never finish
    writers.delete(tr);
  };

  const step = (now) => {
    if (finished) return;
    if (startTime === null) startTime = now;
    const elapsed = now - startTime;
    if (elapsed >= duration) return finish();

    const calmTime = calmTimeAt(elapsed, schedule.total);
    while (written < schedule.ends.length && schedule.ends[written] <= calmTime) written++;
    setProgress(written);

    const { x, y } = placePen();
    if (now - lastInk > 150) {
      spitInk(host, x, y + 1);
      lastInk = now;
    }
    frame = requestAnimationFrame(step);
  };

  // the user touches the row: show the whole text now
  ["pointerdown", "keydown", "focusin"].forEach((type) =>
    host.addEventListener(type, finish, { signal: interaction.signal })
  );
  writers.set(tr, { finish });
  frame = requestAnimationFrame(step);
}

// The pen of the logo (without the lines under it) and the writing of the translation:
//   - the pen scribbles on the spot (mountPenScribble: the waiting bubble of the assistant)
//   - when a translation arrives it is written letter by letter, fast, like a chat (typeTranslation)
// While we wait for a translation the whole page shows the pen (see loading-overlay.js).

const INK_COLOR = "#231a19"; // the color of the text
const PEN_SCALE = 0.8;
// where the nib is inside the pen drawing (the viewBox below puts it at 2, 42)
const NIB = { x: 2 * PEN_SCALE, y: 42 * PEN_SCALE };

// The text is written fast (about 250 characters in a second), so nobody waits for it.
// A very long text speeds up smoothly after the first second and a half, so it never takes more than 3 seconds.
const MS_PER_CHARACTER = 4;
const PAUSE_AFTER_COMMA_MS = 0;
const PAUSE_AFTER_SENTENCE_MS = 0;
const CALM_MS = 1500; // the normal speed is kept for the first second and a half
const SPEED_UP_SHARE = 0.4; // what is left to write after that is written in 40% of its normal time (or less)
const MAX_TYPING_MS = 3000;

const writers = new WeakMap(); // row -> {finish}

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// the pen of the logo as an element; the page loading uses a bigger one
export function createPen(scale = PEN_SCALE) {
  const pen = document.createElement("span");
  pen.className = "pen-writer";
  pen.setAttribute("aria-hidden", "true");
  // same drawing as web/logo-mark.svg, only the pen; the nib is at the origin of the group
  pen.innerHTML = `
    <svg viewBox="-2 -42 38 44" width="${38 * scale}" height="${44 * scale}">
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

// ---------- the translation arrives: it is written letter by letter ----------

// The normal schedule: for every character, the time (ms) at which it is written.
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
// that is not written yet is transparent), so the page does not jump while it is written.
export function typeTranslation(tr) {
  finishTyping(tr);
  const host = tr.querySelector(".translated-cell");
  const spans = [...tr.querySelectorAll(".translated-text .seg")];
  const total = spans.reduce((sum, span) => sum + span.textContent.length, 0);
  // no animation for people who turned motion off, and for rows the user can't see anyway
  if (!total || prefersReducedMotion() || !isOnScreen(host)) return;

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

  const schedule = buildTypingSchedule(parts.map((part) => part.full).join(""));
  const duration = typingDuration(schedule.total);
  const interaction = new AbortController();
  let startTime = null;
  let frame = 0;
  let written = 0;
  let finished = false;

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
    frame = requestAnimationFrame(step);
  };

  // the user touches the row: show the whole text now
  ["pointerdown", "keydown", "focusin"].forEach((type) =>
    host.addEventListener(type, finish, { signal: interaction.signal })
  );
  writers.set(tr, { finish });
  frame = requestAnimationFrame(step);
}

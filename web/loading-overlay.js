// The loading of the whole page while the book is read or a translation is made: a big pen writes lines of
// handwriting in the middle and throws drops of ink, at a calm speed. The translations that arrive are written fast
// behind it (see typeTranslation).
//
//   const endLoading = beginLoading({ message: "جارٍ ترجمة الصف…" });  ...  endLoading();
//
// beginLoading can be called again before the first loading ends (a "translate all" with a row inside it):
// the page stays covered until every loading has ended, and the first one decides the title, the tips and the
// stop button.
//
// It does not look the same for long: every time the pen starts again the handwriting is different (taller or
// flatter waves, longer or shorter lines), and for a long wait the tips under the title change.

import { createPen } from "./pen-writer.js";

const INK_COLOR = "#2b1d0e"; // dark brown
const SHOW_AFTER_MS = 250; // a translation that fails at once doesn't flash the screen
const RELEASE_AFTER_MS = 40000; // a request that never answers must not lock the page for good
const FIRST_TIP_AFTER_MS = 2500; // a short wait has no tips
const TIP_EVERY_MS = 6000;
const PEN_SCALE = 1.7;
const NIB = { x: 2 * PEN_SCALE, y: 42 * PEN_SCALE }; // where the nib is inside the pen drawing

// ---------- the handwriting ----------
// 4 lines, one after the other. The pen writes a line (LINE_MS), lifts and goes to the start of the next one (MOVE_MS);
// after the last line the lines fade while the pen goes back to the first one.
const SCENE = { width: 270, height: 140 };
const LINES = 4;
const LINE_START_X = 12;
const LINE_END_X = 246; // the longest a line can be
const LINE_MS = 1100;
const MOVE_MS = 250;
const FADE_MS = 450;
const CYCLE_MS = LINES * LINE_MS + LINES * MOVE_MS - MOVE_MS + 700;
const lineY = (line) => 24 + line * 33;

// The look of one round of writing. A new one is made every time the pen starts again.
function newStyle() {
  const random = (min, max) => min + Math.random() * (max - min);
  return {
    phase: random(0, Math.PI * 2),
    amplitude: random(0.6, 1.5), // how tall the waves are
    stretch: random(0.8, 1.45), // how long the waves are
    // like a paragraph: the lines end at different places, and the last one is the shortest
    ends: Array.from({ length: LINES }, (_, line) => (line === LINES - 1 ? random(110, 190) : random(200, LINE_END_X))),
  };
}

let currentStyle = newStyle();

// the wave of a line, like handwriting
const waveY = (line, x, style) => {
  const along = x - LINE_START_X;
  return (
    lineY(line) +
    6 * style.amplitude * Math.sin(along / (11 * style.stretch) + line + style.phase) +
    2.4 * Math.sin(along / 4.7 + line * 2 + style.phase * 2)
  );
};

const easeInOut = (u) => 0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, Math.max(0, u)));

function wavePoints(line, untilX, style) {
  const points = [];
  for (let x = LINE_START_X; x < untilX; x += 3) points.push(`${x.toFixed(1)} ${waveY(line, x, style).toFixed(1)}`);
  points.push(`${untilX.toFixed(1)} ${waveY(line, untilX, style).toFixed(1)}`);
  return `M${points.join(" L")}`;
}

// Where everything is at the time t of the cycle:
// the pen (x, y), whether it touches the paper, how much of every line is written, and the opacity of the lines.
export function sceneAt(t, style = currentStyle) {
  const lastDrawEnd = (LINES - 1) * (LINE_MS + MOVE_MS) + LINE_MS;
  const lastLine = LINES - 1;
  const written = new Array(LINES).fill(LINE_START_X);
  let line = lastLine;
  let pen;
  let touching = false;
  let opacity = 1;

  for (let k = 0; k < LINES; k++) {
    const drawStart = k * (LINE_MS + MOVE_MS);
    const endX = style.ends[k];
    if (t < drawStart) { line = k - 1; break; }
    if (t < drawStart + LINE_MS) {
      const x = LINE_START_X + (endX - LINE_START_X) * easeInOut((t - drawStart) / LINE_MS);
      written[k] = x;
      pen = { x, y: waveY(k, x, style) };
      touching = true;
      line = k;
      break;
    }
    written[k] = endX;
    if (k < lastLine && t < drawStart + LINE_MS + MOVE_MS) {
      // lifted: from the end of this line to the start of the next one
      const u = easeInOut((t - drawStart - LINE_MS) / MOVE_MS);
      pen = {
        x: endX + (LINE_START_X - endX) * u,
        y: waveY(k, endX, style) + (waveY(k + 1, LINE_START_X, style) - waveY(k, endX, style)) * u,
      };
      line = k;
      break;
    }
  }

  if (!pen) {
    // after the last line: the lines fade and the pen goes back to the start of the first one
    const u = easeInOut((t - lastDrawEnd) / (CYCLE_MS - lastDrawEnd));
    const endX = style.ends[lastLine];
    pen = {
      x: endX + (LINE_START_X - endX) * u,
      y: waveY(lastLine, endX, style) + (waveY(0, LINE_START_X, style) - waveY(lastLine, endX, style)) * u,
    };
    opacity = 1 - Math.min(1, (t - lastDrawEnd) / FADE_MS);
  }
  return { pen, touching, written, opacity, line };
}

// ---------- the page ----------
let count = 0; // loadings that have not ended
let overlay = null;
let showTimer = null;
let releaseTimer = null;
let tipTimer = null;
let frame = 0;
let inkTimer = null;
let released = false;
let stopHandler = null;
let pendingMessage = ""; // the texts of the loading, written when the page is built and every time they change
let pendingProgress = "";
let pendingTips = [];
const parts = {};

function build() {
  const element = document.createElement("div");
  element.className = "loading-overlay";
  element.setAttribute("role", "status");
  element.setAttribute("aria-live", "polite");
  element.innerHTML = `
    <div class="loading-card">
      <div class="loading-scene" style="width:${SCENE.width}px; height:${SCENE.height}px">
        <svg class="loading-lines" viewBox="0 0 ${SCENE.width} ${SCENE.height}" aria-hidden="true">
          ${Array.from({ length: LINES }, () => '<path class="loading-line" d=""/>').join("")}
        </svg>
      </div>
      <p class="loading-title"></p>
      <p class="loading-progress" hidden></p>
      <p class="loading-tip is-hidden"></p>
      <div class="loading-actions">
        <button type="button" class="loading-button loading-stop" hidden>إيقاف الترجمة</button>
        <button type="button" class="loading-button loading-release" hidden>متابعة العمل</button>
      </div>
    </div>`;

  parts.scene = element.querySelector(".loading-scene");
  parts.lines = [...element.querySelectorAll(".loading-line")];
  parts.title = element.querySelector(".loading-title");
  parts.progress = element.querySelector(".loading-progress");
  parts.tip = element.querySelector(".loading-tip");
  parts.stop = element.querySelector(".loading-stop");
  parts.release = element.querySelector(".loading-release");

  parts.pen = createPen(PEN_SCALE);
  parts.pen.classList.add("loading-pen");
  parts.pen.style.transformOrigin = `${NIB.x}px ${NIB.y}px`;
  parts.scene.append(parts.pen);

  parts.stop.addEventListener("click", () => {
    parts.stop.disabled = true;
    parts.stop.textContent = "جارٍ الإيقاف…";
    stopHandler?.();
  });
  parts.release.addEventListener("click", () => {
    released = true;
    hide();
  });
  return element;
}

// a drop of ink thrown from the nib: it flies away, falls a little and fades
function throwInk(x, y) {
  const drop = document.createElement("i");
  const size = 2 + Math.random() * 3 + (Math.random() < 0.15 ? 3 : 0);
  drop.className = "loading-ink";
  drop.style.cssText = `left:${x}px; top:${y}px; width:${size}px; height:${size}px; background:${INK_COLOR};`;
  parts.scene.append(drop);
  const angle = -Math.PI * (0.15 + Math.random() * 0.7); // upwards, to both sides
  const distance = 10 + Math.random() * 30;
  const dx = Math.cos(angle) * distance;
  const dy = Math.sin(angle) * distance;
  const animation = drop.animate(
    [
      { transform: "translate(0, 0) scale(1)", opacity: 0.85 },
      { transform: `translate(${dx}px, ${dy}px) scale(.9)`, opacity: 0.7, offset: 0.45 },
      { transform: `translate(${dx * 1.25}px, ${dy + 24}px) scale(.3)`, opacity: 0 },
    ],
    { duration: 600 + Math.random() * 500, easing: "ease-out" }
  );
  animation.onfinish = () => drop.remove();
  setTimeout(() => drop.remove(), 1600); // a hidden page may never finish the animation
}

// draws the scene at the time t of the cycle (also used by the loop below)
export function drawFrame(t, style = currentStyle) {
  if (!overlay) return;
  const scene = sceneAt(t, style);
  parts.lines.forEach((path, k) => {
    path.setAttribute("d", scene.written[k] > LINE_START_X ? wavePoints(k, scene.written[k], style) : "");
    path.style.opacity = String(scene.opacity);
  });
  // the pen leans a little with the hand
  const lean = -4 + 6 * Math.sin(t / 230);
  parts.pen.style.transform =
    `translate(${(scene.pen.x - NIB.x).toFixed(1)}px, ${(scene.pen.y - NIB.y).toFixed(1)}px) rotate(${lean.toFixed(1)}deg)`;
  parts.pen.dataset.touching = scene.touching ? "1" : "";
  return scene;
}

function startMotion() {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  currentStyle = newStyle();
  if (reduced) {
    // no movement: the lines are written and the pen rests on the last one
    parts.lines.forEach((path, k) => path.setAttribute("d", wavePoints(k, currentStyle.ends[k], currentStyle)));
    const endX = currentStyle.ends[LINES - 1];
    parts.pen.style.transform = `translate(${endX - NIB.x}px, ${waveY(LINES - 1, endX, currentStyle) - NIB.y}px)`;
    return;
  }
  const start = performance.now();
  let cycle = 0;
  const step = (now) => {
    const elapsed = now - start;
    const thisCycle = Math.floor(elapsed / CYCLE_MS);
    if (thisCycle !== cycle) {
      // the lines have faded: the next round is written differently
      cycle = thisCycle;
      currentStyle = newStyle();
    }
    drawFrame(elapsed % CYCLE_MS);
    frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
  // the ink leaves the nib only while the pen touches the paper
  inkTimer = setInterval(() => {
    if (!parts.pen.dataset.touching) return;
    const nib = parts.pen.getBoundingClientRect();
    const scene = parts.scene.getBoundingClientRect();
    const x = nib.left - scene.left + NIB.x;
    const y = nib.top - scene.top + NIB.y;
    for (let i = 0; i < 1 + Math.round(Math.random()); i++) throwInk(x, y);
  }, 70);
}

function stopMotion() {
  cancelAnimationFrame(frame);
  clearInterval(inkTimer);
}

// ---------- the tips under the title (for a long wait) ----------
function startTips() {
  if (!pendingTips.length) return;
  let next = 0;
  const showNext = () => {
    if (!overlay) return;
    parts.tip.classList.add("is-hidden"); // fades out, the text changes, fades in
    setTimeout(() => {
      if (!overlay) return;
      parts.tip.textContent = pendingTips[next % pendingTips.length];
      parts.tip.classList.remove("is-hidden");
      next++;
    }, 350);
    tipTimer = setTimeout(showNext, TIP_EVERY_MS);
  };
  tipTimer = setTimeout(showNext, FIRST_TIP_AFTER_MS);
}

function setPageBusy(busy) {
  // nothing behind the loading can be reached with the keyboard either
  document.querySelectorAll(".site-header, .app-main").forEach((element) => {
    element.inert = busy;
  });
}

function show() {
  if (overlay || released) return;
  overlay = build();
  document.body.append(overlay);
  setPageBusy(true);
  applyTexts();
  startMotion();
  startTips();
  requestAnimationFrame(() => overlay?.classList.add("is-visible"));
  releaseTimer = setTimeout(() => {
    if (parts.release) parts.release.hidden = false;
  }, RELEASE_AFTER_MS);
}

function hide() {
  clearTimeout(releaseTimer);
  clearTimeout(tipTimer);
  stopMotion();
  setPageBusy(false);
  const closing = overlay;
  overlay = null;
  if (!closing) return;
  closing.classList.remove("is-visible");
  setTimeout(() => closing.remove(), 350);
}

// options: {message, onStop, tips}. tips = short sentences shown one after the other under the title when the wait
// is long. Returns the function that ends this loading (it is safe to call it twice).
export function beginLoading({ message = "جارٍ الترجمة…", onStop = null, tips = [] } = {}) {
  if (count === 0) {
    stopHandler = onStop;
    clearTimeout(showTimer);
    showTimer = setTimeout(show, SHOW_AFTER_MS);
    pendingMessage = message;
    pendingTips = tips;
  }
  count++;

  let ended = false;
  return () => {
    if (ended) return;
    ended = true;
    count--;
    if (count > 0) return;
    clearTimeout(showTimer);
    showTimer = null;
    released = false;
    stopHandler = null;
    pendingProgress = "";
    pendingTips = [];
    hide();
  };
}

function applyTexts() {
  parts.title.textContent = pendingMessage;
  parts.progress.textContent = pendingProgress;
  parts.progress.hidden = !pendingProgress;
  parts.stop.hidden = !stopHandler;
}

// "3 من 12" under the title (for the translation of many rows)
export function setLoadingProgress(text) {
  pendingProgress = text;
  if (overlay) applyTexts();
}

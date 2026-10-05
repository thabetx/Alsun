// The loading of the whole page while a translation is made: a big pen writes lines of handwriting in the middle
// and throws drops of ink, at a calm speed. The translations that arrive are written fast behind it (see typeTranslation).
//
//   const endLoading = beginLoading({ message: "جارٍ ترجمة الصف…" });  ...  endLoading();
//
// beginLoading can be called again before the first loading ends (a "translate all" with a row inside it):
// the page stays covered until every loading has ended, and the first one decides the title and the stop button.

import { createPen } from "./pen-writer.js";

const INK_COLOR = "#2b1d0e"; // dark brown
const SHOW_AFTER_MS = 250; // a translation that fails at once doesn't flash the screen
const RELEASE_AFTER_MS = 40000; // a request that never answers must not lock the page for good
const PEN_SCALE = 1.7;
const NIB = { x: 2 * PEN_SCALE, y: 42 * PEN_SCALE }; // where the nib is inside the pen drawing

// ---------- the handwriting ----------
// 4 lines, one after the other. The pen writes a line (LINE_MS), lifts and goes to the start of the next one (MOVE_MS);
// after the last line the lines fade while the pen goes back to the first one.
const SCENE = { width: 270, height: 140 };
const LINES = 4;
const LINE_START_X = 12;
const LINE_END_X = 246;
const LINE_MS = 1100;
const MOVE_MS = 250;
const FADE_MS = 450;
const CYCLE_MS = LINES * LINE_MS + LINES * MOVE_MS - MOVE_MS + 700;
const lineY = (line) => 24 + line * 33;

// the wave of a line: like handwriting, never the same twice in a row
const waveY = (line, x) => {
  const along = x - LINE_START_X;
  return lineY(line) + 6 * Math.sin(along / 11 + line) + 2.4 * Math.sin(along / 4.7 + line * 2);
};

const easeInOut = (u) => 0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, Math.max(0, u)));

function wavePoints(line, untilX) {
  const points = [];
  for (let x = LINE_START_X; x < untilX; x += 3) points.push(`${x.toFixed(1)} ${waveY(line, x).toFixed(1)}`);
  points.push(`${untilX.toFixed(1)} ${waveY(line, untilX).toFixed(1)}`);
  return `M${points.join(" L")}`;
}

// Where everything is at the time t of the cycle:
// the pen (x, y), whether it touches the paper, how much of every line is written, and the opacity of the lines.
export function sceneAt(t) {
  const lastDrawEnd = (LINES - 1) * (LINE_MS + MOVE_MS) + LINE_MS;
  const written = new Array(LINES).fill(LINE_START_X);
  let line = LINES - 1;
  let pen;
  let touching = false;
  let opacity = 1;

  for (let k = 0; k < LINES; k++) {
    const drawStart = k * (LINE_MS + MOVE_MS);
    if (t < drawStart) { line = k - 1; break; }
    if (t < drawStart + LINE_MS) {
      const x = LINE_START_X + (LINE_END_X - LINE_START_X) * easeInOut((t - drawStart) / LINE_MS);
      written[k] = x;
      pen = { x, y: waveY(k, x) };
      touching = true;
      line = k;
      break;
    }
    written[k] = LINE_END_X;
    if (k < LINES - 1 && t < drawStart + LINE_MS + MOVE_MS) {
      // lifted: from the end of this line to the start of the next one
      const u = easeInOut((t - drawStart - LINE_MS) / MOVE_MS);
      pen = {
        x: LINE_END_X + (LINE_START_X - LINE_END_X) * u,
        y: waveY(k, LINE_END_X) + (waveY(k + 1, LINE_START_X) - waveY(k, LINE_END_X)) * u,
      };
      line = k;
      break;
    }
  }

  if (!pen) {
    // after the last line: the lines fade and the pen goes back to the start of the first one
    const u = easeInOut((t - lastDrawEnd) / (CYCLE_MS - lastDrawEnd));
    pen = {
      x: LINE_END_X + (LINE_START_X - LINE_END_X) * u,
      y: waveY(LINES - 1, LINE_END_X) + (waveY(0, LINE_START_X) - waveY(LINES - 1, LINE_END_X)) * u,
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
let frame = 0;
let inkTimer = null;
let released = false;
let stopHandler = null;
let pendingMessage = ""; // the texts of the loading, written when the page is built and every time they change
let pendingProgress = "";
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
      <div class="loading-actions">
        <button type="button" class="loading-button loading-stop" hidden>إيقاف الترجمة</button>
        <button type="button" class="loading-button loading-release" hidden>متابعة العمل</button>
      </div>
    </div>`;

  parts.scene = element.querySelector(".loading-scene");
  parts.lines = [...element.querySelectorAll(".loading-line")];
  parts.title = element.querySelector(".loading-title");
  parts.progress = element.querySelector(".loading-progress");
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
export function drawFrame(t) {
  if (!overlay) return;
  const scene = sceneAt(t);
  parts.lines.forEach((path, k) => {
    path.setAttribute("d", scene.written[k] > LINE_START_X ? wavePoints(k, scene.written[k]) : "");
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
  if (reduced) {
    // no movement: the lines are written and the pen rests on the last one
    parts.lines.forEach((path, k) => path.setAttribute("d", wavePoints(k, LINE_END_X)));
    parts.pen.style.transform = `translate(${LINE_END_X - NIB.x}px, ${waveY(LINES - 1, LINE_END_X) - NIB.y}px)`;
    return;
  }
  const start = performance.now();
  const step = (now) => {
    drawFrame((now - start) % CYCLE_MS);
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
  requestAnimationFrame(() => overlay?.classList.add("is-visible"));
  releaseTimer = setTimeout(() => {
    if (parts.release) parts.release.hidden = false;
  }, RELEASE_AFTER_MS);
}

function hide() {
  clearTimeout(releaseTimer);
  stopMotion();
  setPageBusy(false);
  const closing = overlay;
  overlay = null;
  if (!closing) return;
  closing.classList.remove("is-visible");
  setTimeout(() => closing.remove(), 350);
}

// options: {message, onStop}. Returns the function that ends this loading (it is safe to call it twice).
export function beginLoading({ message = "جارٍ الترجمة…", onStop = null } = {}) {
  if (count === 0) {
    stopHandler = onStop;
    clearTimeout(showTimer);
    showTimer = setTimeout(show, SHOW_AFTER_MS);
    pendingMessage = message;
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

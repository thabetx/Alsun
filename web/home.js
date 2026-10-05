// ---------- upload box ----------
const fileInput = document.getElementById("file-input");
const dropzone = document.getElementById("dropzone");
const chip = document.getElementById("file-chip");
const fileName = document.getElementById("file-name");
const fileSize = document.getElementById("file-size");
const btnStart = document.getElementById("btn-start");
const langSelect = document.getElementById("lang-select");
let chosen = null;

function formatSize(bytes) {
  return bytes >= 1048576
    ? (bytes / 1048576).toFixed(1) + " MB"
    : Math.max(1, Math.round(bytes / 1024)) + " KB";
}

function setFile(file) {
  const isPdf = file && (file.type === "application/pdf" || /\.pdf$/i.test(file.name));
  if (!isPdf) {
    chosen = null;
    if (file) alert("الرجاء اختيار ملف بصيغة PDF.");
  } else {
    chosen = file;
  }
  fileName.textContent = chosen ? chosen.name : "";
  fileSize.textContent = chosen ? formatSize(chosen.size) : "";
  chip.hidden = !chosen;
  dropzone.hidden = !!chosen;
  btnStart.disabled = !chosen;
}

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
document.getElementById("file-remove").addEventListener("click", () => {
  fileInput.value = "";
  setFile(null);
});

["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); }));
dropzone.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

btnStart.addEventListener("click", () => {
  if (!chosen) return;
  sessionStorage.setItem("alsun_upload", JSON.stringify({
    name: chosen.name, size: chosen.size, lang: langSelect.value,
  }));
  // Demo build: the viewer still shows the fixed sample book.
  location.href = "/app";
});

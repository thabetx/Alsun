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

// the same limit as the server (python/books.py), so a file that is too big is refused before it is sent
const MAX_BYTES = 50 * 1024 * 1024;
const errorBox = document.getElementById("upload-error");

function showError(text) {
  errorBox.textContent = text;
  errorBox.hidden = !text;
}

function setFile(file) {
  const isPdf = file && (file.type === "application/pdf" || /\.pdf$/i.test(file.name));
  showError("");
  if (!isPdf) {
    chosen = null;
    if (file) showError("الرجاء اختيار ملف بصيغة PDF.");
  } else if (file.size > MAX_BYTES) {
    chosen = null;
    showError("حجم الملف أكبر من 50 ميغابايت.");
  } else {
    chosen = file;
  }
  // the server starts to load the quran detector now, so it is ready when the translation starts
  if (chosen) fetch("/warmup", { method: "POST" }).catch(() => {});
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

const OLD_SERVER_TEXT = "الخادم يعمل بنسخة قديمة لا تدعم رفع الكتب، أعد تشغيله ثم حاول مرة أخرى.";

// what the server says (python/books.py), in arabic
function uploadErrorText(detail) {
  const pages = /more than (\d+) pages/.exec(detail);
  if (pages) return `عدد صفحات الكتاب أكبر من الحد المسموح (${pages[1]} صفحة).`;
  const known = [
    ["bigger than", "حجم الملف أكبر من 50 ميغابايت."],
    ["empty", "الملف فارغ."],
    ["not a pdf", "هذا الملف ليس PDF صالحًا."],
    ["password", "الملف محمي بكلمة مرور، أزلها ثم ارفعه."],
    ["can not be read", "تعذّر قراءة الملف، قد يكون تالفًا."],
    ["no pages", "الملف لا يحتوي على صفحات."],
  ].find(([word]) => detail.includes(word));
  return known ? known[1] : "تعذّر رفع الكتاب، حاول مرة أخرى.";
}

// sends the pdf to the server (the body of the request is the file) and gives the book {id, name, pages, size}
function uploadBook(file, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `/books?name=${encodeURIComponent(file.name)}`);
    request.setRequestHeader("Content-Type", "application/pdf");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new Error("تعذّر الوصول إلى الخادم، تأكد من تشغيله."));
    request.onload = () => {
      let body = {};
      try {
        body = JSON.parse(request.responseText);
      } catch (error) {
        // not json: the generic message is used
      }
      if (request.status === 200) resolve(body);
      // a server that started before the upload existed has no /books: it has to be started again
      else if (request.status === 404 || request.status === 405) reject(new Error(OLD_SERVER_TEXT));
      else reject(new Error(uploadErrorText(String(body.detail || ""))));
    };
    request.send(file);
  });
}

const startLabel = btnStart.innerHTML;

btnStart.addEventListener("click", async () => {
  if (!chosen) return;
  showError("");
  btnStart.disabled = true;
  try {
    const book = await uploadBook(chosen, (percent) => {
      btnStart.textContent = percent < 100 ? `جارٍ الرفع… ${percent}%` : "جارٍ الفحص…";
    });
    sessionStorage.setItem("alsun_upload", JSON.stringify({
      name: book.name, size: book.size, book: book.id, lang: langSelect.value,
    }));
    location.href = `/app?book=${encodeURIComponent(book.id)}`;
  } catch (error) {
    showError(error.message);
    btnStart.innerHTML = startLabel;
    btnStart.disabled = !chosen;
  }
});

import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.min.mjs";
pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.worker.min.mjs";

const SVGNS = "http://www.w3.org/2000/svg";
const blockRows = document.getElementById("block-rows");
const pdfPages = document.getElementById("pdf-pages");
const checkAll = document.getElementById("check-all");

function stripHtml(html) {
  const div = document.createElement("div");
  div.innerHTML = html || "";
  return div.textContent.trim();
}

function collectBlocks(node, out = []) {
  for (const child of node.children || []) {
    if (child.block_type !== "Page") out.push(child);
    collectBlocks(child, out);
  }
  return out;
}

function makeRow(b) {
  const tr = document.createElement("tr");
  tr.className = "block-row";
  tr.dataset.id = b.id;

  const text = stripHtml(b.html);
  const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  tr.innerHTML = `
    <td class="col-check text-center">
      <input class="form-check-input block-check" type="checkbox" data-id="${b.id}">
    </td>
    <td class="col-original">
      <div class="original-text" contenteditable="true" dir="rtl"
           data-id="${b.id}" aria-label="النص الأصلي">${escaped}</div>
    </td>
    <td class="translated-cell">
      <div class="translated-text" contenteditable="true" dir="ltr"
           data-id="${b.id}" aria-label="الترجمة">Dummy translation text, to be replaced with the actual translation.</div>
    </td>
    <td class="col-actions text-center">
      <div class="row-actions">
        <div class="dropdown dropend">
          <button class="btn btn-dots" type="button"
                  data-bs-toggle="dropdown" aria-expanded="false"
                  aria-label="إجراءات" title="إجراءات">&#8942;</button>
          <ul class="dropdown-menu">
            <li><button class="dropdown-item" type="button" data-action="translate">ترجمة</button></li>
            <li><button class="dropdown-item" type="button" data-action="summarize">تلخيص</button></li>
            <li><button class="dropdown-item" type="button" data-action="revert">استعادة التغييرات</button></li>
            <li><hr class="dropdown-divider"></li>
            <li><button class="dropdown-item text-danger" type="button" data-action="delete">حذف</button></li>
          </ul>
        </div>
      </div>
    </td>`;

  const check = tr.querySelector(".block-check");
  const checkTd = tr.querySelector(".col-check");
  const original = tr.querySelector(".original-text");
  const translated = tr.querySelector(".translated-text");
  check.addEventListener("change", () => {
    tr.classList.toggle("active", check.checked);
  });
  check.addEventListener("click", (e) => e.stopPropagation());
  checkTd.addEventListener("click", () => {
    check.checked = !check.checked;
    tr.classList.toggle("active", check.checked);
  });

  const editClass = (on) => tr.classList.toggle("editing", on);
  original.addEventListener("focus", () => editClass(true));
  original.addEventListener("blur", () => editClass(false));
  translated.addEventListener("focus", () => editClass(true));
  translated.addEventListener("blur", () => editClass(false));

  const dots = tr.querySelector(".btn-dots");
  dots.addEventListener("click", (e) => e.stopPropagation());

  tr.querySelectorAll(".dropdown-item").forEach((item) => {
    item.addEventListener("click", (e) => {
      e.stopPropagation();
      console.log(item.dataset.action, b.id);
    });
  });

  return tr;
}

async function main() {
  let data;
  try {
    data = await (await fetch("../data/two-pages.json")).json();
  } catch (e) {
    blockRows.innerHTML =
      '<tr><td colspan="3" style="color:#ff8a80">تعذّر تحميل ../data/two-pages.json. ' +
      "قدّم مجلد المشروع عبر HTTP وافتح http://localhost:8000/datalab/</td></tr>";
    return;
  }

  let pdf;
  try {
    pdf = await pdfjsLib.getDocument("../data/two-pages.pdf").promise;
  } catch (e) {
    pdfPages.innerHTML =
      '<div class="block" style="color:#ff8a80">تعذّر تحميل ../data/two-pages.pdf (يجب تقديمه عبر HTTP).</div>';
    return;
  }

  const pages = (data.children || []).filter((c) => c.block_type === "Page");
  const scale = 1.5;

  pages.forEach((page, pi) => {
    // ---- right: render PDF page with overlay ----
    const sheet = document.createElement("div");
    sheet.className = "page-sheet";
    pdfPages.appendChild(sheet);

    const canvas = document.createElement("canvas");
    canvas.className = "page-canvas";
    sheet.appendChild(canvas);

    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("class", "page-overlay");
    svg.setAttribute("preserveAspectRatio", "none");
    sheet.appendChild(svg);

    const [x0, y0, x1, y1] = page.bbox;
    svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);

    pdf.getPage(pi + 1).then((pdfPage) => {
      const viewport = pdfPage.getViewport({ scale });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      svg.setAttribute("width", viewport.width);
      svg.setAttribute("height", viewport.height);
      pdfPage.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
    });

    const blocks = collectBlocks(page);

    for (const b of blocks) {
      const tr = makeRow(b);
      blockRows.appendChild(tr);

      const poly = (b.polygon && b.polygon.length)
        ? addPolygon(svg, b.polygon)
        : null;

      const highlight = (on) => {
        poly?.classList.toggle("highlight", on);
        tr.classList.toggle("active", on);
      };

      tr.addEventListener("mouseenter", () => {
        highlight(true);
        if (poly) poly.scrollIntoView({ block: "center", behavior: "smooth" });
      });
      tr.addEventListener("mouseleave", () => highlight(false));

      if (poly) {
        poly.addEventListener("mouseenter", () => {
          highlight(true);
          tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
        poly.addEventListener("mouseleave", () => highlight(false));
      }
    }
  });

  checkAll.addEventListener("change", () => {
    blockRows.querySelectorAll(".block-check").forEach((c) => {
      c.checked = checkAll.checked;
      c.closest("tr").classList.toggle("active", checkAll.checked);
    });
  });
}

function addPolygon(svg, points) {
  const poly = document.createElementNS(SVGNS, "polygon");
  poly.setAttribute("points", points.map((p) => p.join(",")).join(" "));
  svg.appendChild(poly);
  return poly;
}

main();
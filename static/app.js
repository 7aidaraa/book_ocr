"use strict";

const $ = (id) => document.getElementById(id);

let bookId = null;
let pollTimer = null;

// countdown: ETA computed from the measured pages/second, ticking every second
let convStart = null;
let etaTarget = null;
let tickTimer = null;

function fmtDur(totalSec) {
  const s = Math.max(0, Math.round(totalSec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const two = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(sec)}` : `${m}:${two(sec)}`;
}

function renderEta() {
  const el = $("eta");
  if (!el) return;
  el.textContent = etaTarget === null ? "يُحسب..." : fmtDur((etaTarget - Date.now()) / 1000);
}

function startCountdown() {
  convStart = Date.now();
  etaTarget = null;
  renderEta();
  if (!tickTimer) tickTimer = setInterval(renderEta, 1000);
}

function stopCountdown() {
  clearInterval(tickTimer);
  tickTimer = null;
  etaTarget = null;
}

function showError(msg) {
  $("error-text").textContent = msg;
  $("error-text").hidden = !msg;
}

function fmtSize(bytes) {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " م.ب";
  return Math.max(1, Math.round(bytes / 1024)) + " ك.ب";
}

function setUploadStatus(msg) {
  $("upload-status").textContent = msg;
  $("upload-status").hidden = !msg;
}

// XHR rather than fetch: it reports upload progress, which matters for
// large books on a slow phone connection.
function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch (_) {
        reject(new Error(`الخادم ردّ بحالة ${xhr.status} بدل بيانات صالحة`));
        return;
      }
      if (xhr.status === 200) resolve(body);
      else reject(new Error(body.detail || `حالة ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("انقطع الاتصال بالخادم"));
    xhr.ontimeout = () => reject(new Error("انتهت مهلة الرفع"));
    xhr.timeout = 15 * 60 * 1000;
    xhr.send(form);
  });
}

$("pdf-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  showError("");
  $("file-info").hidden = true;
  $("progress-section").hidden = true;
  $("done-section").hidden = true;
  setUploadStatus(`جارٍ رفع «${file.name}» (${fmtSize(file.size)})... 0%`);

  try {
    const info = await uploadFile(file, (pct) =>
      setUploadStatus(
        pct < 100
          ? `جارٍ رفع «${file.name}» (${fmtSize(file.size)})... ${pct}%`
          : "اكتمل الرفع — يقرأ الخادم الملف..."
      )
    );
    setUploadStatus("");
    bookId = info.book_id;
    $("file-name").textContent = info.filename;
    $("file-size").textContent = fmtSize(info.size_bytes);
    $("page-count").textContent = info.page_count;
    $("file-info").hidden = false;
  } catch (err) {
    setUploadStatus("");
    showError("فشل رفع الملف: " + err.message);
  }
});

$("start-btn").addEventListener("click", async () => {
  if (!bookId) return;
  showError("");
  $("start-btn").disabled = true;
  const lang = $("lang-select").value;
  try {
    const res = await fetch(`/api/convert/${bookId}?lang=${lang}`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    $("progress-section").hidden = false;
    startCountdown();
    pollTimer = setInterval(poll, 1500);
  } catch (err) {
    $("start-btn").disabled = false;
    showError("تعذر بدء التحويل: " + err.message);
  }
});

async function poll() {
  try {
    const res = await fetch(`/api/status/${bookId}`);
    if (!res.ok) return;
    const s = await res.json();

    const pct = s.page_count ? Math.round((s.current_page / s.page_count) * 100) : 0;
    $("bar-fill").style.width = pct + "%";
    $("progress-count").textContent = `${s.current_page} / ${s.page_count}`;
    $("status-text").textContent = s.message || s.state;
    $("engine-name").textContent = s.ocr_engine;

    // re-anchor the countdown to the measured page rate on every poll
    if (s.state === "running" && convStart && s.current_page > 0) {
      const elapsed = (Date.now() - convStart) / 1000;
      const remaining = (elapsed / s.current_page) * (s.page_count - s.current_page);
      etaTarget = Date.now() + remaining * 1000;
    }

    if (s.state === "done" || s.state === "failed") {
      clearInterval(pollTimer);
      stopCountdown();
      $("start-btn").disabled = false;
      if (s.state === "done") {
        $("done-section").hidden = false;
        const failed = s.failed_pages || [];
        $("done-text").textContent = failed.length
          ? `اكتمل التحويل مع فشل ${failed.length} صفحة: ${failed.join("، ")}`
          : "اكتمل التحويل بنجاح ✓";
        $("output-dir").textContent = s.output_dir;
        $("download-link").href = `/api/result/${bookId}/book.md`;
        $("zip-link").href = `/api/result/${bookId}/zip`;
        $("reader-link").href = `/reader/${encodeURIComponent(s.book_name)}`;
        loadBooks();
      } else {
        showError("فشل التحويل: " + (s.error || ""));
      }
    }
  } catch (_) {
    /* transient polling errors are ignored */
  }
}

$("forget-btn").addEventListener("click", async () => {
  if (!bookId) return;
  if (!confirm("حذف الكتاب ونتائجه من الخادم نهائيًا؟ تأكد أنك نزّلت ملف ZIP أولًا.")) return;
  try {
    const res = await fetch(`/api/book/${bookId}`, { method: "DELETE" });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    bookId = null;
    $("done-section").hidden = true;
    $("file-info").hidden = true;
    $("progress-section").hidden = true;
    $("pdf-input").value = "";
    loadBooks();
  } catch (err) {
    showError("تعذر الحذف: " + err.message);
  }
});

async function loadBooks() {
  try {
    const res = await fetch("/api/books");
    if (!res.ok) return;
    const { books } = await res.json();
    const list = $("books-list");
    list.innerHTML = "";
    for (const b of books) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = b.reader_url;
      a.textContent = b.book_name;
      a.target = "_blank";
      li.appendChild(a);
      const info = document.createElement("span");
      info.className = "book-meta";
      info.textContent = ` — ${b.page_count} صفحة`
        + (b.failed_pages.length ? ` (فشل ${b.failed_pages.length})` : "");
      li.appendChild(info);
      list.appendChild(li);
    }
    $("books-section").hidden = books.length === 0;
  } catch (_) { /* offline list is best-effort */ }
}

loadBooks();

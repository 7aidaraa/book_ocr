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
        const total = s.page_count || 0;
        $("done-text").textContent = !failed.length
          ? "اكتمل التحويل بنجاح ✓"
          : failed.length === total
          ? `فشلت كل الصفحات (${total}) — المحرك لم يعمل`
          : `اكتمل التحويل مع فشل ${failed.length} من ${total} صفحة`;
        // show WHY, right here, instead of hiding it in the output files
        $("fail-reason").hidden = !s.first_error;
        if (s.first_error) $("fail-reason").textContent = "سبب الفشل: " + s.first_error;
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

$("selftest-btn").addEventListener("click", async () => {
  const out = $("selftest-out");
  out.hidden = false;
  out.textContent = "جارٍ الفحص... (قد يستغرق دقيقة عند أول تحميل للنماذج)";
  try {
    const res = await fetch("/api/selftest");
    const r = await res.json();
    out.textContent = [
      `المحرك: ${r.engine} ${r.engine_version || ""}`,
      `المعالج: ${r.device}`,
      r.ok ? "✓ المحرك يعمل" : "✗ المحرك لا يعمل",
      r.text ? `النص المستخرج: ${r.text}` : "",
      r.error ? `الخطأ: ${r.error}` : "",
      r.traceback ? `\n${r.traceback}` : "",
    ].filter(Boolean).join("\n");
  } catch (err) {
    out.textContent = "تعذر الفحص: " + err.message;
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

// ---- hub mode: this deployment is the fixed front door; show the live
// ---- GPU session entry when a Colab session has registered itself.
async function refreshHub() {
  try {
    const res = await fetch("/api/gpu-session");
    if (!res.ok) return;
    const s = await res.json();
    $("hub-online").hidden = !s.online;
    $("hub-offline").hidden = s.online;
    if (s.online) $("hub-enter").href = s.url;
  } catch (_) { /* best-effort */ }
}

(async () => {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const cfg = await res.json();
    if (!cfg.hub_mode) return;
    $("hub-colab").href = cfg.colab_url;
    $("hub-section").hidden = false;
    refreshHub();
    setInterval(refreshHub, 10000);
  } catch (_) { /* non-hub deployments just skip this */ }
})();

// ---- book discovery: search a source, then let the server do the rest.
// The client never sends a URL — only an id the server itself issued.
let acquireTimer = null;

function stepState(job) {
  const done = { found: true };
  const stage = (job.progress && job.progress.stage) || job.state;
  if (["downloading", "processing", "completed"].includes(stage)) done.downloading = true;
  if (job.provenance) done.verified = true;
  if (stage === "completed" || job.state === "completed") {
    done.downloading = done.verified = done.processing = done.completed = true;
  }
  return { done, active: stage };
}

function renderAcquire(job) {
  $("acquire-title").textContent = job.title || "";
  const { done, active } = stepState(job);
  document.querySelectorAll("#acquire-steps li").forEach((li) => {
    const step = li.dataset.step;
    li.classList.toggle("done", Boolean(done[step]));
    li.classList.toggle("active", step === active && !done[step]);
  });

  const p = job.progress || {};
  const pct = p.total ? Math.round((p.current / p.total) * 100) : 0;
  $("acquire-bar").style.width = pct + "%";
  $("acquire-status").textContent =
    job.message + (p.total && p.stage === "processing" ? ` (${p.current}/${p.total})` : "");

  $("acquire-error").hidden = !job.error;
  if (job.error) $("acquire-error").textContent = job.error;

  const finished = ["completed", "failed", "cancelled"].includes(job.state);
  $("acquire-cancel").hidden = finished;
  $("acquire-reader").hidden = job.state !== "completed";
  if (job.state === "completed") {
    $("acquire-reader").href = "/reader/" + encodeURIComponent(job.book_name);
  }
  return finished;
}

async function pollAcquire(jobId) {
  const res = await fetch("/api/books/jobs/" + jobId);
  if (!res.ok) return;
  if (renderAcquire(await res.json())) clearInterval(acquireTimer);
}

async function acquire(candidateId, title) {
  const res = await fetch("/api/books/acquire", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_id: candidateId }),
  });
  const job = await res.json();
  if (!res.ok) { $("search-note").hidden = false; $("search-note").textContent = job.detail; return; }
  $("acquire-section").hidden = false;
  $("acquire-error").hidden = true;
  job.title = job.title || title;
  renderAcquire(job);
  $("acquire-cancel").onclick = () =>
    fetch(`/api/books/jobs/${job.id}/cancel`, { method: "POST" });
  clearInterval(acquireTimer);
  acquireTimer = setInterval(() => pollAcquire(job.id), 1500);
}

function renderResults(data) {
  const list = $("search-results");
  list.innerHTML = "";
  $("search-note").hidden = !data.note;
  if (data.note) $("search-note").textContent = data.note;

  data.candidates.forEach((c) => {
    const li = document.createElement("li");
    const meta = [c.author, c.source, c.volume,
                  c.pages ? c.pages + " صفحة" : null,
                  "تطابق " + Math.round(c.confidence * 100) + "%"]
      .filter(Boolean).join(" · ");
    const title = document.createElement("div");
    title.className = "result-title";
    title.textContent = c.title;
    const info = document.createElement("div");
    info.className = "result-meta";
    info.textContent = meta;
    const button = document.createElement("button");
    button.className = "btn primary";
    button.textContent = data.needs_confirmation ? "اختيار" : "تحويل إلى Markdown";
    button.onclick = () => acquire(c.id, c.title);
    li.append(title, info, button);
    list.appendChild(li);
  });
  if (!data.candidates.length && !data.note) {
    $("search-note").hidden = false;
    $("search-note").textContent = "لا نتائج.";
  }
}

async function searchBooks() {
  const query = $("book-query").value.trim();
  if (!query) return;
  $("search-btn").disabled = true;
  $("search-results").innerHTML = "";
  try {
    const res = await fetch("/api/books/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, author: $("book-author").value.trim() || null }),
    });
    const data = await res.json();
    if (!res.ok) {
      $("search-note").hidden = false;
      $("search-note").textContent = data.detail;
      return;
    }
    renderResults(data);
  } finally {
    $("search-btn").disabled = false;
  }
}

// Show the search box only when a source is actually enabled. With every
// real source still UNVERIFIED, the manual upload stays the only path.
(async () => {
  try {
    const res = await fetch("/api/books/sources");
    if (!res.ok) return;
    const { sources } = await res.json();
    if (!sources.some((s) => s.status.enabled)) return;
    $("search-section").hidden = false;
    $("search-btn").onclick = searchBooks;
    $("book-query").addEventListener("keydown", (e) => {
      if (e.key === "Enter") searchBooks();
    });
  } catch (_) { /* the upload flow works regardless */ }
})();

"use strict";

const $ = (id) => document.getElementById(id);

let bookId = null;
let pollTimer = null;

function showError(msg) {
  $("error-text").textContent = msg;
  $("error-text").hidden = !msg;
}

function fmtSize(bytes) {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " م.ب";
  return Math.max(1, Math.round(bytes / 1024)) + " ك.ب";
}

$("pdf-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  showError("");

  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/upload", { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const info = await res.json();
    bookId = info.book_id;
    $("file-name").textContent = info.filename;
    $("file-size").textContent = fmtSize(info.size_bytes);
    $("page-count").textContent = info.page_count;
    $("file-info").hidden = false;
    $("progress-section").hidden = true;
    $("done-section").hidden = true;
  } catch (err) {
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

    if (s.state === "done" || s.state === "failed") {
      clearInterval(pollTimer);
      $("start-btn").disabled = false;
      if (s.state === "done") {
        $("done-section").hidden = false;
        const failed = s.failed_pages || [];
        $("done-text").textContent = failed.length
          ? `اكتمل التحويل مع فشل ${failed.length} صفحة: ${failed.join("، ")}`
          : "اكتمل التحويل بنجاح ✓";
        $("output-dir").textContent = s.output_dir;
        $("download-link").href = `/api/result/${bookId}/book.md`;
      } else {
        showError("فشل التحويل: " + (s.error || ""));
      }
    }
  } catch (_) {
    /* transient polling errors are ignored */
  }
}

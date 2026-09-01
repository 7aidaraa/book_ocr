/**
 * Arabic Book OCR — نسخة Google Drive
 * ------------------------------------
 * تحويل كتب PDF العربية المصوّرة إلى Markdown عبر محرك OCR الخاص بـGoogle،
 * كل شيء داخل حساب Google الخاص بك، مجانًا، بلا خادم.
 *
 * طريقة العمل بعد التثبيت:
 *   1. ضع ملف PDF في مجلد «كتب-للتحويل» في Drive.
 *   2. الأداة تعمل تلقائيًا كل 5 دقائق: تحوّل صفحةً صفحة (رقم الصفحة محفوظ).
 *   3. تابع ملف «الحالة.txt» داخل مجلد الكتاب في «كتب-محوّلة».
 *   4. عند الاكتمال تجد: pages/001.md ... + book.md + metadata.json،
 *      ويُنقل ملف PDF الأصلي إلى مجلد الكتاب.
 *
 * التثبيت (مرة واحدة): انظر خطوات الإعداد في README المشروع، وخلاصتها:
 *   - script.google.com ← مشروع جديد ← الصق هذا الملف كاملًا.
 *   - من قائمة Services (+) أضف «Drive API» (المعرّف Drive، الإصدار v2).
 *   - شغّل الدالة setup مرة واحدة ووافق على الأذونات.
 *
 * حدود واقعية: حصة المشغّلات للحسابات المجانية ≈ 90 دقيقة يوميًا،
 * أي كتاب كبير واحد تقريبًا في اليوم.
 */

var INPUT_FOLDER = 'كتب-للتحويل';
var OUTPUT_FOLDER = 'كتب-محوّلة';
var OCR_LANGUAGE = 'ar';
var TIME_BUDGET_MS = 4.5 * 60 * 1000; // نتوقف قبل حد الست دقائق
var PDFLIB_URL =
  'https://cdnjs.cloudflare.com/ajax/libs/pdf-lib/1.17.1/pdf-lib.min.js';

/** شغّلها مرة واحدة: تنشئ المجلدات والمشغّل الدوري. */
function setup() {
  getOrCreateFolder_(INPUT_FOLDER);
  getOrCreateFolder_(OUTPUT_FOLDER);
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(5).create();
  Logger.log('✓ تم الإعداد. ضع أي PDF في مجلد: ' + INPUT_FOLDER);
}

/** إيقاف الأداة نهائيًا (يمكن إعادة تشغيلها بـsetup). */
function stopAll() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    ScriptApp.deleteTrigger(t);
  });
}

/** نقطة الدخول الدورية — وتصلح للتشغيل اليدوي أيضًا. */
async function tick() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return; // تشغيل سابق ما يزال يعمل
  try {
    var deadline = Date.now() + TIME_BUDGET_MS;
    var pdf = nextPdf_();
    if (!pdf) return;
    await processBook_(pdf, deadline);
  } finally {
    lock.releaseLock();
  }
}

// ---------------------------------------------------------------- داخلي

function nextPdf_() {
  var files = getOrCreateFolder_(INPUT_FOLDER).getFilesByType(MimeType.PDF);
  return files.hasNext() ? files.next() : null;
}

function stateKey_(file) {
  return 'book:' + file.getId();
}

function loadState_(file) {
  var raw = PropertiesService.getScriptProperties().getProperty(stateKey_(file));
  return raw ? JSON.parse(raw) : null;
}

function saveState_(file, state) {
  PropertiesService.getScriptProperties().setProperty(
    stateKey_(file), JSON.stringify(state));
}

async function processBook_(pdfFile, deadline) {
  var bookName = pdfFile.getName().replace(/\.pdf$/i, '');
  var outRoot = getOrCreateFolder_(OUTPUT_FOLDER);
  var bookDir = getOrCreateSubfolder_(outRoot, bookName);
  var pagesDir = getOrCreateSubfolder_(bookDir, 'pages');

  var lib = getPdfLib_();
  var srcBytes = new Uint8Array(pdfFile.getBlob().getBytes());
  var srcDoc = await lib.PDFDocument.load(srcBytes, { ignoreEncryption: true });
  var pageCount = srcDoc.getPageCount();

  var state = loadState_(pdfFile) || { next: 1, failed: [], started: nowIso_() };

  // مرحلة OCR: صفحة صفحة، ضمن ميزانية الوقت
  while (state.next <= pageCount && Date.now() < deadline) {
    var n = state.next;
    try {
      var single = await lib.PDFDocument.create();
      var copied = await single.copyPages(srcDoc, [n - 1]);
      single.addPage(copied[0]);
      var pageBytes = await single.save();
      var text = ocrPdfBytes_(pageBytes, bookName + ' p' + n);
      writeFile_(pagesDir, pad3_(n) + '.md',
        pageMarkdown_(bookName, n, 'ok', text, null));
    } catch (e) {
      state.failed.push(n);
      if (!state.firstError) state.firstError = String(e);
      writeFile_(pagesDir, pad3_(n) + '.md',
        pageMarkdown_(bookName, n, 'error', '', String(e)));
    }
    state.next = n + 1;
    saveState_(pdfFile, state);
    setStatus_(bookDir, 'قيد التحويل: صفحة ' + n + ' من ' + pageCount +
      (state.failed.length ? ' — فشل ' + state.failed.length : ''), state.firstError);

    // كل الصفحات تفشل ⇒ عطل في المحرك لا في الكتاب: نتوقف بدل إحراق الحصة
    if (state.failed.length >= 3 && state.failed.length === n) {
      setStatus_(bookDir, '✗ توقّف: فشلت أول ' + n + ' صفحات — عطل في الإعداد لا في الكتاب.\n' +
        'أصلح السبب أدناه ثم أعد وضع الملف في ' + INPUT_FOLDER, state.firstError);
      return;
    }
  }

  if (state.next <= pageCount) return; // نكمل في التشغيلة القادمة

  // مرحلة التجميع والختام
  assembleBook_(bookDir, pagesDir, bookName, pageCount);
  writeFile_(bookDir, 'metadata.json', JSON.stringify({
    book_name: bookName,
    author: null,
    original_filename: pdfFile.getName(),
    page_count: pageCount,
    processed_at: nowIso_(),
    ocr_engine: 'google-drive',
    ocr_engine_version: 'Drive API v2',
    processing_settings: { ocr_language: OCR_LANGUAGE },
    verification_status: 'unverified',
    failed_pages: state.failed,
  }, null, 2));
  setStatus_(bookDir, '✓ اكتمل: ' + pageCount + ' صفحة' +
    (state.failed.length ? '، فشل منها: ' + state.failed.join('، ') : ''),
    state.firstError);

  pdfFile.moveTo(bookDir); // الأصل يُحفظ مع الناتج ولا يُمس
  PropertiesService.getScriptProperties().deleteProperty(stateKey_(pdfFile));
}

/**
 * OCR لصفحة واحدة: PDF ← مستند Google (بمحرك OCR) ← نص ← حذف المؤقت.
 * يدعم خدمة Drive بإصدارَيها: v2 (insert) و v3 (create).
 */
function ocrPdfBytes_(bytes, tmpName) {
  var blob = Utilities.newBlob(bytes, 'application/pdf', tmpName + '.pdf');
  var docId = driveConvertWithOcr_(blob, 'tmp-ocr-' + tmpName);
  try {
    var text = '';
    var lastErr = null;
    for (var i = 0; i < 6; i++) { // المستند قد يتأخر لحظات بعد التحويل
      try { text = DocumentApp.openById(docId).getBody().getText(); lastErr = null; break; }
      catch (e) { lastErr = e; Utilities.sleep(1500); }
    }
    if (lastErr) throw lastErr;
    return text;
  } finally {
    driveTrash_(docId);
  }
}

function driveConvertWithOcr_(blob, title) {
  var DOC_MIME = 'application/vnd.google-apps.document';
  if (typeof Drive === 'undefined' || !Drive.Files) {
    throw new Error('خدمة Drive غير مضافة: Services (+) ← Drive API');
  }
  if (Drive.Files.insert) { // v2
    return Drive.Files.insert(
      { title: title, mimeType: DOC_MIME }, blob,
      { ocr: true, ocrLanguage: OCR_LANGUAGE }).id;
  }
  if (Drive.Files.create) { // v3
    return Drive.Files.create(
      { name: title, mimeType: DOC_MIME }, blob,
      { ocrLanguage: OCR_LANGUAGE }).id;
  }
  throw new Error('نسخة Drive غير مدعومة (لا insert ولا create)');
}

function driveTrash_(fileId) {
  try {
    if (Drive.Files.trash) Drive.Files.trash(fileId);          // v2
    else if (Drive.Files.update) Drive.Files.update({ trashed: true }, fileId); // v3
    else DriveApp.getFileById(fileId).setTrashed(true);
  } catch (e) { /* التنظيف ليس حرجًا */ }
}

/**
 * فحص سريع: يحوّل صفحة واحدة من أول كتاب في مجلد الإدخال ويطبع النتيجة.
 * شغّلها من المحرر عند حدوث فشل، وانظر السجل (Execution log).
 */
async function selfTest() {
  var pdfFile = nextPdf_();
  if (!pdfFile) { Logger.log('✗ لا يوجد PDF في مجلد ' + INPUT_FOLDER); return; }
  Logger.log('الملف: ' + pdfFile.getName());
  Logger.log('نسخة Drive: ' + (typeof Drive === 'undefined' ? 'غير مضافة'
    : (Drive.Files && Drive.Files.insert ? 'v2' : (Drive.Files && Drive.Files.create ? 'v3' : 'مجهولة'))));
  try {
    var lib = getPdfLib_();
    var srcDoc = await lib.PDFDocument.load(
      new Uint8Array(pdfFile.getBlob().getBytes()), { ignoreEncryption: true });
    Logger.log('✓ قراءة PDF: ' + srcDoc.getPageCount() + ' صفحة');
    var single = await lib.PDFDocument.create();
    var copied = await single.copyPages(srcDoc, [0]);
    single.addPage(copied[0]);
    var bytes = await single.save();
    Logger.log('✓ استخراج الصفحة الأولى: ' + bytes.length + ' بايت');
    var text = ocrPdfBytes_(bytes, 'selftest');
    Logger.log('✓ OCR نجح. أول 300 حرف:\n' + text.slice(0, 300));
  } catch (e) {
    Logger.log('✗ فشل: ' + e + '\n' + (e.stack || ''));
  }
}

function pageMarkdown_(bookName, n, status, text, error) {
  var fm = ['---', 'book: ' + bookName, 'page: ' + n, 'source_page: ' + n,
    'printed_page: null', 'ocr_engine: google-drive', 'status: ' + status,
    'verified: false', '---', '', '# الصفحة ' + n, ''].join('\n');
  if (status === 'error') {
    return fm + '> ⚠ فشلت معالجة هذه الصفحة: ' + error + '\n';
  }
  // تنظيف محافظ فقط: إزالة فراغات نهايات الأسطر، لا دمج ولا حذف تشكيل
  var body = text.split('\n').map(function (l) { return l.replace(/\s+$/, ''); })
    .join('\n').replace(/^\n+|\n+$/g, '');
  return fm + body + '\n';
}

function assembleBook_(bookDir, pagesDir, bookName, pageCount) {
  var parts = ['# ' + bookName + '\n'];
  for (var n = 1; n <= pageCount; n++) {
    var it = pagesDir.getFilesByName(pad3_(n) + '.md');
    if (!it.hasNext()) continue;
    var content = it.next().getBlob().getDataAsString();
    var body = content.split('\n---\n').slice(1).join('\n---\n')
      .replace(/^\n+/, '');
    parts.push(body.replace(/^# /, '## ').replace(/\n+$/, '') + '\n');
  }
  writeFile_(bookDir, 'book.md', parts.join('\n'));
}

// ------------------------------------------------------------- أدوات صغيرة

function getPdfLib_() {
  if (this.__pdflib) return this.__pdflib;
  // pdf-lib مكتبة JS خالصة تعمل داخل Apps Script مع بديل بسيط لـsetTimeout
  this.setTimeout = function (fn) { fn(); return 0; };
  this.clearTimeout = function () {};
  eval(UrlFetchApp.fetch(PDFLIB_URL).getContentText());
  this.__pdflib = PDFLib;
  return PDFLib;
}

function getOrCreateFolder_(name) {
  var it = DriveApp.getFoldersByName(name);
  return it.hasNext() ? it.next() : DriveApp.createFolder(name);
}

function getOrCreateSubfolder_(parent, name) {
  var it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function writeFile_(folder, name, content) {
  var it = folder.getFilesByName(name);
  if (it.hasNext()) it.next().setContent(content);
  else folder.createFile(name, content, 'text/markdown');
}

function setStatus_(bookDir, msg, firstError) {
  writeFile_(bookDir, 'الحالة.txt', msg +
    (firstError ? '\n\nسبب الفشل:\n' + firstError : '') +
    '\n\nآخر تحديث: ' + nowIso_());
}

function pad3_(n) { return ('000' + n).slice(-3); }
function nowIso_() { return new Date().toISOString(); }

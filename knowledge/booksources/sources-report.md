# تقرير مصادر الكتب — Book Sources Report

آخر فحص: 2026-09-05 · بيئة الفحص: جلسة Claude Code السحابية (Linux)

هذا التقرير سجل وقائع فقط. لا يُدرج مصدر كـ`enabled` إلا بعد التحقق الفعلي
من كل بند في جدول الحالة. لا أسرار ولا cookies ولا tokens هنا.

## معجم الحالات

| الحالة | معناها |
|---|---|
| `discovered` | عُرف الموقع كمرشّح، بلا فحص |
| `reachable` | استُجيب لطلب HTTP فعلي |
| `searchable` | اكتُشفت آلية بحث حقيقية ووُثّقت |
| `downloadable` | اكتُشف رابط ملف حقيقي وتحقق أنه PDF |
| `termsChecked` | قُرئ robots.txt وشروط الاستخدام وسُجّل حكمهما |
| `enabled` | مفعّل في الكود — يتطلب كل ما سبق |

## جدول المصادر

| المصدر | id | discovered | reachable | searchable | downloadable | termsChecked | enabled |
|---|---|---|---|---|---|---|---|
| شبكة الفكر | `alfeker` | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| المكتبة الوقفية | `waqfeya` | ✓ | — | — | — | — | ✗ |
| Internet Archive | `archive` | ✓ | — | — | — | — | ✗ |

`—` = لم يُفحص بعد (لم يبدأ العمل عليه، وفق §29: شبكة الفكر أولًا).

## سجل الفحوص

### alfeker — شبكة الفكر (https://alfeker.net/)

الحالة: **`UNVERIFIED` / سبب: `NETWORK_BLOCKED`**

| المحاولة | الأداة | النتيجة |
|---|---|---|
| `GET https://alfeker.net/robots.txt` | curl عبر وكيل الجلسة | `curl (56): CONNECT tunnel failed, response 403` |
| نفس الرابط | أداة WebFetch | `EGRESS_BLOCKED: Access to alfeker.net is blocked by the network egress proxy` |

تأكيد من حالة الوكيل (`$HTTPS_PROXY/__agentproxy/status`):

```
"kind": "connect_rejected",
"detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
"host": "alfeker.net:443"
```

المنع من سياسة بوابة بيئة التنفيذ، لا من الموقع نفسه. لا يمكن الاستنتاج
من هذا أي شيء عن الموقع: لا توفّره، ولا شروطه، ولا وجود حماية عليه.

**ما لم يُكتشف — وممنوع تخمينه (§28):**

1. آلية البحث ومسارها.
2. شكل صفحة نتائج البحث.
3. شكل صفحة الكتاب.
4. رابط الملف: مباشر أم عبر صفحة وسيطة.
5. هل الملف PDF فعلًا.
6. هل يتطلب تسجيل دخول.
7. وجود CAPTCHA أو حماية Cloudflare.
8. نص robots.txt وشروط الاستخدام — وهذا وحده يكفي لمنع التفعيل.

**شرط رفع الحظر:** قراءة robots.txt وشروط الاستخدام قراءة فعلية أولًا.
إن منعا الوصول الآلي، يبقى المصدر `enabled: false` نهائيًا ويُعاد للمستخدم
`SOURCE_BLOCKED` مع اقتراح الرفع اليدوي.

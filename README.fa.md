<div dir="rtl">

# herat-nerkhbot

[English](README.md) | **فارسی**

یک ابزار پایتون که پست‌های نرخ اسعار را از یک کانال تلگرام جمع‌آوری می‌کند، هر پست را بدون تغییر در پایگاه داده نگه می‌دارد، و آن‌ها را به دادهٔ منظم و ساختارمند (نرخ خرید و فروش) تبدیل می‌کند تا بتوانید آن را تحلیل کنید یا در پروژهٔ دیگری به کار ببرید.

این ابزار برای کانال بازار اسعار هرات، [`@NerkhYab_Khorasan`](https://t.me/NerkhYab_Khorasan)، ساخته شده است و نرخ دالر آمریکا (USD)، یورو (EUR) و کلدار پاکستانی (PKR) را در برابر افغانی (AFN) ثبت می‌کند. بخش جمع‌آوری با هر کانال عمومی تلگرام کار می‌کند؛ بخش خواندن نرخ‌ها برای قالب نوشتاری همین کانال نوشته شده است.

> **وضعیت:** نسخهٔ 0.1.0، در مراحل اولیه اما قابل استفاده. دریافت تاریخچه و خواندن نرخ‌ها روی دادهٔ واقعی آزمایش شده است (از 3,539 پست، 1,861 ردیف نرخ بدون هیچ خطا به دست آمد). حالت زنده و اجرای طولانی‌مدت بدون نظارت هنوز در عمل کم آزمایش شده است. بخش [محدودیت‌ها](#s17) را ببینید.

---

## فهرست

- [چه کاری انجام می‌دهد](#s1)
- [چگونه کار می‌کند](#s2)
- [پیش‌نیازها](#s3)
- [نصب](#s4)
- [گرفتن کلیدهای API تلگرام](#s5)
- [تنظیمات](#s6)
- [شروع سریع](#s7)
- [دستورها](#s8)
- [پایگاه داده](#s9)
- [خواندن نرخ‌ها چگونه انجام می‌شود](#s10)
- [استفاده در پروژهٔ خودتان](#s11)
- [اجرا روی سرور](#s12)
- [ساختار پروژه](#s13)
- [توسعه و آزمایش‌ها](#s14)
- [امنیت و حریم خصوصی](#s15)
- [استفادهٔ مسئولانه](#s16)
- [محدودیت‌ها](#s17)
- [رفع اشکال](#s18)
- [مجوز](#s19)

---

<a id="s1"></a>

## چه کاری انجام می‌دهد

- **تاریخچه را دریافت می‌کند.** در اولین اجرا، پست‌های ۲۰ روز گذشته را می‌گیرد (قابل تنظیم).
- **پست‌های تازه را دنبال می‌کند.** پست‌های جدید و ویرایش‌شده به‌صورت زنده از تلگرام می‌رسند، و یک بررسی احتیاطی در هر ۱۵ دقیقه (قابل تنظیم) هر کمبودی را که به‌خاطر قطع اتصال یا راه‌اندازی دوباره پیش آمده باشد جبران می‌کند.
- **متن اصلی هرگز از بین نمی‌رود.** هر پست دقیقاً همان‌طور که بار اول دیده شده ذخیره می‌شود و هیچ‌گاه تغییر نمی‌کند. ویرایش‌ها به‌عنوان نسخه‌های جداگانه ذخیره می‌شوند.
- **تکرار ایجاد نمی‌کند.** خود پایگاه داده نسخهٔ دوم یک پست یا یک نرخ را نمی‌پذیرد، پس اجرای دوبارهٔ هر دستور همیشه بی‌خطر است.
- **نرخ‌ها را می‌خواند.** هر پست به ردیف‌های ساختارمند تبدیل می‌شود: بازار، ارز، خرید، فروش، زمان. نرخ‌های لحظه‌ای و نرخ‌های پایان روز از هم جدا می‌شوند.
- **دادهٔ مشکوک را علامت می‌زند.** نرخی که نادرست به نظر برسد (خرید بالاتر از فروش، فاصلهٔ بسیار زیاد، جهش ناگهانی) نگه داشته می‌شود اما با `suspect` علامت می‌خورد تا بتوانید آن را کنار بگذارید.
- **اگر چیزی را نتواند بخواند، خبر می‌دهد.** پستی که شبیه نرخ است اما با قالب شناخته‌شده جور نیست با وضعیت `failed` ثبت می‌شود، تا تغییر سبک نوشتن کانال دیده شود و داده بی‌صدا از دست نرود.
- **قابل بازسازی است.** چون پست‌های خام نگه داشته می‌شوند، همهٔ دادهٔ استخراج‌شده را می‌توان هر زمان پاک کرد و با قواعد بهتر دوباره ساخت.

<a id="s2"></a>

## چگونه کار می‌کند

<div dir="ltr">

```
                 Telegram channel
                        │
        ┌───────────────┼────────────────┐
        │               │                │
   1. backfill      2. live          3. catch-up
   (history on    (new + edited     (every 15 min,
     start)         posts pushed)    fills gaps)
        └───────────────┼────────────────┘
                        ▼
              raw_messages  (exact text, never changed)
              raw_message_edits  (later versions)
                        │
                     parser  (strict rules, text cleaned first)
                        ▼
              observations  (one row per price)
              parse_log     (parsed / ignored / failed per post)
                        │
                        ▼
        your analysis, dashboard, API or other project
```

</div>

۱. **backfill**: دریافت تاریخچه هنگام شروع. ۲. **live**: پست‌های جدید و ویرایش‌شده که تلگرام خودش می‌فرستد. ۳. **catch-up**: بررسی دوره‌ای برای پر کردن کمبودها.

در این طراحی **جمع‌آوری** از **خواندن نرخ** جدا است. جمع‌آوری فقط متن را ذخیره می‌کند و خواندن نرخ فقط متن ذخیره‌شده را می‌خواند. اگر بخش خواندن نرخ اشکالی داشته باشد چیزی از دست نمی‌رود: آن را اصلاح کنید و `nerkhbot parse --all` را اجرا کنید.

<a id="s3"></a>

## پیش‌نیازها

- پایتون 3.10 یا بالاتر (روی 3.13 و 3.14 ساخته و آزمایش شده است)
- یک حساب تلگرام و کلیدهای API برای آن (رایگان، [پایین‌تر](#s5) توضیح داده شده)
- حساب باید بتواند کانال را باز کند. برای دریافت زندهٔ پست‌ها بهتر است در کانال **عضو** هم باشد.

کتابخانه‌های اصلی: [Telethon](https://github.com/LonamiWebs/Telethon) (تلگرام)، [SQLAlchemy](https://www.sqlalchemy.org/) (پایگاه داده)، [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) (تنظیمات)، [APScheduler](https://apscheduler.readthedocs.io/) (کار دوره‌ای)، [loguru](https://github.com/Delgan/loguru) (ثبت رویدادها)، [tenacity](https://tenacity.readthedocs.io/) (تلاش دوباره).

<a id="s4"></a>

## نصب

**برای استفاده** (به‌عنوان ابزار یا درون پروژهٔ دیگر):

<div dir="ltr">

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install git+https://github.com/omrtyyb/herat-nerkhbot.git
```

</div>

**برای توسعه** (تغییر کد و اجرای آزمایش‌ها):

<div dir="ltr">

```bash
git clone https://github.com/omrtyyb/herat-nerkhbot.git
cd herat-nerkhbot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

</div>

در هر دو حالت دستور `nerkhbot` و بستهٔ پایتون `nerkhbot` در دسترس شما خواهد بود.

> نام پروژه `herat-nerkhbot` است؛ نام دستور و نام import همان `nerkhbot` کوتاه‌تر است.

<a id="s5"></a>

## گرفتن کلیدهای API تلگرام

این ابزار مانند یک کاربر عادی تلگرام وارد می‌شود (نه ربات)، چون ربات‌ها نمی‌توانند کانالی را که مدیر آن نیستند بخوانند.

1. صفحهٔ <https://my.telegram.org> را باز کنید و با شمارهٔ تلفن خود در قالب بین‌المللی (مثلاً `+93...`) وارد شوید.
2. تلگرام کد ورود را **داخل برنامهٔ تلگرام** می‌فرستد (یک پیام در چت، نه پیامک). آن را وارد کنید.
3. روی **API development tools** کلیک کنید.
4. در *App title* و *Short name* هر نامی بنویسید (مثلاً `nerkhbot`)، گزینهٔ *Desktop* را انتخاب کنید و برنامه را بسازید.
5. مقدار **App api_id** (یک عدد) و **App api_hash** (۳۲ حرف) را کپی کنید.

اگر هنگام ساختن برنامه فقط کلمهٔ "ERROR" نمایش داده شد، VPN و مسدودکنندهٔ تبلیغات را خاموش کنید یا مرورگر دیگری را امتحان کنید.

این دو مقدار فقط برنامهٔ شما را معرفی می‌کنند. ورود واقعی به حساب بعداً با دستور `nerkhbot login` انجام می‌شود.

<a id="s6"></a>

## تنظیمات

همهٔ تنظیمات از متغیرهای محیطی یا از فایلی به نام `.env` در همان پوشه‌ای که دستور را اجرا می‌کنید خوانده می‌شوند. متغیرهای محیطی واقعی بر `.env` اولویت دارند.

فایل `.env` را بسازید:

<div dir="ltr">

```ini
# Telegram API (from https://my.telegram.org)
TG_API_ID=123456
TG_API_HASH=0123456789abcdef0123456789abcdef

# Where the login session is stored (creates data/nerkhbot.session)
TG_SESSION=data/nerkhbot

# Channels to collect, comma-separated: @name, name, or https://t.me/name
TG_CHANNELS=@NerkhYab_Khorasan

# First run: how many days of history to fetch (0 = everything)
BACKFILL_DAYS=20
# How often, in minutes, to re-check for missed posts
CATCHUP_MINUTES=15

DATABASE_URL=sqlite:///data/nerkhbot.db
LOG_LEVEL=INFO
LOG_DIR=logs
```

</div>

| تنظیم | الزامی | پیش‌فرض | معنا |
|---|---|---|---|
| `TG_API_ID` | بله | | عددی که از my.telegram.org می‌گیرید |
| `TG_API_HASH` | بله | | رشتهٔ ۳۲ حرفی از my.telegram.org |
| `TG_SESSION` | نه | `data/nerkhbot` | مسیر فایل نشست ورود (پسوند `.session` افزوده می‌شود) |
| `TG_CHANNELS` | بله، برای جمع‌آوری | خالی | یک یا چند کانال، جداشده با کاما |
| `BACKFILL_DAYS` | نه | `20` | تعداد روزهای تاریخچه که هنگام خالی بودن پایگاه داده دریافت می‌شود. `0` یعنی همهٔ تاریخچه |
| `CATCHUP_MINUTES` | نه | `15` | فاصلهٔ بررسی احتیاطی دوره‌ای، به دقیقه |
| `DATABASE_URL` | نه | `sqlite:///data/nerkhbot.db` | نشانی پایگاه داده به شکل SQLAlchemy |
| `LOG_LEVEL` | نه | `INFO` | یکی از `DEBUG`، `INFO`، `WARNING`، `ERROR` |
| `LOG_DIR` | نه | `logs` | پوشهٔ فایل `nerkhbot.log` (در ۱۰ مگابایت فایل تازه ساخته می‌شود و فایل‌ها ۳۰ روز نگه داشته می‌شوند) |

نکته‌ها:

- مسیرهای نسبی (`data/...` و `logs`) نسبت به پوشه‌ای هستند که دستور را در آن اجرا می‌کنید. همیشه از همان پوشه اجرا کنید یا مسیر کامل بدهید.
- `BACKFILL_DAYS` فقط وقتی اثر دارد که پایگاه داده برای آن کانال هیچ پستی نداشته باشد. پس از آن، ابزار همیشه از تازه‌ترین پستی که دارد ادامه می‌دهد.

<a id="s7"></a>

## شروع سریع

<div dir="ltr">

```bash
# 1. one-time login (asks for phone number, the code from Telegram, and your 2-step password if set)
nerkhbot login

# 2. download history and parse it
nerkhbot backfill

# 3. look at the result
nerkhbot stats
nerkhbot rates
nerkhbot latest -n 3

# 4. keep collecting until you press Ctrl+C
nerkhbot run
```

</div>

۱. ورود یک‌باره (شمارهٔ تلفن، کد ارسالی تلگرام و در صورت فعال بودن، رمز تأیید دومرحله‌ای را می‌پرسد). ۲. دریافت تاریخچه و خواندن نرخ‌ها. ۳. دیدن نتیجه. ۴. ادامهٔ جمع‌آوری تا زمانی که Ctrl+C را بزنید.

نمونهٔ خروجی `nerkhbot rates`:

<div dir="ltr">

```
herat        1 EUR = 72.80 buy / 73.00 sell AFN   (2026-11-15 11:40 UTC)
herat    1,000 PKR = 233.50 buy / 234.00 sell AFN   (2026-11-15 11:40 UTC)
herat        1 USD = 65.70 buy / 65.75 sell AFN   (2026-11-15 11:40 UTC)
```

</div>

<a id="s8"></a>

## دستورها

برای دیدن فهرست، `nerkhbot --help` را اجرا کنید. اگر دستور در PATH شما نیست، `python -m nerkhbot ...` هم کار می‌کند.

| دستور | کاری که انجام می‌دهد |
|---|---|
| `nerkhbot login` | ورود تعاملی یک‌باره. فایل نشست را می‌سازد تا دستورهای بعدی دیگر چیزی نپرسند. |
| `nerkhbot backfill` | هر پستی را که موجود نیست دریافت می‌کند، پست‌های تازه را می‌خواند و سپس بسته می‌شود. برای cron مناسب است. |
| `nerkhbot run` | تاریخچه را کامل می‌کند، سپس منتظر پست‌های جدید و ویرایش‌شده می‌ماند و در هر `CATCHUP_MINUTES` دوباره بررسی می‌کند. تا متوقف نشود اجرا می‌ماند. |
| `nerkhbot parse` | پست‌های ذخیره‌شده‌ای را که هنوز خوانده نشده‌اند به نرخ تبدیل می‌کند. |
| `nerkhbot parse --all` | همهٔ ردیف‌های استخراج‌شده را پاک می‌کند و همهٔ پست‌ها را دوباره می‌خواند. پست‌های خام دست‌نخورده می‌مانند. پس از تغییر قواعد از آن استفاده کنید. |
| `nerkhbot rates` | تازه‌ترین نرخ لحظه‌ای هر بازار و هر ارز را نشان می‌دهد. |
| `nerkhbot stats` | تعداد پست‌های ذخیره‌شدهٔ هر کانال، زمان تازه‌ترین پست، و تعداد پست‌های parsed / ignored / failed را نشان می‌دهد. |
| `nerkhbot latest -n 5` | تازه‌ترین پست‌های ذخیره‌شده را به شکل متن خام چاپ می‌کند. |
| `nerkhbot failed` | پست‌هایی را فهرست می‌کند که شبیه نرخ بودند اما خوانده نشدند. |

متوقف کردن با **Ctrl+C** همیشه بی‌خطر است. هرچه ذخیره شده باقی می‌ماند و اجرای بعدی از همان‌جا ادامه می‌دهد.

<a id="s9"></a>

## پایگاه داده

به‌طور پیش‌فرض SQLite (یک فایل: `data/nerkhbot.db`). همهٔ زمان‌ها به **UTC** ذخیره می‌شوند.

جدول‌ها دو دسته‌اند. **جدول‌های خام** را بخش جمع‌آوری می‌نویسد و هرگز تغییر نمی‌کنند. **جدول‌های استخراج‌شده** را بخش خواندن نرخ از روی جدول‌های خام می‌سازد و می‌توان آن‌ها را پاک کرد و دوباره ساخت.

### `sources` (خام)

برای هر کانال یک ردیف.

| ستون | معنا |
|---|---|
| `id` | شناسهٔ داخلی |
| `kind` | `telegram` |
| `external_id` | شناسهٔ عددی کانال در تلگرام. حتی اگر نام کاربری کانال عوض شود ثابت می‌ماند |
| `name` | نام کاربری فعلی |
| `title` | عنوان نمایشی |
| `created_at` | زمان ساخته شدن ردیف |

ترکیب (`kind`، `external_id`) یکتا است.

### `raw_messages` (خام)

برای هر پست یک ردیف، دقیقاً همان‌طور که بار اول دیده شده.

| ستون | معنا |
|---|---|
| `id` | شناسهٔ داخلی |
| `source_id` | کانال (`sources.id`) |
| `message_id` | شمارهٔ پیام در کانال تلگرام |
| `text` | متن دقیق. برای پست‌هایی که فقط عکس دارند خالی است |
| `posted_at` | زمانی که کانال آن را منتشر کرده |
| `fetched_at` | زمانی که این ابزار آن را ذخیره کرده |
| `views` | تعداد بازدید در لحظهٔ ذخیره |
| `has_media` | آیا پست عکس یا فایل داشته است |

ترکیب (`source_id`، `message_id`) یکتا است. همین قاعده از تکرار جلوگیری می‌کند.

### `raw_message_edits` (خام)

برای هر نسخهٔ بعدی یک پست یک ردیف؛ وقتی کانال پستی را ویرایش می‌کند نوشته می‌شود. ستون‌ها: `source_id`، `message_id`، `text`، `edited_at`، `fetched_at`. نسخهٔ تازه فقط وقتی ذخیره می‌شود که متن واقعاً عوض شده باشد (تلگرام تغییر تعداد بازدید را هم «ویرایش» گزارش می‌کند).

### `observations` (استخراج‌شده)

برای هر نرخ یک ردیف.

| ستون | نمونه | معنا |
|---|---|---|
| `id` | | شناسهٔ داخلی |
| `raw_message_id` | | پستی که نرخ از آن خوانده شده (`raw_messages.id`) |
| `source_id` | | کانال |
| `observed_at` | `2026-11-15 11:40:04` | زمان پست (UTC) |
| `market` | `herat` | شهر |
| `currency` | `USD` | ارزی که قیمت‌گذاری شده: `USD`، `EUR`، `PKR` |
| `quote_currency` | `AFN` | ارزی که قیمت با آن پرداخت می‌شود |
| `unit` | `1`، `1000` | قیمت برای این تعداد واحد است. کلدار برای هر ۱٬۰۰۰ روپیه نرخ‌گذاری می‌شود |
| `buy` | `65.70` | نرخ خرید |
| `sell` | `65.75` | نرخ فروش |
| `kind` | `quote`، `close` | نرخ لحظه‌ای، یا نرخ پایان روز |
| `status` | `ok`، `suspect` | آیا ردیف از بررسی‌های درستی گذشته است |
| `issues` | `jump` | دلیل مشکوک بودن، جداشده با کاما. اگر `ok` باشد خالی است |
| `parser_version` | `1` | نسخهٔ قواعدی که این ردیف را ساخته |
| `created_at` | | زمان نوشته شدن ردیف |

ترکیب (`raw_message_id`، `market`، `currency`) یکتا است.

هر ردیف را این‌طور بخوانید: *در بازار `market`، تعداد `unit` واحد از `currency` به نرخ `buy`/`sell` به `quote_currency` معامله می‌شود*. برای نمونه: `herat, 1000 PKR = 233.50 / 234.00 AFN`.

### `parse_log` (استخراج‌شده)

برای هر پست یک ردیف که تصمیم بخش خواندن نرخ را ثبت می‌کند.

| ستون | معنا |
|---|---|
| `raw_message_id` | پست |
| `status` | `parsed` (نرخ پیدا شد)، `ignored` (پست نرخ نیست)، `failed` (شبیه نرخ بود اما خوانده نشد) |
| `reason` | توضیح برای `failed` |
| `parser_version` | نسخهٔ قواعد |
| `parsed_at` | زمان پردازش |

### نمونهٔ پرس‌وجوها

نرخ پایان روز دالر:

<div dir="ltr">

```sql
SELECT date(observed_at) AS day, buy, sell
FROM observations
WHERE currency = 'USD' AND kind = 'close' AND status = 'ok'
ORDER BY day;
```

</div>

فقط لحظه‌هایی که نرخ دالر تغییر کرده است:

<div dir="ltr">

```sql
SELECT observed_at, buy, sell
FROM (
  SELECT observed_at, buy, sell,
         LAG(buy)  OVER (ORDER BY observed_at, id) AS prev_buy,
         LAG(sell) OVER (ORDER BY observed_at, id) AS prev_sell
  FROM observations
  WHERE currency = 'USD' AND kind = 'quote' AND status = 'ok'
)
WHERE prev_buy IS NULL OR buy <> prev_buy OR sell <> prev_sell;
```

</div>

کمترین، بیشترین و میانگین نرخ میانهٔ هر ارز در هر روز:

<div dir="ltr">

```sql
SELECT date(observed_at) AS day, currency,
       MIN(buy) AS low, MAX(sell) AS high,
       ROUND(AVG((buy + sell) / 2), 4) AS avg_mid,
       COUNT(*) AS quotes
FROM observations
WHERE kind = 'quote' AND status = 'ok'
GROUP BY day, currency
ORDER BY day, currency;
```

</div>

<a id="s10"></a>

## خواندن نرخ‌ها چگونه انجام می‌شود

### کانال چه چیزهایی منتشر می‌کند

بیشتر پست‌ها نرخ‌های یک‌خطی هستند:

<div dir="ltr">

```
هرات دالر به افغانی💵 65.70 خـرید 65.75 فـروش
هرات یورو به افغانی 💶 72.80خرید 73.00 فروش
هرات کلدار افغانی 🇵🇰 233,50 خرید 234,00 فروش
```

</div>

در پایان هر روز معاملاتی یک جمع‌بندی منتشر می‌شود:

<div dir="ltr">

```
📌پایان معاملات📌

🗓️  شنبه | 1405.08.16

💵 دالر به افغانی
65.15 خرید | 65.20 فروش
...
```

</div>

بقیهٔ پست‌ها تبلیغ، سلام و احوال‌پرسی و اطلاعیه هستند و در برخی از آن‌ها عدد و نام ارز هم دیده می‌شود.

### قواعد

1. **اول متن پاک‌سازی می‌شود.** رقم‌های فارسی و عربی به رقم لاتین تبدیل می‌شوند، حرف‌های عربی `ي` و `ك` به `ی` و `ک` فارسی، کشیدهٔ داخل `خـرید` حذف می‌شود، نویسه‌های نادیدنی حذف می‌شوند، و جداکنندهٔ اعشار و هزارگان فارسی تبدیل می‌شود.
2. **نرخ فقط در همین شکل دقیق خوانده می‌شود:** `عدد خرید عدد فروش` (اول خرید، بعد فروش)، که می‌تواند `|` میانشان باشد. خرید و فروش از روی برچسب خودشان شناخته می‌شوند، نه فقط از روی جایگاه.
3. **برچسب، ارز را مشخص می‌کند.** برچسب متنِ پیش از نرخ‌ها در همان خط است، یا خط بالایی (مانند جمع‌بندی‌ها). املاهای شناخته‌شده: `دالر` / `دلار` / `usd` / `dollar`، `یورو` / `eur` / `euro`، `کلدار` / `روپیه پاکستان` / `pkr`.
4. **برچسب باید بگوید قیمت با چه ارزی پرداخت می‌شود** (`افغانی` یعنی AFN). اگر ارز مورد نظر با ارز ناشناخته‌ای قیمت‌گذاری شده باشد، با وضعیت `failed` ثبت می‌شود و حدس زده نمی‌شود.
5. **ارزهایی که دنبال نمی‌شوند کنار گذاشته می‌شوند.** خط‌های تومان عمداً نادیده گرفته می‌شوند.
6. **عددها.** `65.70` و `233,50` هر دو اعشاری‌اند. `1,250` یعنی یک هزار و دوصد و پنجاه. `1,250.5` هم درست خوانده می‌شود.
7. **بازار.** از برچسب گرفته می‌شود (`هرات` یعنی `herat`؛ کابل، مزار و قندهار هم شناخته می‌شوند). جمع‌بندی پایان روز نام شهر ندارد، پس به‌طور پیش‌فرض `herat` در نظر گرفته می‌شود.
8. **نوع.** پستی که عبارت `پایان معاملات` را دارد ردیف‌های `close` می‌سازد؛ بقیه ردیف‌های `quote` می‌سازند.

به‌خاطر قاعدهٔ ۲، تبلیغی مانند «دلار هرات به کانال ۲۶۵» هرگز به نرخ تبدیل نمی‌شود.

### علامت‌های بررسی درستی

یک ردیف با `status = suspect` و دلیل آن در `issues` ذخیره می‌شود وقتی که:

| مشکل | معنا |
|---|---|
| `non_positive` | خرید یا فروش صفر یا منفی است |
| `buy_above_sell` | خرید بالاتر از فروش است |
| `wide_spread` | فروش بیش از ۵٪ بالاتر از خرید است |
| `jump` | نرخ میانه بیش از ۱۰٪ با آخرین نرخ قابل اعتماد فاصله دارد. اگر همان نرخ تازه ۳ بار پشت سر هم تکرار شود، به‌عنوان حرکت واقعی بازار پذیرفته می‌شود |

ردیف‌های مشکوک نگه داشته می‌شوند و هرگز پاک نمی‌شوند. با `status = 'ok'` آن‌ها را کنار بگذارید.

### تغییر قواعد

قواعد در فایل `src/nerkhbot/parser.py` هستند: فهرست املاها (`CURRENCY_ALIASES`)، واحدها (`UNITS`)، بازارها (`MARKETS`) و آستانه‌ها. پس از تغییر، مقدار `PARSER_VERSION` را یک واحد بالا ببرید و این دستور را اجرا کنید:

<div dir="ltr">

```bash
nerkhbot parse --all
```

</div>

<a id="s11"></a>

## استفاده در پروژهٔ خودتان

سه راه وجود دارد، از ساده‌ترین تا وابسته‌ترین.

### ۱. خواندن پایگاه داده (با هر زبانی)

بگذارید `nerkhbot run` پایگاه داده را پر کند و برنامهٔ شما فقط از آن بخواند. با pandas:

<div dir="ltr">

```python
import pandas as pd

df = pd.read_sql(
    "SELECT observed_at, currency, buy, sell FROM observations "
    "WHERE kind = 'quote' AND status = 'ok' ORDER BY observed_at",
    "sqlite:///data/nerkhbot.db",
    parse_dates=["observed_at"],
)
usd = df[df.currency == "USD"].set_index("observed_at")
print(usd.resample("1D")[["buy", "sell"]].last())
```

</div>

### ۲. استفاده از بستهٔ پایتون

خواندن نرخ از یک متن (بدون نیاز به پایگاه داده یا تلگرام):

<div dir="ltr">

```python
from nerkhbot.parser import parse_post

result = parse_post("هرات دالر به افغانی💵 65.70 خـرید 65.75 فـروش")
print(result.status)                 # "parsed"
for q in result.quotes:
    print(q.market, q.currency, q.buy, q.sell, q.quote_currency, q.unit, q.kind)
# herat USD 65.70 65.75 AFN 1 quote
```

</div>

خواندن تازه‌ترین نرخ‌ها از پایگاه داده:

<div dir="ltr">

```python
from nerkhbot import storage
from nerkhbot.db import make_engine, make_session_factory

Session = make_session_factory(make_engine("sqlite:///data/nerkhbot.db"))
with Session() as session:
    for rate in storage.latest_rates(session):
        print(rate.market, rate.currency, rate.buy, rate.sell, rate.observed_at)
```

</div>

اجرای بخش جمع‌آوری از درون کد خودتان، با دادن مستقیم تنظیمات به‌جای `.env`:

<div dir="ltr">

```python
import asyncio

from nerkhbot.collectors.telegram import TelegramCollector
from nerkhbot.config import Settings
from nerkhbot.db import init_db, make_engine, make_session_factory
from nerkhbot.logging_setup import setup_logging

settings = Settings(
    tg_api_id=123456,
    tg_api_hash="0123456789abcdef0123456789abcdef",
    tg_channels="@NerkhYab_Khorasan",
)
setup_logging(settings.log_level, settings.log_dir)
engine = make_engine(settings.database_url)
init_db(engine)                      # creates missing tables
Session = make_session_factory(engine)


async def main():
    collector = TelegramCollector(settings, Session)
    await collector.run_backfill_once()   # or: await collector.run_forever()


asyncio.run(main())
```

</div>

فایل نشست باید از پیش وجود داشته باشد (یک بار `nerkhbot login` را با همان `TG_SESSION` اجرا کنید).

### ۳. صدا زدن دستورها

از یک اسکریپت شل، cron یا برنامهٔ دیگر: `nerkhbot backfill`، `nerkhbot parse`، `nerkhbot rates`.

<a id="s12"></a>

## اجرا روی سرور

`nerkhbot run` یک برنامهٔ همیشه‌درحال‌اجرا است. روی سرور لینوکس، یک سرویس systemd آن را زنده نگه می‌دارد و پس از خطا یا راه‌اندازی دوبارهٔ سرور دوباره اجرایش می‌کند. آنچه در پایین آمده یک نمونه برای تطبیق دادن است، نه یک دستورالعمل آزمایش‌شدهٔ استقرار:

<div dir="ltr">

```ini
# /etc/systemd/system/nerkhbot.service
[Unit]
Description=herat-nerkhbot collector
After=network-online.target
Wants=network-online.target

[Service]
User=nerkhbot
WorkingDirectory=/opt/herat-nerkhbot
ExecStart=/opt/herat-nerkhbot/.venv/bin/nerkhbot run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

</div>

<div dir="ltr">

```bash
sudo systemctl enable --now nerkhbot
journalctl -u nerkhbot -f
```

</div>

مراحل روی سرور تازه: نصب کنید، فایل `.env` را در پوشهٔ کاری بسازید، یک بار `nerkhbot login` را همان‌جا اجرا کنید (تعاملی است)، سپس سرویس را راه بیندازید.

راه دیگر، بدون برنامهٔ همیشه‌درحال‌اجرا: `nerkhbot backfill` را با cron در هر چند دقیقه اجرا کنید. در این حالت دریافت زنده و ثبت ویرایش‌ها را از دست می‌دهید، اما زمان‌ها دقیق می‌مانند چون از خود تلگرام می‌آیند.

از فایل `data/nerkhbot.db` به‌طور منظم نسخهٔ پشتیبان بگیرید. فقط یک فایل است.

<a id="s13"></a>

## ساختار پروژه

<div dir="ltr">

```
herat-nerkhbot/
├── pyproject.toml              project definition and dependencies
├── .env.example                template for your settings
├── README.md / README.fa.md    documentation
├── LICENSE
├── src/nerkhbot/
│   ├── config.py               settings from .env / environment
│   ├── logging_setup.py        console + rotating file log
│   ├── db.py                   table definitions, engine, sessions
│   ├── storage.py              every database read and write
│   ├── parser.py               text -> prices (pure, no I/O)
│   ├── pipeline.py             runs the parser over stored posts
│   ├── collectors/
│   │   └── telegram.py         backfill, live updates, catch-up
│   ├── cli.py                  the `nerkhbot` command
│   └── __main__.py             enables `python -m nerkhbot`
└── tests/                      pytest suite
```

</div>

| فایل | نقش |
|---|---|
| `config.py` | خواندن تنظیمات از `.env` و متغیرهای محیطی |
| `logging_setup.py` | ثبت رویدادها در صفحه و در فایل |
| `db.py` | تعریف جدول‌ها و اتصال به پایگاه داده |
| `storage.py` | همهٔ خواندن‌ها و نوشتن‌های پایگاه داده |
| `parser.py` | تبدیل متن به نرخ (بدون هیچ ورودی و خروجی دیگر) |
| `pipeline.py` | اجرای بخش خواندن نرخ روی پست‌های ذخیره‌شده |
| `collectors/telegram.py` | دریافت تاریخچه، پست‌های زنده و بررسی دوره‌ای |
| `cli.py` | دستور `nerkhbot` |

هنگام اجرا ساخته می‌شوند و git آن‌ها را نادیده می‌گیرد: `.env`، پوشهٔ `data/` (پایگاه داده و فایل نشست) و پوشهٔ `logs/`.

<a id="s14"></a>

## توسعه و آزمایش‌ها

<div dir="ltr">

```bash
pip install -e ".[dev]"
pytest -q
```

</div>

آزمایش‌ها به حساب تلگرام و اینترنت نیاز ندارند. از پایگاه دادهٔ درون‌حافظه‌ای، یک کلاینت ساختگی تلگرام و پست‌های واقعیِ کپی‌شده از کانال استفاده می‌کنند. این موارد را پوشش می‌دهند: جلوگیری از تکرار، تاریخچهٔ ویرایش‌ها، ادامهٔ دریافت تاریخچه، تلاش دوباره هنگام خطای شبکه، تک‌تک قواعد خواندن نرخ، علامت‌های بررسی درستی، و خواندن دوباره.

<a id="s15"></a>

## امنیت و حریم خصوصی

- **فایل نشست همان ورود شما به تلگرام است.** هر کسی که `data/nerkhbot.session` را کپی کند می‌تواند بدون کد، چت‌های شما را بخواند و به نام شما کار کند. آن را خصوصی نگه دارید، هرگز commit نکنید و با کسی شریک نسازید.
- **هرگز `.env` را commit نکنید.** مقدار API hash شما در آن است. فایل `.gitignore` این پروژه `.env`، `*.session`، `data/` و `logs/` را کنار می‌گذارد.
- **پوشهٔ پروژه را از راه وب‌سایت GitHub بارگذاری نکنید.** آن روش `.gitignore` را نادیده می‌گیرد. از `git` در خط فرمان استفاده کنید.
- **بهتر است یک حساب تلگرام جداگانه** برای جمع‌آوری داشته باشید، تا نشت فایل نشست یا محدود شدن حساب به حساب شخصی شما آسیبی نرساند. در هر حال تأیید دومرحله‌ای را فعال کنید.
- **هر زمان می‌توانید دسترسی را قطع کنید:** در تلگرام، Settings ← Devices، نشست را ببندید.
- **این ابزار فقط می‌خواند.** هیچ‌گاه پست نمی‌گذارد، نظر نمی‌دهد، به کسی پیام نمی‌فرستد و اطلاعات اعضای کانال را جمع نمی‌کند.

<a id="s16"></a>

## استفادهٔ مسئولانه

- این ابزار محتوایی را می‌خواند که دیگران منتشر کرده‌اند. کاربرد در نظر گرفته‌شده، جمع‌آوری پست‌های عمومی برای تحلیل شخصی است.
- بازنشر یا فروش دادهٔ جمع‌آوری‌شده ممکن است به اجازهٔ صاحب کانال نیاز داشته باشد و در کشور شما از نظر قانونی محدود باشد. مسئولیت آن با خود شماست.
- تلگرام می‌تواند حساب‌هایی را که رفتار نادرست دارند محدود کند. این ابزار درخواست‌های کم و کوچک می‌فرستد و هر وقت تلگرام بخواهد صبر می‌کند، اما استفاده از حساب با مسئولیت خود شماست و باید شرایط استفادهٔ تلگرام را رعایت کنید.
- دادهٔ جمع‌آوری‌شده در این مخزن قرار ندارد.

<a id="s17"></a>

## محدودیت‌ها

- **بخش خواندن نرخ مخصوص قالب همین کانال است.** جمع‌آوری برای هر کانالی کار می‌کند، اما نرخ‌های کانالی که آن‌ها را به شکل دیگری می‌نویسد `ignored` یا `failed` می‌شوند تا زمانی که قاعده‌ای برایش افزوده شود.
- **فقط USD، EUR و PKR در برابر AFN دنبال می‌شوند.**
- **فرض شده است که کلدار برای هر ۱٬۰۰۰ روپیه نرخ‌گذاری می‌شود.** اگر برای کانال شما چنین نیست، `UNITS` را در `parser.py` تغییر دهید.
- **پست‌های ویرایش‌شده ذخیره می‌شوند اما دوباره خوانده نمی‌شوند.** ردیف نرخ، نسخهٔ اول پست را نشان می‌دهد.
- **ویرایش‌هایی که در زمان خاموش بودن ابزار انجام شده‌اند بازیابی نمی‌شوند.** پست‌های تازهٔ ازدست‌رفته بازیابی می‌شوند.
- **یک حساب تلگرام.** اگر حساب خارج شود یا محدود گردد، جمع‌آوری تا ورود دوباره متوقف می‌ماند.
- **`BACKFILL_DAYS` فقط برای پایگاه دادهٔ خالی اثر دارد.** هنوز دستوری برای دریافت تاریخچهٔ قدیمی‌تر در آینده وجود ندارد.
- **مهاجرت ساختار پایگاه داده وجود ندارد.** جدول‌های تازه خودکار ساخته می‌شوند، اما تغییر یک ستون موجود کار دستی می‌خواهد.
- **PostgreSQL در نظر گرفته شده اما هنوز آزمایش نشده است.** کد از امکانات مخصوص SQLite دوری می‌کند و انتظار می‌رود با نشانی و درایور PostgreSQL کار کند.
- **هنوز API وب، داشبورد یا هشدار ندارد.**

<a id="s18"></a>

## رفع اشکال

| مشکل | علت و راه‌حل |
|---|---|
| `ModuleNotFoundError: No module named 'nerkhbot'` | محیط مجازی فعال نیست (`source .venv/bin/activate`) یا بسته در آن نصب نشده است (`pip install -e ".[dev]"`). |
| `command not found: nerkhbot` | مانند بالا. `python -m nerkhbot ...` هم کار می‌کند. |
| `Bad or missing settings in .env: TG_API_ID, TG_API_HASH` | فایل `.env` در پوشهٔ فعلی نیست یا مقدارها خالی‌اند. دستور را از پوشه‌ای اجرا کنید که `.env` در آن است. |
| `No channels configured. Set TG_CHANNELS in .env` | مقدار `TG_CHANNELS` خالی است. |
| `Not logged in to Telegram. Run nerkhbot login first.` | فایل نشست معتبری در مسیر `TG_SESSION` نیست. `nerkhbot login` را اجرا کنید. |
| `Could not reach Telegram` | اینترنت قطع است یا تلگرام در شبکهٔ شما مسدود است. |
| سایت my.telegram.org فقط "ERROR" نشان می‌دهد | VPN و مسدودکنندهٔ تبلیغات را خاموش کنید یا مرورگر دیگری را امتحان کنید. |
| `BACKFILL_DAYS` را تغییر داده‌اید اما پست قدیمی‌تری نمی‌آید | این تنظیم فقط برای پایگاه دادهٔ خالی اثر دارد. `data/nerkhbot.db` را پاک کنید و دوباره `nerkhbot backfill` را اجرا کنید. |
| `nerkhbot failed` پست‌هایی را نشان می‌دهد | کانال از قالبی استفاده کرده که بخش خواندن نرخ نمی‌شناسد. قاعده‌ای در `parser.py` بیفزایید و سپس `nerkhbot parse --all` را اجرا کنید. |
| دریافت تاریخچه مدتی چیزی چاپ نمی‌کند | در کانال کم‌پست عادی است. پس از هر ۱۰۰ پست یک خط پیشرفت چاپ می‌شود. |

<a id="s19"></a>

## مجوز

MIT. فایل [LICENSE](LICENSE) را ببینید.

</div>

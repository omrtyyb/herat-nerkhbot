"""Parser rules, tested with real posts copied from @NerkhYab_Khorasan."""

from decimal import Decimal as D

import pytest

from nerkhbot.parser import normalize, parse_post, to_decimal

USD_LINE = "هرات دالر به افغانی💵 65.70 خـرید 65.75 فـروش"
EUR_LINE = "هرات یورو به افغانی 💶 72.80خرید 73.00 فروش"
PKR_LINE = "هرات کلدار افغانی 🇵🇰 233,50 خرید 234,00 فروش"
TOMAN_BANK = "هرات تومان بانکی 💳 0.250 خرید  0.260 فروش"
TOMAN_CHEQUE = "هرات تومان چک 💎 0.270 خرید  0.280 فروش"

SUMMARY = (
    "📌پایان معاملات📌\n\n🗓️\xa0\xa0شنبه | 1405.08.16\n\n"
    "💵 دالر به افغانی\n65.15 خرید | 65.20 فروش\n\n"
    "💸 یورو به افغانی\n72.50 خرید | 72.70 فروش\n\n"
    "🇵🇰 کلدار به افغانی\n232,00 خرید | 232,50 فروش\n\n"
    "💳 تومان بانکی به افغانی\n0.240 خرید | 0.250 فروش\n\n"
    "💵 تومان چک به افغانی\n0.270 خرید | 0.280 فروش\n@NerkhYab_Khorasan"
)

NOISE = [
    "دلار هرات 👆",
    "【وقفه برای نماز و نهار 】",
    "",
    "صعود دوباره دلار هرات به کانال ۲۶۵\n\nاین صعود تا کجا ادامه خواهد داشت؟\nکجا باید بخریم؟",
    "🔹ماه پیش دلار 256 هزار تومنی رو پیشبینی کردیم و کسی باور نکرد!\n🔹افزایش مجدد تا 274 هزار را اطلاع دادیم",
    "✅ ۵,۰۰۰ دالر جایزه نقدی ایکس‌چیف برای تریدرهای افغان!\n🥇 نفر اول: ۱,۰۰۰ دالر\n🟡 شروع با حداقل ۱۰۰ دالر واریزی",
    "سلام و درود\nصبح روز اول هفته تان بخیر🌷\n🗓     امروز  شنبه | 1405.08.16",
]


def only(result):
    assert result.status == "parsed"
    [quote] = result.quotes
    return quote


def test_usd_line():
    q = only(parse_post(USD_LINE))
    assert (q.currency, q.quote_currency, q.market, q.unit, q.kind) == ("USD", "AFN", "herat", 1, "quote")
    assert (q.buy, q.sell) == (D("65.70"), D("65.75"))
    assert q.issues == ()


def test_eur_line_without_space_before_buy_word():
    q = only(parse_post(EUR_LINE))
    assert (q.currency, q.buy, q.sell) == ("EUR", D("72.80"), D("73.00"))


def test_pkr_line_uses_decimal_comma_and_unit_1000():
    q = only(parse_post(PKR_LINE))
    assert (q.currency, q.unit, q.buy, q.sell) == ("PKR", 1000, D("233.50"), D("234.00"))


@pytest.mark.parametrize("text", [TOMAN_BANK, TOMAN_CHEQUE])
def test_toman_lines_are_ignored(text):
    assert parse_post(text).status == "ignored"


@pytest.mark.parametrize("text", NOISE)
def test_noise_is_ignored_even_with_currency_words_and_numbers(text):
    result = parse_post(text)
    assert result.status == "ignored"
    assert result.quotes == []


def test_end_of_day_summary_gives_three_close_quotes():
    result = parse_post(SUMMARY)
    assert result.status == "parsed"
    got = {q.currency: (q.buy, q.sell, q.kind, q.market) for q in result.quotes}
    assert got == {
        "USD": (D("65.15"), D("65.20"), "close", "herat"),
        "EUR": (D("72.50"), D("72.70"), "close", "herat"),
        "PKR": (D("232.00"), D("232.50"), "close", "herat"),
    }


def test_persian_digits_arabic_letters_and_other_spellings():
    # Persian digits + decimal mark, Arabic kaf/yeh, the "دلار" spelling.
    q = only(parse_post("هرات دلار به افغانی ۶۵٫۷۰ خريد ۶۵٫۷۵ فروش"))
    assert (q.currency, q.buy, q.sell) == ("USD", D("65.70"), D("65.75"))
    q = only(parse_post("هرات كلدار افغانی 233,50 خرید 234,00 فروش"))
    assert q.currency == "PKR"


def test_normalize():
    assert normalize("خـرید ۱۲۳ ٤٥ ي ك") == "خرید 123 45 ی ک"


@pytest.mark.parametrize(
    "text, expected",
    [("65.70", "65.70"), ("233,50", "233.50"), ("1,250", "1250"), ("1,250.5", "1250.5"), ("0.250", "0.250")],
)
def test_to_decimal(text, expected):
    assert to_decimal(text) == D(expected)


def test_buy_above_sell_is_flagged():
    q = only(parse_post("هرات دالر به افغانی 65.75 خرید 65.70 فروش"))
    assert q.issues == ("buy_above_sell",)


def test_wide_spread_is_flagged():
    q = only(parse_post("هرات دالر به افغانی 65.70 خرید 75.70 فروش"))
    assert q.issues == ("wide_spread",)


def test_quote_shaped_post_that_does_not_match_is_failed_not_dropped():
    # buy/sell words in the opposite order: a format we do not know.
    result = parse_post("هرات دالر به افغانی فروش 65.75 خرید 65.70")
    assert result.status == "failed"


def test_tracked_currency_priced_in_something_else_is_failed():
    result = parse_post("هرات دالر به تومان 112000 خرید 112500 فروش")
    assert result.status == "failed"
    assert "quote currency" in result.reason


def test_other_city_is_recognised():
    q = only(parse_post("کابل دالر به افغانی 65.60 خرید 65.70 فروش"))
    assert q.market == "kabul"

"""
eBag (ebag.bg) product extractor.

Основен път: HTML (BS4) — след редизайна от август 2026 всеки продукт е
<article> с име в <h3> и цени САМО в EUR (лв. вече не се показва).
Fallback: markdown (стари формати — image links + title pattern).
"""

import re

from config import logger, BS4_AVAILABLE
if BS4_AVAILABLE:
    from config import BeautifulSoup

from utils import (
    extract_eur_price,
    extract_bgn_price,
    validate_eur_bgn,
    deduplicate_check,
    is_harmonica_product,
)


def _multipack_is_priced(article, eur, unit_eur):
    """
    Показаната цена за мултипак ли е, вместо за единичната разфасовка?

    Част от продуктите имат превключвател за разфасовка:

        <div role="switch">
          <span style="transform: translate(calc(100% + 2px));"></span>  ← плъзгачът
          <button>400 г</button><button>4x400 г</button>
        </div>

    eBag остойностява САМО избрания вариант — цената на другия се дърпа при клик
    и изобщо я няма в HTML-а. По подразбиране избран е мултипакът, затова
    „Био Краве Кисело Мляко 3,6%" излиза с 4,68 € (4×400 г) срещу референтните
    400 г.

    Разпознаваме случая аритметично: при избран мултипак „N x M" единичната цена
    („… € за бр.") умножена по N дава показаната цена — 4,68 € = 4 × 1,17 €.
    Проверката не зависи от Tailwind класове и от позицията на плъзгача, а те са
    единствените други сигнали в DOM-а (`aria-checked` е "false" и при избран
    мултипак, т.е. е безполезен).

    Ако eBag някога подразбира единичната разфасовка, равенството няма да важи и
    цената се приема нормално.
    """
    if not unit_eur:
        return False

    for button in article.find_all("button"):
        label = re.sub(r"\s+", " ", button.get_text(strip=True))  # \s хваща и nbsp
        match = re.fullmatch(
            r"(\d+)\s*[x×]\s*\d+(?:[.,]\d+)?\s*(?:г|гр|мл|кг|л|бр\.?)", label)
        if not match:
            continue
        multiplier = int(match.group(1))
        # допуск за закръгляне на единичната цена (±0.01 на бройка)
        if multiplier > 1 and abs(eur - multiplier * unit_eur) <= 0.01 * multiplier:
            return True

    return False


def extract_ebag_from_html(html):
    """
    Извлича продукти от eBag HTML — по една <article> карта на продукт.

    Структура (проверена на живо 11.08.2026):
        <article>
          <h3><span class="sr-only">Български продукт</span><img/>ИМЕТО</h3>
          <span ...>1,49 €</span>                 ← текуща цена
          <span ... line-through>2,04 €</span>    ← стара цена (пропуска се)
          <span ...>0,77 € за бр.</span>          ← единична цена (пропуска се)

    Името е в директните текстови възли на <h3> — вложените <span class="sr-only">
    ("Български продукт") и <img> (знаме) се игнорират.
    Цените са само в EUR, затова bgn остава None.
    """
    if not BS4_AVAILABLE or not html:
        return []

    products = []
    seen = set()
    soup = BeautifulSoup(html, "html.parser")

    for article in soup.find_all("article"):
        h3 = article.find("h3")
        if not h3:
            continue

        # Само директните текстови възли — без sr-only етикета и знамето
        name = " ".join(
            t.strip() for t in h3.find_all(string=True, recursive=False) if t.strip()
        )
        name = re.sub(r"\s+", " ", name).strip()

        if len(name) < 5 or not is_harmonica_product(name):
            continue
        if deduplicate_check(name, seen):
            continue

        eur = None
        unit_eur = None
        for tag in article.find_all(["span", "div", "p"]):
            if tag.find(True):                  # само листови елементи
                continue
            # eBag ползва nbsp между числото и валутата ("1,49\xa0€"), а
            # extract_eur_price приема само [ \t] — нормализираме интервалите.
            text = re.sub(r"[\s\u00a0\u202f]+", " ", tag.get_text(strip=True))
            if "€" not in text:
                continue
            classes = " ".join(tag.get("class") or [])
            if "line-through" in classes:       # зачеркната стара цена
                continue
            if re.search(r"за\s", text):        # единична цена: "0,77 € за бр."
                if unit_eur is None:
                    unit_eur = extract_eur_price(text)
                continue
            if eur is None:                     # първата незачеркната цена
                eur = extract_eur_price(text)

        if not eur:
            continue

        if _multipack_is_priced(article, eur, unit_eur):
            logger.info(
                f"eBag: пропускам цената на „{name}“ — показаните {eur}€ са за "
                f"мултипак, а единичната разфасовка не е остойностена в HTML-а"
            )
            # Продуктът остава в списъка без цена. Ако го махнехме напълно,
            # референтният запис би се закачил за друг продукт (киселото мляко
            # хващаше прясното) и грешното отклонение само сменя мястото си.
            eur = None

        products.append({"name": name, "eur": eur, "bgn": None})

    return products


def extract_ebag_products(markdown, html_text=None):
    """Извлича продукти от eBag. HTML е основният път, markdown — fallback."""
    if html_text:
        html_products = extract_ebag_from_html(html_text)
        if html_products:
            return html_products
        logger.info("eBag: HTML парсването върна 0 продукта — fallback към markdown")

    products = []
    seen = set()

    img_pattern = r'\[!\[([^\]]+)\]\([^\)]+\)\]\([^\)]+\)'

    for match in re.finditer(img_pattern, markdown):
        name = match.group(1).strip()

        if len(name) < 5 or 'flag' in name.lower():
            continue
        if not is_harmonica_product(name):
            continue
        if deduplicate_check(name, seen):
            continue

        idx = match.start()
        context = markdown[max(0, idx-50):idx+500]

        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)
        eur, bgn = validate_eur_bgn(eur, bgn)

        if eur or bgn:
            products.append({"name": name, "eur": eur, "bgn": bgn})

    title_pattern = r'###\s*\[\s*([^\]]+?)\s+Годно до:[^\]]*?(\d+[,\.]\d{2})\s*€[^\]]*?(\d+[,\.]\d{2})\s*лв'

    for match in re.finditer(title_pattern, markdown):
        name = match.group(1).strip()

        if len(name) < 5 or not is_harmonica_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        try:
            eur = float(match.group(2).replace(",", "."))
            bgn = float(match.group(3).replace(",", "."))

            if 0.20 <= eur <= 100 and 0.50 <= bgn <= 200:
                seen.add(name_key)
                products.append({"name": name, "eur": round(eur, 2), "bgn": round(bgn, 2)})
        except ValueError:
            pass

    return products

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
steam_gem_arbitrage.py
=======================

Инструмент для поиска выгодных карточных сетов, которые можно скрафтить
из самоцветов (gems) на Steam Community Market, а затем продать карточки
по отдельности.

ВАЖНО: крафтить бустер-паки (и, соответственно, наборы карточек) можно
ТОЛЬКО для игр, которые есть в вашей библиотеке Steam. Поэтому скрипт
не сканирует весь рынок, а сначала получает список игр из вашей
библиотеки, и считает экономику только по ним.

ЧТО СЧИТАЕТ СКРИПТ
-------------------
1. Цену 1 самоцвета (через листинг "753-Sack of Gems", 1000 шт за раз).
2. Список игр вашей библиотеки (через официальный Steam Web API).
3. Для каждой игры — карты её сета и текущие цены на маркете (обычные
   и фольговые отдельно).
4. (опционально, нужна авторизация) Стоимость одного бустер-пака в
   самоцветах для каждой игры — берётся со страницы Booster Creator.
   Без авторизации используется допущение DEFAULT_GEMS_PER_BOOSTER=1000
   (верно для большинства, но не всех игр).
5. Ожидаемую прибыль:
     EV(бустера) = 3 * средняя_цена_ОБЫЧНОЙ_карты_после_комиссии - цена_пака_в_деньгах
   где цена_пака_в_деньгах = gems_за_пак * цена_1_самоцвета.
   Фольга в основной расчёт EV НЕ включается (это редкий дроп, не 1/3 от
   пака) — показывается отдельной информационной колонкой.

ВАЖНОЕ ДОПУЩЕНИЕ ПРО "НАБОРЫ"
-------------------------------
Steam НЕ позволяет продать "сет" одним лотом — сет либо крафтится в
значок (значок нельзя перепродать), либо карточки продаются по одной.
Поэтому "продать набор" в этом скрипте трактуется как "продать все
карточки из набора по отдельности".

ТРЕБОВАНИЯ
----------
    pip install requests beautifulsoup4

НАСТРОЙКА (обязательно для получения списка библиотеки)
----------------------------------------------------------------------
1. Получите бесплатный Steam Web API ключ:
   https://steamcommunity.com/dev/apikey (привяжите к своему аккаунту).
2. SteamID64 определяется автоматически из куки STEAM_LOGIN_SECURE,
   либо задайте вручную.

ОДИН АККАУНТ
----------------------------------------------------------------------
    set STEAM_API_KEY=...
    set STEAM_LOGIN_SECURE=...
    set SESSIONID=...
    set STEAM_ID=...   (не обязательно, если STEAM_LOGIN_SECURE задан)

НЕСКОЛЬКО АККАУНТОВ (без релогинов/ручного редактирования между запусками)
----------------------------------------------------------------------
Перечислите метки аккаунтов через запятую в STEAM_ACCOUNTS, и для каждой
метки задайте переменные с суффиксом _МЕТКА (в верхнем регистре). Если
переменная с суффиксом не задана — используется значение без суффикса
(удобно для общего на все аккаунты API-ключа).

Пример для двух аккаунтов "main" и "alt" (Windows cmd):
    set STEAM_ACCOUNTS=main,alt
    set STEAM_API_KEY=общий_ключ_если_один_на_оба
    set STEAM_ID_MAIN=76561199002315417
    set STEAM_LOGIN_SECURE_MAIN=токен_первого_аккаунта
    set SESSIONID_MAIN=sessionid_первого
    set STEAM_ID_ALT=76561198111222333
    set STEAM_LOGIN_SECURE_ALT=токен_второго_аккаунта
    set SESSIONID_ALT=sessionid_второго
    py -3.11 steam_gem_arbitrage.py

Результаты по каждому аккаунту сохраняются в отдельный файл:
gem_arbitrage_results_<метка>.csv

Как получить куки STEAM_LOGIN_SECURE / SESSIONID для аккаунта:
    1. Зайдите на steamcommunity.com в браузере под нужным аккаунтом.
    2. DevTools -> Application/Storage -> Cookies -> скопируйте значения
       `steamLoginSecure` и `sessionid`.
    3. НЕ хардкодьте их в файле — это токен доступа к аккаунту, задавайте
       только через переменные окружения (`set ...`), не сохраняйте в код.

ОГРАНИЧЕНИЯ STEAM API
----------------------
- /market/priceoverview/ и /market/search/render/ рейт-лимитятся Steam;
  при превышении отдают 429. Скрипт делает паузы и повторные попытки —
  не понижайте задержки слишком сильно, иначе поймаете временный бан IP.

ЗАПУСК
------
    python3 steam_gem_arbitrage.py
"""

import os
import re
import csv
import json
import time
import math
import random
import sys
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# НАСТРОЙКИ
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# КОНФИГ-ФАЙЛ (опционально, чтобы не вводить всё через set/export каждый раз)
# ----------------------------------------------------------------------
# Если рядом со скриптом лежит steam_config.json — настройки и аккаунты
# берутся из него (см. steam_config.example.json как образец структуры).
# Если файла нет — всё работает как раньше, через переменные окружения.
#
# !!! steam_config.json будет содержать ЖИВЫЕ токены сессий — храните его
# !!! ТОЛЬКО локально, никогда не коммитьте в git и не показывайте никому
# !!! (добавьте "steam_config.json" в .gitignore).

CONFIG_FILE = "steam_config.json"


def load_config_file() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        print(f"[i] Конфиг загружен из {CONFIG_FILE} ({len(cfg.get('accounts', []))} аккаунтов).")
        return cfg
    except Exception as e:
        print(f"[!] Не удалось прочитать {CONFIG_FILE}: {e}. Использую переменные окружения.")
        return {}


_CONFIG = load_config_file()

# ----------------------------------------------------------------------
# НАСТРОЙКИ (из steam_config.json, если есть, иначе значения по умолчанию)
# ----------------------------------------------------------------------

CURRENCY = _CONFIG.get("currency", 18)  # 1=USD, 3=EUR, 5=RUB, 18=UAH ...
REQUEST_DELAY = _CONFIG.get("request_delay", 1.6)   # пауза между запросами к priceoverview, сек
SEARCH_DELAY = _CONFIG.get("search_delay", 1.8)     # пауза между запросами к market/search/render, сек
MAX_RETRIES = 5
CACHE_FILE = "steam_price_cache.json"

DEFAULT_GEMS_PER_BOOSTER = _CONFIG.get("default_gems_per_booster", 1000)
TOP_N = _CONFIG.get("top_n", 25)
ONLY_POSITIVE_EV = _CONFIG.get("only_positive_ev", False)

# Переопределение стоимости бустера в гемах для конкретных игр (appid ->
# gems_per_booster). Данные из Booster Creator (если авторизованы) имеют
# приоритет над этим списком.
MANUAL_GEMS_OVERRIDE = {int(k): v for k, v in _CONFIG.get("manual_gems_override", {}).items()}

# --- Несколько аккаунтов -----------------------------------------------
# Вариант 1 (проще): steam_config.json с массивом "accounts" — см.
# steam_config.example.json.
#
# Вариант 2 (без файла, через переменные окружения): перечислите метки
# через запятую в STEAM_ACCOUNTS, и для каждой метки задайте переменные
# с суффиксом _МЕТКА. Если переменная с суффиксом не задана — берётся
# значение без суффикса (удобно для общего API-ключа на все аккаунты).
#
# Пример (Windows cmd) для двух аккаунтов "main" и "alt":
#   set STEAM_ACCOUNTS=main,alt
#   set STEAM_API_KEY=общий_ключ_если_один_на_оба
#   set STEAM_ID_MAIN=76561199002315417
#   set STEAM_LOGIN_SECURE_MAIN=токен_первого_аккаунта
#   set SESSIONID_MAIN=sessionid_первого
#   set STEAM_ID_ALT=76561198111222333
#   set STEAM_LOGIN_SECURE_ALT=токен_второго_аккаунта
#   set SESSIONID_ALT=sessionid_второго
#
# Если ни steam_config.json, ни STEAM_ACCOUNTS не заданы — один аккаунт
# из несуффиксованных переменных (STEAM_ID / STEAM_LOGIN_SECURE / SESSIONID).

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)
# ВАЖНО: глобальная сессия НЕ несёт куки конкретного аккаунта — она
# используется только для публичных, не завязанных на аккаунт запросов
# (цены, карты). Куки нужны только для Booster Creator и передаются
# точечно в get_booster_creator_games(), отдельно на каждый аккаунт.


# ----------------------------------------------------------------------
# ПРОСТОЙ ДИСК-КЭШ, чтобы не долбить Steam повторно при перезапусках
# ----------------------------------------------------------------------

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


CACHE = load_cache()


# ----------------------------------------------------------------------
# НИЗКОУРОВНЕВЫЕ ЗАПРОСЫ К STEAM
# ----------------------------------------------------------------------

def _get_json(url: str, params: dict, delay: float = REQUEST_DELAY) -> Optional[dict]:
    """GET с ретраями и уважением к рейт-лимиту Steam."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            print(f"  [!] Сетевая ошибка: {e}, retry {attempt}/{MAX_RETRIES}")
            time.sleep(delay * attempt)
            continue

        if resp.status_code == 429:
            wait = delay * (2 ** attempt) + random.uniform(0, 1)
            print(f"  [!] 429 Too Many Requests, жду {wait:.1f}с...")
            time.sleep(wait)
            continue

        if resp.status_code != 200:
            print(f"  [!] HTTP {resp.status_code} для {url}")
            print(f"      Тело ответа (первые 300 симв.): {resp.text[:300]!r}")
            time.sleep(delay)
            continue

        try:
            parsed = resp.json()
        except ValueError:
            print("  [!] Ответ HTTP 200, но это не JSON (похоже на HTML/капчу).")
            print(f"      Тело ответа (первые 300 симв.): {resp.text[:300]!r}")
            return None

        if not parsed.get("success"):
            print(f"  [!] Steam вернул success=false. Полный ответ: {parsed}")

        return parsed

    return None


def parse_price_str(price_str: Optional[str]) -> Optional[float]:
    """'123,45 pуб.' / '$1.23' / '31₴' -> 123.45 (float). None если пусто."""
    if not price_str:
        return None
    cleaned = re.sub(r"[^\d,.\-]", "", price_str)
    cleaned = cleaned.replace(",", ".")
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


def get_price_overview(market_hash_name: str, appid: int = 753) -> Optional[dict]:
    """Цена одного лота на торговой площадке (appid=753 — площадка Steam)."""
    cache_key = f"price:{appid}:{market_hash_name}:{CURRENCY}"
    if cache_key in CACHE:
        return CACHE[cache_key]

    time.sleep(REQUEST_DELAY)
    data = _get_json(
        "https://steamcommunity.com/market/priceoverview/",
        {"appid": appid, "currency": CURRENCY, "market_hash_name": market_hash_name},
    )
    if data and data.get("success"):
        CACHE[cache_key] = data
        save_cache(CACHE)
    return data


def get_gem_unit_price() -> Optional[float]:
    """
    Цена ОДНОГО самоцвета, исходя из цены лота '753-Sack of Gems' (1000 шт).
    ВАЖНО: market_hash_name обязательно с префиксом '753-' — без него Steam
    отвечает success=true, но с пустыми полями цены (проверено вручную).
    """
    data = get_price_overview("753-Sack of Gems", appid=753)
    if not data:
        print("  [!] Пустой ответ от Steam (сеть/таймаут/капча) — см. диагностику выше.")
        return None
    if not data.get("success"):
        print(f"  [!] success=false. Полный ответ: {data}")
        return None
    print(f"  [i] Сырой ответ Steam по Sack of Gems: {data}")
    price = parse_price_str(data.get("lowest_price") or data.get("median_price"))
    if price is None:
        print("  [!] success=true, но поля lowest_price/median_price пустые.")
        return None
    return price / 1000.0


# ----------------------------------------------------------------------
# КОМИССИЯ STEAM MARKET (обратный расчёт: сколько получит продавец)
# ----------------------------------------------------------------------

STEAM_FEE_RATE = 0.05
PUBLISHER_FEE_RATE = 0.10


def net_amount_after_fee(listed_price: float) -> float:
    """Сколько получит продавец, если ВЫСТАВИТ лот по цене listed_price."""
    if listed_price <= 0:
        return 0.0
    cents = round(listed_price * 100)

    def fees_for(pre_fee_cents: float):
        steam_fee = max(1, math.floor(pre_fee_cents * STEAM_FEE_RATE))
        pub_fee = max(1, math.floor(pre_fee_cents * PUBLISHER_FEE_RATE))
        return steam_fee, pub_fee

    pre_fee_est = cents / (1 + STEAM_FEE_RATE + PUBLISHER_FEE_RATE)
    best = pre_fee_est
    for delta in range(-3, 4):
        candidate = round(pre_fee_est) + delta
        if candidate <= 0:
            continue
        sf, pf = fees_for(candidate)
        if candidate + sf + pf == cents:
            best = candidate
            break
    return round(best / 100.0, 2)


# ----------------------------------------------------------------------
# ВАША БИБЛИОТЕКА ИГР (Steam Web API)
# ----------------------------------------------------------------------

def parse_steamid_from_login_cookie(cookie_value: str) -> Optional[str]:
    """steamLoginSecure имеет формат '<SteamID64>||<токен>' (иногда разделитель
    приходит URL-закодированным как %7C%7C, если скопирован из адресной строки)."""
    if not cookie_value:
        return None
    normalized = cookie_value.replace("%7C%7C", "||").replace("%7c%7c", "||")
    parts = normalized.split("||")
    if parts and parts[0].isdigit() and len(parts[0]) >= 15:
        return parts[0]
    return None


def get_owned_games(api_key: str, steamid: str) -> list:
    """
    [(appid, name), ...] игр библиотеки указанного аккаунта через
    официальный Steam Web API.
    """
    if not api_key:
        print("  [!] Не задан API-ключ для этого аккаунта. Получите бесплатный "
              "ключ на https://steamcommunity.com/dev/apikey.")
        return []
    if not steamid:
        print("  [!] Не смог определить SteamID64 для этого аккаунта. Задайте "
              "вручную (17-значный ID, посмотреть можно на https://steamid.io), "
              "либо задайте STEAM_LOGIN_SECURE — steamid определится автоматически.")
        return []

    print(f"  [i] Запрашиваю библиотеку для SteamID64 {steamid}...")
    data = _get_json(
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/",
        {
            "key": api_key,
            "steamid": steamid,
            "format": "json",
            "include_appinfo": 1,
            "include_played_free_games": 1,
        },
    )
    if not data or "response" not in data:
        print("  [!] Пустой/некорректный ответ Steam Web API — проверьте ключ и steamid.")
        return []

    games = data["response"].get("games", [])
    if not games:
        print("  [!] Библиотека пуста, либо её видимость закрыта. В настройках "
              "приватности Steam-профиля 'Game details' должно быть Public — "
              "либо это должен быть собственный API-ключ для этого же "
              "steamid (тогда обычно работает и без публичного профиля).")
        return []

    print(f"  [i] Найдено игр в библиотеке: {len(games)}")
    return [(g["appid"], g.get("name", str(g["appid"]))) for g in games]


# ----------------------------------------------------------------------
# (ОПЦИОНАЛЬНО) ТОЧНАЯ ЦЕНА ПАКА В ГЕМАХ С BOOSTER CREATOR
# ----------------------------------------------------------------------

def get_booster_creator_games(login_secure: str, sessionid: str) -> dict:
    """
    Парсит https://steamcommunity.com/tradingcards/boostercreator/ для
    указанного аккаунта (свои куки, не глобальная сессия — чтобы можно
    было безопасно обрабатывать несколько аккаунтов подряд без утечки
    кук одного аккаунта в запросы другого). Возвращает {appid: gems_cost}.
    Без кук возвращает {} — тогда используется DEFAULT_GEMS_PER_BOOSTER.
    """
    if not login_secure:
        print(f"  [i] STEAM_LOGIN_SECURE не задан для этого аккаунта — точная цена "
              f"бустеров недоступна, использую допущение {DEFAULT_GEMS_PER_BOOSTER} "
              "гем/пак (кроме перечисленных в MANUAL_GEMS_OVERRIDE).")
        return {}

    cookies = {"steamLoginSecure": login_secure}
    if sessionid:
        cookies["sessionid"] = sessionid

    try:
        resp = requests.get("https://steamcommunity.com/tradingcards/boostercreator/",
                             headers=HEADERS, cookies=cookies, timeout=20)
    except requests.RequestException as e:
        print(f"  [!] Сетевая ошибка при запросе Booster Creator: {e}")
        return {}

    if resp.status_code != 200:
        print(f"  [!] Не удалось получить boostercreator: HTTP {resp.status_code}")
        return {}

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    # Основной путь (CSS-классы страницы Booster Creator старого образца)
    for row in soup.select(".booster_creator_game"):
        appid_attr = row.get("data-appid")
        if not appid_attr:
            continue
        price_el = row.select_one(".gamebooster_price")
        gems = None
        if price_el:
            m = re.search(r"([\d,]+)", price_el.get_text())
            if m:
                gems = int(m.group(1).replace(",", ""))
        result[int(appid_attr)] = gems or DEFAULT_GEMS_PER_BOOSTER

    if not result:
        # Фолбэк №1: Steam часто хранит данные страницы в виде JS-объекта
        # прямо в <script>, а не в HTML-атрибутах — пробуем вытащить оттуда
        # пары (appid, цена_в_гемах) через широкий regex по всему тексту.
        js_matches = re.findall(
            r'"?appid"?\s*:\s*(\d+)[^{}]{0,200}?"?price"?\s*:\s*"?(\d+)"?',
            html, re.IGNORECASE,
        )
        for appid_s, gems_s in js_matches:
            try:
                result[int(appid_s)] = int(gems_s)
            except ValueError:
                continue

    if not result:
        # Диагностика: ничего не нашли — печатаем, что реально есть на странице,
        # чтобы можно было точно откалибровать парсинг под актуальную разметку.
        has_data_appid = len(re.findall(r'data-appid="(\d+)"', html))
        print(f"  [!] Не смог распарсить Booster Creator ни основным способом, ни "
              f"фолбэком. Диагностика: длина HTML={len(html)} символов, "
              f"вхождений data-appid=\"...\" в сыром HTML: {has_data_appid}.")
        if has_data_appid:
            sample_pos = re.search(r'data-appid="\d+"', html).start()
            print(f"  [DEBUG] Фрагмент вокруг первого data-appid "
                  f"(500 симв.):\n{html[max(0,sample_pos-100):sample_pos+400]}")
        else:
            gem_hits = re.findall(r'.{60}(?:[Gg]ems?|гем\w*).{60}', html)[:3]
            if gem_hits:
                print("  [DEBUG] Фрагменты с упоминанием гемов (до 3 шт):")
                for h in gem_hits:
                    print(f"    ...{h}...")
            else:
                print("  [DEBUG] Даже слово 'gems'/'гем' не встречается в HTML — "
                      "возможно, страница отдала не тот контент (логин истёк, "
                      "редирект на страницу входа, капча) для этого аккаунта.")
        print("  [!] Пришлите мне вывод [DEBUG] выше — поправлю парсинг под "
              "актуальную структуру страницы.")
        return {}

    if result:
        print(f"  [i] Booster Creator: получены точные цены паков для {len(result)} игр.")
    return result


# ----------------------------------------------------------------------
# КАРТЫ ИГРЫ + ИХ ЦЕНЫ ЗА ОДИН ЗАПРОС (поиск маркета, без priceoverview)
# ----------------------------------------------------------------------

# Опознаём фольговую карту по названию лота.
FOIL_MARKERS = ("(Foil)", "Foil Trading Card", "(Foil Trading Card)")


def is_foil_card(market_hash_name: str) -> bool:
    return any(marker.lower() in market_hash_name.lower() for marker in FOIL_MARKERS)


def get_game_cards_with_prices(appid: int) -> list:
    """
    Список карт игры С ЦЕНАМИ за ОДИН запрос (цена уже есть в результатах
    поиска — sell_price_text, отдельный поход в priceoverview не нужен).
    Возвращает: [{"hash_name":str, "lowest": float|None, "foil": bool}, ...]
    """
    cache_key = f"cards_priced:{appid}:{CURRENCY}"
    if cache_key in CACHE:
        return CACHE[cache_key]

    time.sleep(SEARCH_DELAY)
    params = {
        "query": "",
        "start": 0,
        "count": 100,
        "search_descriptions": 0,
        "sort_column": "name",
        "sort_dir": "asc",
        "appid": 753,
        "norender": 1,
        "currency": CURRENCY,
        "category_753_Game[]": f"tag_app_{appid}",
        "category_753_item_class[]": "tag_item_class_2",  # Trading Card
    }
    data = _get_json("https://steamcommunity.com/market/search/render/", params, delay=SEARCH_DELAY)
    cards = []
    if data and data.get("success"):
        for row in data.get("results", []):
            hash_name = row.get("hash_name")
            if not hash_name:
                continue
            # подстраховка: если фильтр по игре вдруг не сработал как ожидается,
            # проверяем appid по числовому префиксу самого hash_name
            m = re.match(r"^(\d+)-", hash_name)
            if m and int(m.group(1)) != appid:
                continue
            price = parse_price_str(row.get("sell_price_text"))
            cards.append({"hash_name": hash_name, "lowest": price, "foil": is_foil_card(hash_name)})
    CACHE[cache_key] = cards
    save_cache(CACHE)
    return cards


# ----------------------------------------------------------------------
# АНАЛИТИКА ПО ОДНОЙ ИГРЕ
# ----------------------------------------------------------------------

@dataclass
class GameAnalysis:
    appid: int
    name: str = ""
    num_cards: int = 0
    num_normal_cards: int = 0
    num_foil_cards: int = 0
    gems_per_booster: int = 1000
    gem_unit_price: float = 0.0
    booster_cost_money: float = 0.0
    avg_normal_card_lowest_price: float = 0.0
    avg_normal_card_net_after_fee: float = 0.0
    avg_foil_card_net_after_fee: float = 0.0
    ev_per_booster: float = 0.0
    roi_percent: float = 0.0
    full_set_buy_cost: float = 0.0
    full_set_sell_value: float = 0.0
    card_prices: dict = field(default_factory=dict)


def analyze_game(appid: int, gems_per_booster: int, gem_unit_price: float,
                  name_hint: str = "") -> Optional[GameAnalysis]:
    cards = get_game_cards_with_prices(appid)
    if not cards:
        print(f"  [i] appid {appid} ({name_hint}): нет сета трейдинг-карт на маркете — пропускаю.")
        return None

    result = GameAnalysis(appid=appid, name=name_hint or str(appid), num_cards=len(cards),
                           gems_per_booster=gems_per_booster, gem_unit_price=gem_unit_price)

    normal_lowest, normal_net, foil_net = [], [], []
    for c in cards:
        if c["lowest"] is None:
            continue
        net = net_amount_after_fee(c["lowest"])
        result.card_prices[c["hash_name"]] = {"lowest": c["lowest"], "net": net, "foil": c["foil"]}
        if c["foil"]:
            foil_net.append(net)
        else:
            normal_lowest.append(c["lowest"])
            normal_net.append(net)

    result.num_normal_cards = len(normal_net)
    result.num_foil_cards = len(foil_net)

    if not normal_net:
        print(f"  [!] appid {appid} ({result.name}): нет цен ни по одной обычной карте — пропускаю.")
        return None

    result.avg_normal_card_lowest_price = sum(normal_lowest) / len(normal_lowest)
    result.avg_normal_card_net_after_fee = sum(normal_net) / len(normal_net)
    if foil_net:
        result.avg_foil_card_net_after_fee = sum(foil_net) / len(foil_net)

    # EV считаем ТОЛЬКО по обычным картам — фольга выпадает из бустера
    # крайне редко, включать её наравне с обычными картами необоснованно
    # завышает ожидаемую прибыль.
    result.booster_cost_money = gems_per_booster * gem_unit_price
    result.ev_per_booster = 3 * result.avg_normal_card_net_after_fee - result.booster_cost_money
    if result.booster_cost_money > 0:
        result.roi_percent = (result.ev_per_booster / result.booster_cost_money) * 100
    result.full_set_buy_cost = sum(normal_lowest)
    result.full_set_sell_value = sum(normal_net)

    print(f"  appid {appid:>7} | {result.name[:32]:<32} | обыч {result.num_normal_cards:>2} "
          f"фольга {result.num_foil_cards:>2} | EV/пак {result.ev_per_booster:>8.2f} | "
          f"ROI {result.roi_percent:>7.1f}%")

    return result


# ----------------------------------------------------------------------
# ГЛАВНАЯ ФУНКЦИЯ
# ----------------------------------------------------------------------

def print_and_export(results: list, csv_path: str = "gem_arbitrage_results.csv") -> None:
    if ONLY_POSITIVE_EV:
        pool = [r for r in results if r.ev_per_booster > 0]
    else:
        pool = list(results)

    pool.sort(key=lambda r: r.ev_per_booster, reverse=True)
    top = pool[:TOP_N] if TOP_N else pool

    print(f"\n\n===================== ТОП-{len(top)} ПО ВЫГОДЕ "
          f"(из {len(results)} игр вашей библиотеки с картами) =====================")
    print(f"{'appid':>8} | {'игра':<28} | {'обыч':>4} | {'фольга':>6} | {'гем/пак':>7} | "
          f"{'ст-ть пака':>10} | {'ср.цена карты':>13} | {'EV с пака':>10} | {'ROI %':>7}")
    for r in top:
        name_short = (r.name[:26] + "…") if len(r.name) > 27 else r.name
        print(f"{r.appid:>8} | {name_short:<28} | {r.num_normal_cards:>4} | "
              f"{r.num_foil_cards:>6} | {r.gems_per_booster:>7} | "
              f"{r.booster_cost_money:>10.2f} | {r.avg_normal_card_net_after_fee:>13.2f} | "
              f"{r.ev_per_booster:>10.2f} | {r.roi_percent:>6.1f}%")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "appid", "name", "num_normal_cards", "num_foil_cards", "gems_per_booster",
            "booster_cost_money", "avg_normal_card_lowest_price",
            "avg_normal_card_net_after_fee", "avg_foil_card_net_after_fee",
            "ev_per_booster", "roi_percent", "full_set_buy_cost", "full_set_sell_value",
        ])
        for r in pool:
            writer.writerow([
                r.appid, r.name, r.num_normal_cards, r.num_foil_cards, r.gems_per_booster,
                f"{r.booster_cost_money:.2f}",
                f"{r.avg_normal_card_lowest_price:.2f}",
                f"{r.avg_normal_card_net_after_fee:.2f}",
                f"{r.avg_foil_card_net_after_fee:.2f}",
                f"{r.ev_per_booster:.2f}", f"{r.roi_percent:.1f}",
                f"{r.full_set_buy_cost:.2f}", f"{r.full_set_sell_value:.2f}",
            ])
    print(f"\nПолный список ({len(pool)} игр) сохранён в {csv_path}")
    print("[!] Напоминание: EV считается ТОЛЬКО по обычным (не фольговым) картам.")


# ----------------------------------------------------------------------
# СБОРКА СПИСКА АККАУНТОВ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ----------------------------------------------------------------------

def build_accounts() -> list:
    # Вариант 1: аккаунты заданы в steam_config.json
    config_accounts = _CONFIG.get("accounts")
    if config_accounts:
        accounts = []
        for i, acc in enumerate(config_accounts):
            label = acc.get("label") or f"account{i + 1}"
            login_secure = acc.get("login_secure", "")
            steam_id = acc.get("steam_id") or parse_steamid_from_login_cookie(login_secure)
            accounts.append({
                "label": label,
                "api_key": acc.get("api_key") or _CONFIG.get("api_key", ""),
                "steam_id": steam_id,
                "login_secure": login_secure,
                "sessionid": acc.get("sessionid", ""),
            })
        return accounts

    # Вариант 2 (фолбэк): переменные окружения
    labels = [l.strip() for l in os.environ.get("STEAM_ACCOUNTS", "").split(",") if l.strip()]
    if not labels:
        labels = ["default"]

    accounts = []
    for label in labels:
        suffix = re.sub(r"[^A-Z0-9_]", "_", label.upper())

        def env(base: str) -> str:
            return os.environ.get(f"{base}_{suffix}", "") or os.environ.get(base, "")

        login_secure = env("STEAM_LOGIN_SECURE")
        steam_id = env("STEAM_ID") or parse_steamid_from_login_cookie(login_secure)
        accounts.append({
            "label": label,
            "api_key": env("STEAM_API_KEY"),
            "steam_id": steam_id,
            "login_secure": login_secure,
            "sessionid": env("SESSIONID"),
        })
    return accounts


def process_account(account: dict, gem_price: float) -> list:
    label = account["label"]
    print(f"\n{'=' * 70}\nАККАУНТ: {label}\n{'=' * 70}")

    owned_games = get_owned_games(account["api_key"], account["steam_id"])
    if not owned_games:
        print(f"  [!] Не удалось получить библиотеку для аккаунта '{label}' — пропускаю его.")
        return []

    gems_override = dict(MANUAL_GEMS_OVERRIDE)
    booster_creator_gems = get_booster_creator_games(account["login_secure"], account["sessionid"])
    confirmed_craftable = set(booster_creator_gems.keys()) | set(MANUAL_GEMS_OVERRIDE.keys())
    if booster_creator_gems:
        gems_override.update(booster_creator_gems)

    est_minutes = len(owned_games) * SEARCH_DELAY / 60
    print(f"\n  Считаю экономику по {len(owned_games)} играм "
          f"(примерно {est_minutes:.1f} мин)...\n")

    results = []
    skipped_unconfirmed = []
    for appid, name in owned_games:
        if booster_creator_gems and appid not in confirmed_craftable:
            # см. пояснение в комментарии ниже про No More Room in Hell —
            # без подтверждения из Booster Creator считать EV нечестно.
            skipped_unconfirmed.append((appid, name))
            continue
        gems_cost = gems_override.get(appid, DEFAULT_GEMS_PER_BOOSTER)
        analysis = analyze_game(appid, gems_cost, gem_price, name_hint=name)
        if analysis:
            results.append(analysis)

    if skipped_unconfirmed:
        print(f"\n  [i] Пропущено {len(skipped_unconfirmed)} игр — не подтверждены в "
              f"Booster Creator как доступные для крафта:")
        for appid, name in skipped_unconfirmed:
            print(f"      - {appid}: {name}")

    if not booster_creator_gems:
        print(f"\n  [!] Booster Creator недоступен для '{label}' (нет авторизации/сбой) — "
              f"считаю ВСЕ {len(owned_games)} игр с допущением "
              f"{DEFAULT_GEMS_PER_BOOSTER} гем/пак. Часть из них может оказаться "
              f"нереальной для крафта — проверяйте вручную перед тем, как полагаться "
              "на цифры.")

    csv_path = f"gem_arbitrage_results_{label}.csv"
    print_and_export(results, csv_path=csv_path)
    return results


def main():
    print("Получаю цену самоцвета (Sack of Gems)...")
    gem_price = get_gem_unit_price()
    if gem_price is None:
        print("Не удалось получить цену самоцветов. Проверьте сеть/куки. Выход.")
        sys.exit(1)
    print(f"Цена 1 самоцвета: {gem_price:.5f}")

    accounts = build_accounts()
    print(f"\nБудет обработано аккаунтов: {len(accounts)} "
          f"({', '.join(a['label'] for a in accounts)})")

    all_results = {}
    for account in accounts:
        all_results[account["label"]] = process_account(account, gem_price)

    print(f"\n\n{'=' * 70}\nИТОГО ПО ВСЕМ АККАУНТАМ\n{'=' * 70}")
    for label, results in all_results.items():
        positive = sum(1 for r in results if r.ev_per_booster > 0)
        print(f"  {label}: игр посчитано {len(results)}, из них прибыльных: {positive} "
              f"(файл: gem_arbitrage_results_{label}.csv)")


if __name__ == "__main__":
    main()

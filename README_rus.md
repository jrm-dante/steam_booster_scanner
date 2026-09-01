# steam_booster_scanner

Считает ожидаемую прибыль от крафта бустер-паков из самоцветов Steam для
игр вашей библиотеки: цена пака в гемах vs суммарная цена продажи карт
этого набора на торговой площадке (после комиссии).

## Установка

```
pip install requests beautifulsoup4
```

## Настройка

1. Скопируйте `steam_config.example.json` в `steam_config.json`.
2. Получите бесплатный ключ Steam Web API: https://steamcommunity.com/dev/apikey
3. Получите `steamLoginSecure` / `sessionid`: залогиньтесь на
   steamcommunity.com в браузере -> DevTools -> Application/Storage ->
   Cookies -> скопируйте значения.
4. Впишите всё это в `steam_config.json` (см. комментарии внутри файла).

**`steam_config.json` содержит токен доступа к вашему аккаунту — файл в
`.gitignore`, не коммитьте его и никому не показывайте.**

## Запуск

```
python steam_gem_arbitrage.py
```

Результаты по каждому аккаунту сохраняются в `gem_arbitrage_results_<метка>.csv`.

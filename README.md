# steam_booster_scanner

Calculates the expected profit from crafting Steam gem booster packs for
games in your library: the pack price in gems versus the total resale value
of the cards in that set on the marketplace (after fees).

### README translation

[README_rus.md](README_rus.md)

## Installation

```
pip install requests beautifulsoup4
```

## Setup

1. Copy `steam_config.example.json` to `steam_config.json`.
2. Get a free Steam Web API key: https://steamcommunity.com/dev/apikey
3. Get your `steamLoginSecure` / `sessionid`: log in to
   steamcommunity.com in your browser -> DevTools -> Application/Storage ->
   Cookies -> copy the values.
4. Enter all of this into `steam_config.json` (see comments in the file).

**`steam_config.json` contains your account access token — the file is in
`.gitignore`, do not commit it and do not show it to anyone.**

## Running

```
python steam_gem_arbitrage.py
```

Results for each account are saved to `gem_arbitrage_results_<label>.csv`.

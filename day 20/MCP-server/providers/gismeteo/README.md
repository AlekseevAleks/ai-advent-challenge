# Gismeteo Provider

[Gismeteo Weather Forecast API v2](https://docs.gismeteo.net/v2/weather) — текущая погода,
суточный прогноз (агрегация 24 ч) и поиск населённых пунктов.

- ID: `gismeteo`
- Tools: `gismeteo_current`, `gismeteo_forecast`, `gismeteo_search_city`
- Конфигурация: `config/providers/gismeteo.json`
- **Требуется API token** (заголовок `X-Gismeteo-Token`): задаётся в Web UI
  (Providers → Gismeteo → Credentials) или через env `GISMETEO_TOKEN`.

Базовая схема ответов API: `{ "meta": {...}, "response": ... }`.
Типы осадков: 0 — нет, 1 — дождь, 2 — снег, 3 — смешанные. Облачность: 0..3.
Направление ветра: румбы 0..8 (0 — штиль, 1..8 — от севера по часовой стрелке).
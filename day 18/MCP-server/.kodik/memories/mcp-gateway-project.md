---
title: "MCP Gateway проект: команды и архитектура"
---

# MCP Gateway — проект в /Users/lexx/Documents/AI challenge/MCP-server

Локальный MCP Gateway: MCP-сервер (Streamable HTTP на /mcp + stdio) + Web UI (React/Vite) + плагинные API-провайдеры.

## Команды
- `npm run dev` — backend (tsx watch) + web (Vite 5173 с прокси /api и /mcp на 3000)
- `npm run build` — tsc (dist/src) + vite build (web/dist)
- `npm start` — node dist/src/server/index.js (слушает 127.0.0.1:3000, раздаёт Web UI)
- `npm run test` — vitest (53 теста), `npm run validate-config`
- `npm run mcp-stdio` — stdio-режим для Claude Desktop

## Архитектура
- `src/core/{config,logging,http,providers,registry}` + `providers/{weather,github,gismeteo}` + `src/server` (Fastify, mcp-http/mcp-server/mcp-stdio, routes) + `web/` (workspace-пакет)
- ProviderRegistry: классы из `providers/index.ts`, конфиги `config/providers/<id>.json`, hot reload без рестарта
- HttpClient — единый слой (timeout, retries, 429/Retry-After, редaкция секретов перед JSONL-логами)
- Секреты: маска в API (`ghp_****abcd`), [REDACTED] в логах, никогда полным значением из API

## Провайдеры
- weather (Open-Meteo, без ключа): weather_current, weather_forecast
- github (GitHub REST, PAT опционален): 6 tools
- gismeteo (Gismeteo API v2, https://api.gismeteo.net, ТОКЕН ОБЯЗАТЕЛЕН — X-Gismeteo-Token, env GISMETEO_TOKEN): gismeteo_current, gismeteo_forecast, gismeteo_search_city; ответы {meta,response}, ошибки {meta.status_code, errors[]}; поля: temperature.air.C, wind.speed.km_h и т.д.

## Ключевые нюансы (важно не сломать)
- MCP SDK 1.30: `StreamableHTTPServerTransport` = ОДНА сессия на инстанс; в `src/server/mcp-http.ts` создаётся transport+Server на каждый initialize, сессии в Map по Mcp-Session-Id
- MCP SDK 1.30: POST /mcp требует Accept с application/json И text/event-stream → 406 "Not Acceptable" клиентам без SSE (не исправлено, известная проблема)
- Fastify: custom JSON parser для пустых тел (POST enable/disable/test без тела), иначе 400 FST_ERR_CTP_EMPTY_JSON_BODY
- Импорты в backend — с `.js` суффиксами (NodeNext); корневой tsconfig НЕ включает web/src (JSX/DOM в web/tsconfig)
- LogLevel включает 'silent' (для тестов/CLI); authError(message, code, status?, details?)

## Проверено e2e
weather_current/forecast + github_get_repository реальные вызовы через MCP HTTP/stdio, hot reload tools, редaкция токенов в логах; gismeteo — без токена понятная auth-ошибка, с фейковым токеном реальный 401 от API.

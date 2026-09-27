# Weather Provider (Open-Meteo)

Демонстрационный провайдер без API key. Использует Open-Meteo Forecast API.

- ID: `weather`
- Tools: `weather_current`, `weather_forecast`
- Конфигурация: `config/providers/weather.json`
- Документация API: https://open-meteo.com/en/docs

Провайдер преобразует «сырые» поля Open-Meteo в компактный результат,
понятный AI-агенту (описание погоды по WMO-коду вместо числового кода и т.д.).
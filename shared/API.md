# API contract v1

Все ошибки имеют вид `{"error": "сообщение"}`. Времена запуска и погодного выпуска в будущих ответах должны содержать часовой пояс ISO 8601.

## GET /api/health

Ответ 200: `{"status":"ok"}`.

## GET /api/turbines

Ответ 200: `{"turbines":[{"id":"turbine_1","rows":142360,"first_observation":"2023-03-11T00:00:00","last_observation":"2026-01-31T23:50:00","expected_rows":152352,"missing_intervals":9992}]}`. Поля наблюдений намеренно без часового пояса, как в источнике. Значения вычисляются из CSV.

## POST /api/forecast-runs

Запрос: `{"turbine_id":"turbine_1","issued_at":"2026-01-31T00:00:00+05:00","horizon_hours":48}`. `horizon_hours` — 24 или 48. `issued_at` обязан содержать часовой пояс. Пока модель не подключена, ответ 501: `{"error":"Прогнозная модель пока не подключена"}`.

Планируемый успешный ответ: `{"run_id":"...","turbine_id":"turbine_1","issued_at":"...","weather_run_issued_at":"...","model_version":"...","points":[{"time":"...","normalized_power":0.42}]}`. Точный контракт результата следует согласовать перед реализацией.

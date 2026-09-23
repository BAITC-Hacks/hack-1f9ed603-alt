# API contract v1

Этот документ фиксирует интерфейс между `backend/`, `frontend/` и `forecasting/`. Ниже приведён ответ проверочного запуска `POST /api/forecast-runs`; `run_id` при каждом вызове создаётся заново.

## Турбины и координаты

Координаты извлечены из ссылок Google Maps в условии задачи:

| ID | Широта | Долгота | Источник |
| --- | ---: | ---: | --- |
| `turbine_1` | 43.645150 | 78.535604 | https://maps.app.goo.gl/iN6svMt69D5qRpFU9 |
| `turbine_2` | 43.643198 | 78.538828 | https://maps.app.goo.gl/8UQMwsYavY6nLvFY8 |

Для запроса погоды используйте десятичные градусы WGS84. Не округляйте координаты до менее чем шести знаков после запятой в конфигурации источника.

## Время

`Статистическое время` в CSV не имеет смещения UTC и в условии не указан его часовой пояс. **Часовой пояс наблюдений не установлен.** Эти значения остаются локальными метками без смещения до письменного подтверждения от поставщика данных/организаторов. Нельзя автоматически считать их ни UTC, ни `Asia/Almaty`.

Географическое местное время в этом регионе изменилось с UTC+6 на UTC+5 1 марта 2024 года ([сообщение правительства Казахстана](https://www.gov.kz/memleket/entities/mti/press/news/details/688998?lang=ru)). При этом ряды CSV идут без повторённого часа в этот переход. Это **не доказывает**, в каком поясе записаны данные, и делает простое присвоение местного пояса опасным. До выяснения вопроса нельзя надёжно соединять историю турбин с почасовой погодой по абсолютному времени.

Все моменты в API (`issued_at`, `input_data_cutoff_at`, `weather_run_issued_at`, `weather_run_initialized_at`, `weather_run_usable_after_at`, `weather_actual_publication_at`, `points[].time`) — ISO 8601 со смещением, кроме `weather_actual_publication_at`, которое может быть `null`. Бэкенд принимает явное смещение или `Z`, а в ответе возвращает UTC с `Z`. Только `first_observation` и `last_observation` сохраняют исходные метки CSV без пояса.

## GET /api/health

Ответ `200`:

```json
{"status":"ok"}
```

## GET /api/turbines

Ответ `200`. Значения `rows` и `missing_intervals` вычисляются из файлов; пример соответствует текущим CSV:

```json
{
  "turbines": [
    {
      "id": "turbine_1",
      "latitude": 43.64515,
      "longitude": 78.535604,
      "rows": 142360,
      "first_observation": "2023-03-11T00:00:00",
      "last_observation": "2026-01-31T23:50:00",
      "expected_rows": 152352,
      "missing_intervals": 9992
    },
    {
      "id": "turbine_2",
      "latitude": 43.643198,
      "longitude": 78.538828,
      "rows": 149499,
      "first_observation": "2023-03-11T00:00:00",
      "last_observation": "2026-01-31T23:50:00",
      "expected_rows": 152352,
      "missing_intervals": 2853
    }
  ]
}
```

Если CSV отсутствует или повреждён, ответ `503` с полем `error`.

## POST /api/forecast-runs

Синхронный запуск одного прогноза для одной турбины. Запрос:

```json
{
  "turbine_id": "turbine_1",
  "issued_at": "2026-02-01T12:00:00Z",
  "horizon_hours": 24
}
```

`turbine_id` принимает только `turbine_1` или `turbine_2`; `horizon_hours` — только 24 или 48. `issued_at` обязательно содержит смещение или `Z` и приходится на начало часа по UTC. Для исторического запуска погодный выпуск и все входные наблюдения должны быть доступны к `issued_at`.

При успехе: `201 Created` и полный результат. **Следующие числа и идентификаторы вымышлены исключительно для примера формата; API не должен возвращать их вместо расчёта.**

```json
{
  "run_id": "e96af92c-6995-4dc0-8531-0ac762c98e70",
  "status": "completed",
  "turbine_id": "turbine_1",
  "issued_at": "2026-02-01T12:00:00Z",
  "horizon_hours": 24,
  "unit": "normalized_power",
  "input_data_cutoff_at": "2026-01-31T19:00:00Z",
  "weather_source": "open_meteo_single_runs_ecmwf_ifs",
  "weather_run_id": "ecmwf_ifs_20260201T0000Z",
  "weather_run_issued_at": "2026-02-01T00:00:00Z",
  "weather_run_initialized_at": "2026-02-01T00:00:00Z",
  "weather_run_usable_after_at": "2026-02-01T12:00:00Z",
  "weather_actual_publication_at": null,
  "model_version": "ecmwf_ifs_100m_bin_curve_v1_final_20260201T0000Z",
  "points": [
    {
      "time": "2026-02-01T13:00:00Z",
      "normalized_power": 0.371398
    },
    {
      "time": "2026-02-01T14:00:00Z",
      "normalized_power": 0.47421
    },
    {
      "time": "2026-02-01T15:00:00Z",
      "normalized_power": 0.371398
    },
    {
      "time": "2026-02-01T16:00:00Z",
      "normalized_power": 0.371398
    },
    {
      "time": "2026-02-01T17:00:00Z",
      "normalized_power": 0.371398
    },
    {
      "time": "2026-02-01T18:00:00Z",
      "normalized_power": 0.371398
    },
    {
      "time": "2026-02-01T19:00:00Z",
      "normalized_power": 0.370652
    },
    {
      "time": "2026-02-01T20:00:00Z",
      "normalized_power": 0.370652
    },
    {
      "time": "2026-02-01T21:00:00Z",
      "normalized_power": 0.370652
    },
    {
      "time": "2026-02-01T22:00:00Z",
      "normalized_power": 0.371398
    },
    {
      "time": "2026-02-01T23:00:00Z",
      "normalized_power": 0.528043
    },
    {
      "time": "2026-02-02T00:00:00Z",
      "normalized_power": 0.528043
    },
    {
      "time": "2026-02-02T01:00:00Z",
      "normalized_power": 0.528043
    },
    {
      "time": "2026-02-02T02:00:00Z",
      "normalized_power": 0.47421
    },
    {
      "time": "2026-02-02T03:00:00Z",
      "normalized_power": 0.47421
    },
    {
      "time": "2026-02-02T04:00:00Z",
      "normalized_power": 0.637734
    },
    {
      "time": "2026-02-02T05:00:00Z",
      "normalized_power": 0.528043
    },
    {
      "time": "2026-02-02T06:00:00Z",
      "normalized_power": 0.514649
    },
    {
      "time": "2026-02-02T07:00:00Z",
      "normalized_power": 0.686633
    },
    {
      "time": "2026-02-02T08:00:00Z",
      "normalized_power": 0.771929
    },
    {
      "time": "2026-02-02T09:00:00Z",
      "normalized_power": 0.771929
    },
    {
      "time": "2026-02-02T10:00:00Z",
      "normalized_power": 0.686633
    },
    {
      "time": "2026-02-02T11:00:00Z",
      "normalized_power": 0.637734
    },
    {
      "time": "2026-02-02T12:00:00Z",
      "normalized_power": 0.528043
    }
  ]
}
```

`points` содержит ровно `horizon_hours` элементов с шагом один час, по возрастанию. Первый `time = issued_at + 1 час`. Каждая точка — средняя нормализованная активная мощность за предшествующий час `(time - 1 час, time]`, число от 0 до 1. Это **не кВт·ч**. `input_data_cutoff_at` не может быть позже `issued_at`. `weather_run_id` должен позволять воспроизвести источник погоды.

`weather_run_initialized_at` — время инициализации погодной модели, а `weather_run_usable_after_at` — расчётный порог доступности: инициализация плюс консервативные 12 часов. Оба времени не позже `issued_at`. Архив Open-Meteo не содержит точного исторического времени публикации, поэтому `weather_actual_publication_at` равен `null`; время инициализации не следует выдавать за подтверждённую публикацию. Устаревающее поле `weather_run_issued_at` оставлено для совместимости и равно `weather_run_initialized_at`; новые клиенты должны использовать явное имя.

## Ошибки и текущее состояние

Все ошибки: `{"error":"человекочитаемое сообщение"}`. `422` — неверный запрос; `503` — данные/погодный источник временно недоступны; `500` — внутренняя ошибка без трассировки в ответе. Если модуль прогнозного ядра отсутствует, `POST /api/forecast-runs` возвращает `501`:

```json
{"error":"Прогнозная модель пока не подключена"}
```

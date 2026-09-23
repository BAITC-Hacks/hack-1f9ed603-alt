# Backend — подключение прогнозного ядра

Запуск из корня репозитория:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --reload --port 8000
```

API читает CSV из `DATA_DIR` (по умолчанию `data/raw`). Успешные запуски записываются в SQLite по пути `RUNS_DB_PATH` (по умолчанию `backend/runs.sqlite3`). При необходимости задайте оба пути переменными окружения. База создаётся при первом успешном прогнозе. В Docker Compose погодный кэш монтируется из `data/weather/ecmwf_ifs/`, а SQLite хранится в именованном томе `runs_data`.

Прогнозное ядро подключено через `forecasting/runner.py` с синхронной функцией:

```python
def run_forecast(
    turbine_id: str,
    issued_at: datetime,  # timezone-aware UTC
    horizon_hours: int,     # 24 или 48
) -> dict:
    ...
```

Функция возвращает словарь с полями `input_data_cutoff_at`, `weather_source`, `weather_run_id`, `weather_run_initialized_at`, `weather_run_usable_after_at`, `weather_actual_publication_at`, `weather_run_issued_at`, `model_version` и `points`. `weather_run_issued_at` — прежнее имя времени инициализации, сохранённое для совместимости; фактическая публикация в архиве неизвестна (`null`). Каждая точка содержит `time` и `normalized_power`. Все ненулевые времена должны быть с часовым поясом; `points` — ровно 24 или 48 последовательных часов после `issued_at`. Backend сам назначает `run_id`, проверяет границы и сериализует UTC как `Z`. `issued_at` в API должен соответствовать началу часа по UTC, иначе ответ 422. Формат внешнего API — `shared/API.md`.

Если источник временно недоступен, функция может бросить `ConnectionError`, `TimeoutError` или `OSError`: API вернёт 503. Некорректный результат не сохраняется и даст 502. Если модуль ядра отсутствует, API возвращает 501. Не возвращайте заготовленный прогноз вместо ошибки.

Проверка:

```bash
python -m unittest discover -s backend/tests -v
```

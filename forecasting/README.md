# Baseline forecasting

This folder contains a reproducible 24/48-hour wind-power baseline for both turbines. It uses archived **individual** ECMWF IFS forecast runs from [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api), rather than future observed weather or a stitched historical weather series. The requested coordinates come from `forecasting/sites.py`; at 9 km weather resolution, both sites map to the same archive grid cell (43.620384, 78.478910).

Weather data: ECMWF IFS via Open-Meteo, [CC BY 4.0 attribution terms](https://open-meteo.com/en/terms). Cached API responses retain the request URL and the original values. Derived training examples use the API's `wind_speed_unit=ms` output and exclude missing power hours.

## Build data, model, and chronological backtest

Run from the repository root with Python 3.11+:

```bash
python -m forecasting.train_baseline --csv-utc-offset +05:00
python -m unittest discover -s forecasting/tests -v
python -m forecasting.forecast turbine_1 2026-02-01T12:00:00Z 48
```

The `+05:00` offset is an explicit working assumption supplied by the user. The CSV itself does not declare a timezone, and the organizers have not confirmed it. Never silently infer the offset from the turbine coordinates.

The training command writes:

- `data/processed/hourly_turbine_*.csv`: complete hourly grid, sample counts, and means; incomplete and empty hours remain visible and are excluded from model fitting/scoring.
- `data/weather/ecmwf_ifs/*.json`: exact requested forecast runs, original API response, source URL, nominal cycle time, and conservative usability time.
- `data/processed/historical_launches.json`: one record per turbine, horizon, and historical launch, including the weather run ID, nominal issue/cycle time, and conservative usability time.
- `forecasting/artifacts/baseline_model.json`: per-turbine 0.5 m/s wind-bin power curves, included by the backend Docker build.
- `data/processed/backtest_report.json`: data-quality counts and December/January MAE for 24/48 hours, with constant-mean and last-day persistence comparisons.

The model is trained on archived **forecast wind at 100 m**, matched to observed normalized power by time. November 2025 trains the December fold; November–December train the January fold. The final artifact uses all available examples through January 2026 for February forecasts. No actual February power is included, so February error cannot be measured from this repository.

## Time and weather provenance

The ten-minute CSV timestamp has an unknown interval convention. The implementation groups labels `HH:00` through `HH:50` into an hour ending at `HH+1:00`; this is an explicit approximation. It neither fills gaps nor treats partial hours as complete.

Open-Meteo's `run` parameter is the **model initialization time**, not the exact time the forecast appeared on its API. The archive does not expose historical publication timestamps. [Open-Meteo documents a typical 4–6 hour computation delay](https://open-meteo.com/en/docs/single-runs-api), and [ECMWF publishes a dissemination schedule](https://confluence.ecmwf.int/pages/viewpage.action?pageId=621039623). This baseline conservatively allows a run only 12 hours after initialization. `weather_run_issued_at` in the public result is the nominal ECMWF cycle time, **not a verified API publication timestamp**. The historical-launch manifest stores `weather_run_usable_after_at` separately and leaves `weather_actual_publication_at` null. If exact publication times become available, replace the conservative rule and populate that field.

The height of wind measurements in the turbine CSV is unknown. The 100 m forecast wind may differ from turbine measurements, and the 9 km weather grid cannot represent local terrain perfectly. These uncertainties are visible in the report rather than hidden as confirmed facts.

## Backend handoff

`forecasting.runner.run_forecast(turbine_id, issued_at, horizon_hours)` is the entry point expected by the current backend adapter. It returns the required forecast fields with 24 or 48 hourly points, model version, input-data cutoff, and weather run ID/time. `forecasting.forecast.forecast` also provides a standalone full result and CLI. Missing or incompatible model/weather raises `ForecastUnavailable` (`OSError`), which backend maps to HTTP 503. It never returns placeholder power values. This folder does not modify backend or shared API files.

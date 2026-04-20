# SPX Prophet

SPX Prophet is a production-grade Streamlit trading application built around a
clean Python core. The price-engine, pivot logic, projections, scenarios,
confirmation checks, and confluence scoring remain testable independently of
the frontend.

## Requirements

- Python 3.11+
- `yfinance`
- `pandas`
- `pytz`
- `numpy`
- `streamlit`
- `plotly`

## Project Layout

```text
.
|-- app.py
|-- core
|   |-- __init__.py
|   |-- confluence.py
|   |-- data_fetch.py
|   |-- pivots.py
|   |-- projections.py
|   |-- scenarios.py
|   |-- time_utils.py
|   `-- trade_log.py
|-- requirements.txt
|-- README.md
`-- tests
    `-- test_validation_case.py
```

## Core Modules

- `app.py`: Streamlit UI with three tabs, custom styling, spatial ladder, and persistent journal.
- `core/time_utils.py`: Central Time normalization, market-hour rules, and session windows.
- `core/data_fetch.py`: `yfinance` retrieval for ES hourly candles and SPX 8:30 confirmation candles.
- `core/pivots.py`: Last pivot detection, exact green/red anchor resolution, and NY session wick anchors.
- `core/projections.py`: Fixed-rate six-line projection math using `1.04` per candle.
- `core/scenarios.py`: Exact seven-scenario logic, 8:30 confirmation, sit-out filters, strikes, and trade cards.
- `core/confluence.py`: Five-factor confluence scoring from Asian, London, data reaction, opening drive, and clustering.
- `core/trade_log.py`: Persistent JSON trade log, journals, exports, and performance metrics.

## Run The Validation Test

```bash
python -m unittest discover -s tests -v
```

## Run The App

```bash
streamlit run app.py
```

## Notes

- Candle counting is modeled on hourly candle-close timestamps in Central Time.
- The four pivot-price anchors project from the pivot timestamp, which matches the Friday-to-Monday validation case.
- The full-session wick lines keep their own anchor timestamps.
- SPX values on the NY tab are shown in SPX terms by subtracting the manual ES-SPX offset from ES-derived lines.

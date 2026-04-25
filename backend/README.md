# SPX Prophet API Bridge

This FastAPI app is the bridge between the tested Python intelligence engine and
the new Next.js production operator surface.

## Run Locally

```bash
pip install -r ../requirements.txt
uvicorn backend.main:app --reload --port 8000
```

## Endpoints

- `GET /health`
- `GET /api/operator-snapshot`

The first implementation returns a realistic mock snapshot so the production UI
can be designed without disturbing the Streamlit app. A later wiring pass should
replace `build_mock_operator_snapshot()` with an adapter around the existing SPX
Prophet live signal package.

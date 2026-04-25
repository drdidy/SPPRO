# SPX Prophet Operator Surface

This is the new production-facing web app for SPX Prophet. It is intentionally
separate from Streamlit so the operator UI can use premium layout, animation,
responsive design, and PWA install behavior.

## Run Locally

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Connect To The Python Bridge

Start the backend:

```bash
uvicorn backend.main:app --reload --port 8000
```

Then create `frontend/.env.local`:

```bash
SPX_PROPHET_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

If the backend is unavailable, the UI falls back to the local mock snapshot so
the page remains usable during design work.

## First Production Surface

The initial screen includes:

- Decision Hero
- Market Context
- Primary and Alternate execution cards
- Nearby strike ladders
- ES polarity structure map

Streamlit remains the Edge Lab / research console during the migration.

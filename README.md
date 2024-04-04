
# Steps

1. Start the Codespace or Dev Container (which contains a local PostgreSQL container).

1. Install the FastAPI app in editable mode:

```bash
python3 -m pip install -e src
```

1. Run the FastAPI app

```bash
python3 -m uvicorn fastapi_app:app --reload --port=8000
```

1. Run the frontend

```bash
cd src/frontend
npm run dev
```

1. Open the browser at `http://localhost:5173/` and you will see the frontend.
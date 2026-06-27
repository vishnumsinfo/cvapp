# CV Screening Software — Claude-powered

End-to-end resume screening: FastAPI backend + Claude scoring engine + React/Tailwind HR dashboard.

## Architecture
```
cv-screener/
├── requirements.txt
├── database.py            # SQLite + SQLAlchemy session
├── models.py              # Job, Candidate, Evaluation tables
├── schemas.py             # Pydantic I/O + Claude output schema (Scorecard)
├── main.py                # FastAPI: /jobs /upload /candidates /evaluate /export
├── services/
│   ├── parser.py          # PDF (pdfplumber) + DOCX text extraction
│   └── claude_client.py   # Anthropic integration, system prompt, few-shot, validation
└── frontend/
    └── Dashboard.jsx      # React + Tailwind recruiter dashboard
```

## Backend setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
# optional: export CLAUDE_MODEL=claude-sonnet-4-6
uvicorn main:app --reload --port 8000
```
API docs at http://localhost:8000/docs

## Frontend setup (Vite + React + Tailwind)
```bash
npm create vite@latest hr-ui -- --template react
cd hr-ui && npm install
npm install -D tailwindcss postcss autoprefixer && npx tailwindcss init -p
# add Tailwind directives to src/index.css, set content to ["./src/**/*.{js,jsx}"]
# copy frontend/Dashboard.jsx into src/ and render it from App.jsx
echo "VITE_API_URL=http://localhost:8000" > .env
npm run dev
```

## How it works
1. Create a Job (title, description, required skills, min experience).
2. Drag-drop PDF/DOCX resumes — each is saved and queued as a FastAPI **background task**.
3. The worker extracts clean text (token-saving), then calls Claude with a strict
   JSON-only, **bias-free** system prompt + one few-shot example, and an assistant
   prefill (`{`) that forces valid JSON. Output is validated against the `Scorecard`
   Pydantic schema with retries + exponential backoff.
4. The dashboard polls for results, lets you filter/sort/compare, drill into a
   per-candidate scorecard, and export a ranked CSV shortlist.

## Error handling
- Unsupported file types are rejected per-file (upload continues for the rest).
- Empty/unreadable documents are marked `error` with a message on the record.
- API timeouts/rate limits → retried with backoff; persistent failure → candidate `error`.
- Malformed model output → schema validation retry with a corrective nudge.

## Fairness
The system prompt instructs Claude to score only on job-relevant evidence and to ignore
name, gender, age, ethnicity, and other protected/irrelevant attributes. Red flags must be
evidence-based and job-relevant. This reduces—but does not eliminate—bias; keep a human in
the loop and audit outputs periodically.

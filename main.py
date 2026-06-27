"""FastAPI application: jobs, bulk upload, candidates, evaluate, CSV export."""
import csv
import io
import os
import uuid

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, BackgroundTasks, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from database import get_db, init_db, SessionLocal
import models
import schemas
from services import parser
from services import ingest
from services.claude_client import evaluate_resume

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="CV Screener", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


# Also create tables at import time so non-lifespan contexts (tests, some ASGI
# servers) have a ready schema. Idempotent.
init_db()


# ---------------- Jobs ----------------
@app.post("/jobs", response_model=schemas.JobOut)
def create_job(job: schemas.JobCreate, db: Session = Depends(get_db)):
    obj = models.Job(**job.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj


@app.get("/jobs", response_model=list[schemas.JobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(models.Job).order_by(models.Job.created_at.desc()).all()


@app.get("/jobs/{job_id}", response_model=schemas.JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    obj = db.get(models.Job, job_id)
    if not obj:
        raise HTTPException(404, "Job not found")
    return obj


# ---------------- Upload + background processing ----------------
def _process_candidate(candidate_id: int):
    """Runs in background: extract text -> Claude -> persist evaluation."""
    db = SessionLocal()
    try:
        cand = db.get(models.Candidate, candidate_id)
        if not cand:
            return
        cand.status = "processing"; db.commit()

        text = parser.extract_text(cand.file_path)
        if not text.strip():
            raise ValueError("No extractable text in document")
        cand.raw_text = text

        job = db.get(models.Job, cand.job_id)
        card = evaluate_resume(job, text)

        # denormalize contact for fast listing; keep applicant-typed values
        # if Claude's parse came back blank (landing-page submissions seed these)
        cand.full_name = card.parsed.contact.full_name or cand.full_name
        cand.email = card.parsed.contact.email or cand.email
        cand.phone = card.parsed.contact.phone or cand.phone
        cand.parsed_data = card.parsed.model_dump()

        ev = models.Evaluation(
            candidate_id=cand.id,
            match_score=card.match_score,
            skill_alignment=card.skill_alignment,
            experience_depth=card.experience_depth,
            relevancy=card.relevancy,
            fit_analysis=card.fit_analysis,
            missing_critical_skills=card.missing_critical_skills,
            red_flags=card.red_flags,
            interview_questions=card.interview_questions,
            salary=card.salary.model_dump(),
            recommendation=card.recommendation,
        )
        db.add(ev)
        cand.status = "done"; cand.error_message = ""
        db.commit()
    except Exception as e:  # noqa: BLE001 - capture any failure on the record
        db.rollback()
        cand = db.get(models.Candidate, candidate_id)
        if cand:
            cand.status = "error"; cand.error_message = str(e)[:1000]
            db.commit()
    finally:
        db.close()


@app.post("/upload")
async def upload_resumes(
    background: BackgroundTasks,
    job_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    if not db.get(models.Job, job_id):
        raise HTTPException(404, "Job not found")

    created = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in (".pdf", ".docx", ".doc"):
            created.append({"file": f.filename, "error": "unsupported format"})
            continue

        safe = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(UPLOAD_DIR, safe)
        try:
            with open(path, "wb") as out:
                out.write(await f.read())
        except Exception as e:  # noqa: BLE001
            created.append({"file": f.filename, "error": f"save failed: {e}"})
            continue

        cand = models.Candidate(
            job_id=job_id, file_name=f.filename or safe,
            file_path=path, status="pending",
        )
        db.add(cand); db.commit(); db.refresh(cand)
        background.add_task(_process_candidate, cand.id)
        created.append({"file": f.filename, "candidate_id": cand.id})

    return {"queued": created}


# ---------------- Candidates ----------------
@app.get("/candidates", response_model=list[schemas.CandidateOut])
def list_candidates(job_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Candidate)
    if job_id is not None:
        q = q.filter(models.Candidate.job_id == job_id)
    return q.order_by(models.Candidate.created_at.desc()).all()


@app.get("/candidates/{cid}")
def get_candidate(cid: int, db: Session = Depends(get_db)):
    cand = db.get(models.Candidate, cid)
    if not cand:
        raise HTTPException(404, "Candidate not found")
    out = schemas.CandidateOut.model_validate(cand).model_dump()
    out["parsed_data"] = cand.parsed_data
    return out


@app.post("/evaluate/{cid}")
def reevaluate(cid: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    cand = db.get(models.Candidate, cid)
    if not cand:
        raise HTTPException(404, "Candidate not found")
    if cand.evaluation:
        db.delete(cand.evaluation); db.commit()
    cand.status = "pending"; db.commit()
    background.add_task(_process_candidate, cand.id)
    return {"status": "queued", "candidate_id": cid}


# ---------------- CV download ----------------
@app.get("/candidates/{cid}/download")
def download_cv(cid: int, db: Session = Depends(get_db)):
    cand = db.get(models.Candidate, cid)
    if not cand or not os.path.exists(cand.file_path):
        raise HTTPException(404, "CV file not found")
    return FileResponse(cand.file_path, filename=cand.file_name,
                        media_type="application/octet-stream")


# ---------------- Channel ingestion ----------------
def _register_and_queue(db, background, job_id, file_name, file_path, source):
    cand = models.Candidate(
        job_id=job_id, file_name=file_name, file_path=file_path,
        status="pending", source=source,
    )
    db.add(cand); db.commit(); db.refresh(cand)
    background.add_task(_process_candidate, cand.id)
    return cand.id


@app.post("/ingest/url")
def ingest_url(
    background: BackgroundTasks,
    job_id: int, cv_url: str, file_name: str | None = None,
    db: Session = Depends(get_db),
):
    """Pull a single CV from a direct https file URL (e.g. a Meta lead link)."""
    if not db.get(models.Job, job_id):
        raise HTTPException(404, "Job not found")
    try:
        name, path = ingest.fetch_cv_from_url(cv_url, file_name)
    except ingest.IngestError as e:
        raise HTTPException(400, str(e))
    cid = _register_and_queue(db, background, job_id, name, path, "portal")
    return {"queued": [{"candidate_id": cid, "file": name}]}


@app.post("/ingest/meta")
def ingest_meta(
    background: BackgroundTasks,
    job_id: int, form_id: str,
    db: Session = Depends(get_db),
):
    """Pull applicants from a Meta lead-gen form. CV links (if present) are fetched."""
    if not db.get(models.Job, job_id):
        raise HTTPException(404, "Job not found")
    token = os.getenv("META_ACCESS_TOKEN", "")
    try:
        leads = ingest.pull_meta_leads(form_id, token)
    except ingest.IngestError as e:
        raise HTTPException(400, str(e))

    queued, skipped = [], []
    for lead in leads:
        cv_url = lead.get("cv_url")
        if not cv_url:
            skipped.append({"lead": lead.get("email"), "reason": "no CV link"})
            continue
        try:
            name, path = ingest.fetch_cv_from_url(cv_url)
        except ingest.IngestError as e:
            skipped.append({"lead": lead.get("email"), "reason": str(e)})
            continue
        cid = _register_and_queue(db, background, job_id, name, path, "meta_ads")
        queued.append({"candidate_id": cid, "lead": lead.get("email")})
    return {"queued": queued, "skipped": skipped}


@app.post("/ingest/portal")
def ingest_portal(
    background: BackgroundTasks,
    job_id: int, provider: str, job_ref: str,
    db: Session = Depends(get_db),
):
    """Pull applicants from an official employer portal API (Naukri/Indeed/LinkedIn).

    Requires the provider's paid employer account + API key. Scraping is not supported.
    """
    if not db.get(models.Job, job_id):
        raise HTTPException(404, "Job not found")
    try:
        rows = ingest.pull_portal_applicants(provider, job_ref)
    except ingest.IngestError as e:
        raise HTTPException(400, str(e))

    queued = []
    for row in rows:
        cv_url = row.get("cv_url")
        if not cv_url:
            continue
        try:
            name, path = ingest.fetch_cv_from_url(cv_url)
        except ingest.IngestError:
            continue
        cid = _register_and_queue(db, background, job_id, name, path, "portal")
        queued.append({"candidate_id": cid, "applicant": row.get("email")})
    return {"queued": queued}


# ---------------- Public landing page (Meta ad funnel target) ----------------
_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "apply.html")


@app.get("/apply/{job_id}", response_class=HTMLResponse)
def apply_page(job_id: int, db: Session = Depends(get_db)):
    """Public, branded application page. Point your Meta ad / website link here."""
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        html = f.read()

    skills_html = "".join(
        f'<span class="chip">{s}</span>' for s in (job.required_skills or [])
    )
    repl = {
        "__JOB_ID__": str(job.id),
        "__JOB_TITLE__": job.title,
        "__JOB_LOCATION__": job.location or "India",
        "__JOB_DESC__": (job.description or "")[:400],
        "__JOB_SKILLS__": skills_html,
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return HTMLResponse(html)


@app.post("/apply")
async def public_apply(
    background: BackgroundTasks,
    job_id: int = Form(...),
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    cv: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Public submission from the landing page. Saves CV + queues for screening."""
    if not db.get(models.Job, job_id):
        raise HTTPException(404, "Job not found")

    ext = os.path.splitext(cv.filename or "")[1].lower()
    if ext not in (".pdf", ".docx", ".doc"):
        raise HTTPException(400, "Please upload a PDF or DOCX file")

    data = await cv.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "File exceeds 10 MB")

    safe = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, safe)
    with open(path, "wb") as out:
        out.write(data)

    cand = models.Candidate(
        job_id=job_id, file_name=cv.filename or safe, file_path=path,
        status="pending", source="meta_ads",
        # seed applicant-provided contact; Claude parse may refine
        full_name=full_name, email=email, phone=phone,
    )
    db.add(cand); db.commit(); db.refresh(cand)
    background.add_task(_process_candidate, cand.id)
    return {"status": "received", "candidate_id": cand.id}


# ---------------- CSV shortlist export ----------------
@app.get("/export")
def export_csv(job_id: int, min_score: float = 0.0, db: Session = Depends(get_db)):
    cands = (
        db.query(models.Candidate)
        .filter(models.Candidate.job_id == job_id,
                models.Candidate.status == "done")
        .all()
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Email", "Phone", "Match Score", "Recommendation",
                "Rec. Offer", "Market Median", "Within Budget",
                "Negotiation", "Missing Skills", "Red Flags", "Source", "File"])
    rows = []
    for c in cands:
        ev = c.evaluation
        if not ev or ev.match_score < min_score:
            continue
        sal = ev.salary or {}
        rows.append((ev.match_score, [
            c.full_name, c.email, c.phone, ev.match_score, ev.recommendation,
            sal.get("recommended_offer", ""), sal.get("market_median", ""),
            sal.get("within_budget", ""), sal.get("negotiation_strategy", ""),
            "; ".join(ev.missing_critical_skills or []),
            "; ".join(ev.red_flags or []), c.source, c.file_name,
        ]))
    for _, row in sorted(rows, key=lambda x: x[0], reverse=True):
        w.writerow(row)

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=shortlist_job{job_id}.csv"},
    )

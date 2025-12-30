import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Review, Submission
from .services.ocr import extract_receipt_data

app = FastAPI(title="Receipt Reviewer")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RECEIPT_DIR = DATA_DIR / "receipts"
RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
TESSERACT_CMD = os.getenv("TESSERACT_CMD")

app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
app.mount("/receipts", StaticFiles(directory=RECEIPT_DIR), name="receipts")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("upload.html", {"request": request, "default_applicant": "XYY"})


@app.post("/submissions")
async def create_submission(
    request: Request,
    applicant: str = Form("XYY"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    saved_path = save_upload(file)
    extracted = extract_receipt_data(saved_path, tesseract_cmd=TESSERACT_CMD)
    public_path = Path("receipts") / saved_path.name

    submission = Submission(
        applicant=applicant or "XYY",
        date=extracted.get("date"),
        recipient=extracted.get("recipient"),
        amount=extracted.get("amount"),
        registration_number=extracted.get("registration_number"),
        image_path=str(public_path),
        ocr_text=extracted.get("ocr_text"),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    response = RedirectResponse(url="/submissions?created=1", status_code=303)
    return response


@app.get("/submissions", response_class=HTMLResponse)
def list_submissions(request: Request, created: int | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    submissions = db.query(Submission).order_by(Submission.created_at.desc()).all()
    return templates.TemplateResponse(
        "submissions.html",
        {
            "request": request,
            "submissions": submissions,
            "created": created,
        },
    )


@app.get("/approvals", response_class=HTMLResponse)
def approvals_view(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    submissions = db.query(Submission).order_by(Submission.created_at.desc()).all()
    latest_reviews: Dict[int, Review | None] = {}
    for submission in submissions:
        latest_reviews[submission.id] = (
            db.query(Review)
            .filter(Review.submission_id == submission.id)
            .order_by(Review.created_at.desc())
            .first()
        )
    return templates.TemplateResponse(
        "approvals.html",
        {
            "request": request,
            "submissions": submissions,
            "latest_reviews": latest_reviews,
        },
    )


@app.post("/approvals/bulk")
async def approve_bulk(
    request: Request,
    reviewer: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form = await request.form()
    actions: Dict[int, Dict[str, Any]] = {}

    for key, value in form.items():
        if key.startswith("status_"):
            submission_id = int(key.split("_")[1])
            actions[submission_id] = {"status": value}
        if key.startswith("note_"):
            submission_id = int(key.split("_")[1])
            actions.setdefault(submission_id, {})["note"] = value

    for submission_id, payload in actions.items():
        status = payload.get("status")
        note = payload.get("note", "")
        if status not in {"OK", "NG"}:
            continue
        review = Review(
            submission_id=submission_id,
            reviewer=reviewer,
            status=status,
            note=note,
            created_at=datetime.utcnow(),
        )
        db.add(review)

    db.commit()

    response = RedirectResponse(url="/approvals?saved=1", status_code=303)
    return response


def save_upload(file: UploadFile) -> Path:
    extension = Path(file.filename).suffix
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    filename = f"receipt_{timestamp}{extension}"
    path = RECEIPT_DIR / filename

    content = file.file.read()
    path.write_bytes(content)
    return path


@app.get("/health", tags=["health"])
def health() -> Dict[str, str]:
    return {"status": "ok"}

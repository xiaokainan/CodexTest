import csv
import io
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import hashlib
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional
from statistics import mean

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .database import Base, engine, get_db, SessionLocal
from .models import Flow, FlowRequest, FlowRequestApproval, FlowStep, Review, Submission, User
from .services.ocr import extract_receipt_data

app = FastAPI(title="Receipt Reviewer")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", secrets.token_hex(16)))

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RECEIPT_DIR = DATA_DIR / "receipts"
RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"
TESSERACT_CMD = os.getenv("TESSERACT_CMD")

app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
app.mount("/receipts", StaticFiles(directory=RECEIPT_DIR), name="receipts")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

logger = logging.getLogger("receipt_app")
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    return hash_password(password, salt) == password_hash


def get_audit_context(request: Request, user: Optional[User]) -> Dict[str, str | int | None]:
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "-")
    return {
        "user": user.username if user else None,
        "user_name": user.full_name if user else None,
        "role": user.role if user else None,
        "ip": client_host,
        "agent": user_agent,
    }


def log_action(action: str, request: Request, user: Optional[User], **details: Any) -> None:
    context = get_audit_context(request, user)
    merged = {**context, **details}
    detail_str = " ".join(f"{key}={value}" for key, value in merged.items())
    logger.info("%s %s", action, detail_str)


def send_email_notification(subject: str, body: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM") or smtp_user or "alllink@local"
    smtp_to = os.getenv("SMTP_TO")
    if not smtp_host or not smtp_to:
        logger.info("notification_skipped reason=missing_smtp_config")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = smtp_to
    message.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            if os.getenv("SMTP_STARTTLS", "1") == "1":
                smtp.starttls()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("notification_failed error=%s", exc)


def get_current_user(request: Request, db: Optional[Session]) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id or not db:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_admin(user: Optional[User]) -> None:
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="管理者のみが利用できます")


def seed_admin_user(db: Session) -> None:
    if db.query(User).filter(User.username == "admin").first():
        return
    default_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    admin_user = User(
        username="admin",
        full_name="System Admin",
        role="admin",
        password_hash=hash_password(default_password, "admin"),
    )
    db.add(admin_user)
    db.commit()


def seed_default_flow(db: Session) -> Flow:
    existing = db.query(Flow).filter(Flow.name == "財務会計 (領収書OCR)").first()
    if existing:
        return existing
    flow = Flow(
        name="財務会計 (領収書OCR)",
        category="財務会計",
        description="既存の領収書 OCR 申請/承認フローを表すデフォルトフローです。",
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)

    default_steps = ["申請者", "経理担当", "管理者"]
    for idx, step_name in enumerate(default_steps, start=1):
        step = FlowStep(flow_id=flow.id, name=step_name, approver_role="財務", order=idx)
        db.add(step)
    db.commit()
    return flow


def get_flow_or_404(flow_id: int, db: Session) -> Flow:
    flow = db.query(Flow).filter(Flow.id == flow_id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="フローが見つかりません")
    return flow


def get_next_step(flow: Flow, approvals: List[FlowRequestApproval]) -> Optional[FlowStep]:
    if not flow.steps:
        return None
    taken_orders = {approval.step_order for approval in approvals if approval.step_order is not None}
    for step in flow.steps:
        if step.order not in taken_orders:
            return step
    return None


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_admin_user(db)
        seed_default_flow(db)


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request) -> HTMLResponse:
    user = get_current_user(request, None)
    return templates.TemplateResponse(
        "upload.html",
        {"request": request, "default_applicant": user.full_name if user else "XYY", "user": user},
    )


@app.post("/submissions")
async def create_submission(
    request: Request,
    applicant: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="ログインしてください")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    saved_path = save_upload(file)
    extracted = extract_receipt_data(saved_path, tesseract_cmd=TESSERACT_CMD)
    public_path = Path("receipts") / saved_path.name

    submission = Submission(
        applicant=applicant or user.full_name or "XYY",
        applicant_login=user.username,
        user_id=user.id,
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

    log_action(
        "submission_created",
        request,
        user,
        submission_id=submission.id,
        applicant=submission.applicant,
        amount=submission.amount,
        recipient=submission.recipient,
    )
    send_email_notification(
        "AllLink 申請登録通知",
        "\n".join(
            [
                f"申請ID: {submission.id}",
                f"申請者: {submission.applicant}",
                f"日付: {submission.date or '-'}",
                f"宛先: {submission.recipient or '-'}",
                f"金額: {submission.amount or '-'}",
                f"登録番号: {submission.registration_number or '-'}",
            ]
        ),
    )

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
            "user": get_current_user(request, db),
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = get_current_user(request, db)
    submissions = db.query(Submission).order_by(Submission.created_at.desc()).all()
    latest_reviews: Dict[int, Review | None] = {}
    for submission in submissions:
        latest_reviews[submission.id] = (
            db.query(Review)
            .filter(Review.submission_id == submission.id)
            .order_by(Review.created_at.desc())
            .first()
        )

    reviewed = [review for review in latest_reviews.values() if review]
    ok_count = sum(1 for review in reviewed if review.status == "OK")
    ng_count = sum(1 for review in reviewed if review.status == "NG")
    approval_rate = round((ok_count / len(reviewed)) * 100, 1) if reviewed else None

    processing_times = []
    for submission in submissions:
        review = latest_reviews.get(submission.id)
        if review:
            processing_times.append((review.created_at - submission.created_at).total_seconds() / 3600)
    avg_processing_hours = round(mean(processing_times), 2) if processing_times else None

    flow_requests = db.query(FlowRequest).order_by(FlowRequest.created_at.desc()).all()
    flow_approved = sum(1 for record in flow_requests if record.status == "approved")
    flow_rejected = sum(1 for record in flow_requests if record.status == "rejected")
    flow_pending = sum(1 for record in flow_requests if record.status == "pending")
    flow_reviewed_total = flow_approved + flow_rejected
    flow_approval_rate = round((flow_approved / flow_reviewed_total) * 100, 1) if flow_reviewed_total else None
    flow_processing_times = []
    for record in flow_requests:
        latest = (
            db.query(FlowRequestApproval)
            .filter(FlowRequestApproval.request_id == record.id)
            .order_by(FlowRequestApproval.created_at.desc())
            .first()
        )
        if latest and record.status in {"approved", "rejected"}:
            flow_processing_times.append((latest.created_at - record.created_at).total_seconds() / 3600)
    flow_avg_processing_hours = round(mean(flow_processing_times), 2) if flow_processing_times else None

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "submission_total": len(submissions),
            "submission_ok": ok_count,
            "submission_ng": ng_count,
            "submission_approval_rate": approval_rate,
            "submission_avg_processing_hours": avg_processing_hours,
            "flow_total": len(flow_requests),
            "flow_approved": flow_approved,
            "flow_rejected": flow_rejected,
            "flow_pending": flow_pending,
            "flow_approval_rate": flow_approval_rate,
            "flow_avg_processing_hours": flow_avg_processing_hours,
        },
    )


@app.get("/api/submissions")
def api_submissions(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    submissions = db.query(Submission).order_by(Submission.created_at.desc()).all()
    return [
        {
            "id": submission.id,
            "applicant": submission.applicant,
            "applicant_login": submission.applicant_login,
            "date": submission.date,
            "recipient": submission.recipient,
            "amount": submission.amount,
            "registration_number": submission.registration_number,
            "image_path": submission.image_path,
            "created_at": submission.created_at.isoformat(),
        }
        for submission in submissions
    ]


@app.get("/api/flows/{flow_id}/requests")
def api_flow_requests(flow_id: int, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    flow = get_flow_or_404(flow_id, db)
    requests = (
        db.query(FlowRequest)
        .filter(FlowRequest.flow_id == flow.id)
        .order_by(FlowRequest.created_at.desc())
        .all()
    )
    return [
        {
            "id": record.id,
            "flow_id": record.flow_id,
            "title": record.title,
            "description": record.description,
            "applicant": record.applicant,
            "applicant_login": record.applicant_login,
            "status": record.status,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
        for record in requests
    ]


def build_submission_csv(submissions: List[Submission]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "申請者", "ログインID", "日付", "宛先", "金額", "登録番号", "登録日時", "画像パス"])
    for submission in submissions:
        writer.writerow(
            [
                submission.id,
                submission.applicant,
                submission.applicant_login or "",
                submission.date or "",
                submission.recipient or "",
                submission.amount or "",
                submission.registration_number or "",
                submission.created_at.strftime("%Y-%m-%d %H:%M"),
                submission.image_path,
            ]
        )
    return output.getvalue()


def sanitize_pdf_text(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def build_pdf_document(lines: List[str]) -> bytes:
    content_lines = ["BT", "/F1 10 Tf", "50 780 Td"]
    for idx, line in enumerate(lines):
        safe = sanitize_pdf_text(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"({safe}) Tj")
        if idx < len(lines) - 1:
            content_lines.append("T*")
    content_lines.append("ET")
    content = "\n".join(content_lines)
    content_bytes = content.encode("latin-1")

    objects: List[bytes] = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append(
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
    )
    objects.append(
        b"4 0 obj << /Length "
        + str(len(content_bytes)).encode("ascii")
        + b" >> stream\n"
        + content_bytes
        + b"\nendstream endobj\n"
    )
    objects.append(b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")

    result = io.BytesIO()
    result.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(result.tell())
        result.write(obj)
    xref_start = result.tell()
    result.write(b"xref\n")
    result.write(f"0 {len(offsets)}\n".encode("ascii"))
    result.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.write(b"trailer << /Size ")
    result.write(str(len(offsets)).encode("ascii"))
    result.write(b" /Root 1 0 R >>\nstartxref\n")
    result.write(str(xref_start).encode("ascii"))
    result.write(b"\n%%EOF")
    return result.getvalue()


def build_submission_pdf(submissions: List[Submission]) -> bytes:
    lines = ["AllLink Submissions Export"]
    for submission in submissions:
        lines.extend(
            [
                f"ID: {submission.id} 申請者: {submission.applicant} ({submission.applicant_login or '-'})",
                f"日付: {submission.date or '-'} 宛先: {submission.recipient or '-'} 金額: {submission.amount or '-'} 登録番号: {submission.registration_number or '-'}",
                f"登録日時: {submission.created_at.strftime('%Y-%m-%d %H:%M')} 画像: {submission.image_path}",
                "",
            ]
        )
    return build_pdf_document(lines)


@app.get("/exports/submissions")
def export_submissions(format: str = "csv", db: Session = Depends(get_db)) -> StreamingResponse:
    submissions = db.query(Submission).order_by(Submission.created_at.desc()).all()
    if format == "pdf":
        pdf_bytes = build_submission_pdf(submissions)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=submissions.pdf"},
        )
    csv_data = build_submission_csv(submissions)
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=submissions.csv"},
    )


def build_flow_request_csv(records: List[FlowRequest]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "件名", "申請者", "ログインID", "状態", "申請日時", "更新日時"])
    for record in records:
        writer.writerow(
            [
                record.id,
                record.title,
                record.applicant,
                record.applicant_login or "",
                record.status,
                record.created_at.strftime("%Y-%m-%d %H:%M"),
                record.updated_at.strftime("%Y-%m-%d %H:%M") if record.updated_at else "",
            ]
        )
    return output.getvalue()


def build_flow_request_pdf(records: List[FlowRequest], flow: Flow) -> bytes:
    lines = [f"AllLink Flow Export: {flow.name}"]
    for record in records:
        lines.extend(
            [
                f"ID: {record.id} 件名: {record.title}",
                f"申請者: {record.applicant} ({record.applicant_login or '-'}) 状態: {record.status}",
                f"申請日時: {record.created_at.strftime('%Y-%m-%d %H:%M')} 更新日時: {record.updated_at.strftime('%Y-%m-%d %H:%M') if record.updated_at else '-'}",
                "",
            ]
        )
    return build_pdf_document(lines)


@app.get("/exports/flows/{flow_id}")
def export_flow_requests(flow_id: int, format: str = "csv", db: Session = Depends(get_db)) -> StreamingResponse:
    flow = get_flow_or_404(flow_id, db)
    records = (
        db.query(FlowRequest)
        .filter(FlowRequest.flow_id == flow.id)
        .order_by(FlowRequest.created_at.desc())
        .all()
    )
    if format == "pdf":
        pdf_bytes = build_flow_request_pdf(records, flow)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=flow_{flow.id}.pdf"},
        )
    csv_data = build_flow_request_csv(records)
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=flow_{flow.id}.csv"},
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
            "user": get_current_user(request, db),
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
    log_action("approval_recorded", request, get_current_user(request, db), reviewer=reviewer, actions=actions)
    send_email_notification(
        "AllLink 承認通知",
        "\n".join(
            [
                f"承認者: {reviewer}",
                f"対象件数: {len(actions)}",
                f"申請ID一覧: {', '.join(str(item) for item in actions.keys())}",
            ]
        ),
    )

    response = RedirectResponse(url="/approvals?saved=1", status_code=303)
    return response


@app.get("/submissions/{submission_id}", response_class=HTMLResponse)
def submission_detail(submission_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="申請が見つかりません")
    latest_review = (
        db.query(Review)
        .filter(Review.submission_id == submission.id)
        .order_by(Review.created_at.desc())
        .first()
    )
    return templates.TemplateResponse(
        "submission_detail.html",
        {"request": request, "submission": submission, "latest_review": latest_review, "user": get_current_user(request, db)},
    )


@app.get("/auth/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/auth/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)) -> RedirectResponse:
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.username, user.password_hash):
        log_action("login_failed", request, user, username=username)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "ユーザー名またはパスワードが正しくありません"},
            status_code=401,
        )
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["full_name"] = user.full_name
    request.session["role"] = user.role
    log_action("login_success", request, user)
    return RedirectResponse(url="/", status_code=303)


@app.post("/auth/logout")
async def logout(request: Request) -> RedirectResponse:
    user = get_current_user(request, None)
    log_action("logout", request, user)
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/auth/register", response_class=HTMLResponse)
def register_form(request: Request, created: int | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    user = get_current_user(request, db)
    require_admin(user)
    return templates.TemplateResponse(
        "register.html", {"request": request, "error": None, "user": user, "created": created}
    )


@app.post("/auth/register")
async def register_user(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    current_user = get_current_user(request, db)
    require_admin(current_user)

    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "同じユーザー名が既に存在します", "user": current_user},
            status_code=400,
        )
    password_hash = hash_password(password, username)
    new_user = User(username=username, full_name=full_name, password_hash=password_hash, role=role)
    db.add(new_user)
    db.commit()
    log_action(
        "user_registered",
        request,
        current_user,
        created_username=username,
        created_full_name=full_name,
        created_role=role,
    )
    return RedirectResponse(url="/auth/register?created=1", status_code=303)


@app.get("/flows", response_class=HTMLResponse)
def list_flows(request: Request, created: int | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    user = get_current_user(request, db)
    flows = db.query(Flow).order_by(Flow.created_at.desc()).all()
    flow_summaries = []
    for flow in flows:
        request_count = db.query(FlowRequest).filter(FlowRequest.flow_id == flow.id).count()
        flow_summaries.append({"flow": flow, "request_count": request_count})
    return templates.TemplateResponse(
        "flows.html",
        {"request": request, "flows": flow_summaries, "user": user, "created": created},
    )


@app.post("/flows")
async def create_flow(
    request: Request,
    name: str = Form(...),
    category: str = Form(""),
    description: str = Form(""),
    route_steps: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = get_current_user(request, db)
    require_admin(user)
    if db.query(Flow).filter(Flow.name == name.strip()).first():
        flows = db.query(Flow).order_by(Flow.created_at.desc()).all()
        flow_summaries = []
        for flow in flows:
            request_count = db.query(FlowRequest).filter(FlowRequest.flow_id == flow.id).count()
            flow_summaries.append({"flow": flow, "request_count": request_count})
        return templates.TemplateResponse(
            "flows.html",
            {
                "request": request,
                "flows": flow_summaries,
                "user": user,
                "created": None,
                "error": "同じ名前のフローが既に存在します。",
            },
            status_code=400,
        )
    flow = Flow(name=name.strip(), category=category.strip() or None, description=description.strip() or None)
    db.add(flow)
    db.commit()
    db.refresh(flow)

    steps = [line.strip() for line in route_steps.splitlines() if line.strip()]
    for idx, step_name in enumerate(steps, start=1):
        step = FlowStep(flow_id=flow.id, name=step_name, approver_role=None, order=idx)
        db.add(step)
    db.commit()

    log_action("flow_created", request, user, flow_id=flow.id, name=flow.name, steps=len(steps))
    return RedirectResponse(url="/flows?created=1", status_code=303)


@app.get("/flows/{flow_id}/requests", response_class=HTMLResponse)
def view_flow_requests(flow_id: int, request: Request, created: int | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    flow = get_flow_or_404(flow_id, db)
    user = get_current_user(request, db)
    requests = (
        db.query(FlowRequest)
        .filter(FlowRequest.flow_id == flow.id)
        .order_by(FlowRequest.created_at.desc())
        .all()
    )
    latest_approvals: Dict[int, FlowRequestApproval | None] = {}
    for record in requests:
        latest_approvals[record.id] = (
            db.query(FlowRequestApproval)
            .filter(FlowRequestApproval.request_id == record.id)
            .order_by(FlowRequestApproval.created_at.desc())
            .first()
        )

    return templates.TemplateResponse(
        "flow_requests.html",
        {
            "request": request,
            "flow": flow,
            "flow_requests": requests,
            "latest_approvals": latest_approvals,
            "user": user,
            "created": created,
        },
    )


@app.get("/flows/{flow_id}/requests/new", response_class=HTMLResponse)
def new_flow_request_form(flow_id: int, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    flow = get_flow_or_404(flow_id, db)
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="ログインしてください")
    return templates.TemplateResponse(
        "flow_request_form.html",
        {
            "request": request,
            "flow": flow,
            "user": user,
        },
    )


@app.post("/flows/{flow_id}/requests")
async def create_flow_request(
    flow_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    flow = get_flow_or_404(flow_id, db)
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="ログインしてください")
    flow_request = FlowRequest(
        flow_id=flow.id,
        title=title.strip(),
        description=description.strip() or None,
        applicant=user.full_name or user.username,
        applicant_login=user.username,
        status="pending",
    )
    db.add(flow_request)
    db.commit()
    db.refresh(flow_request)

    log_action(
        "flow_request_created",
        request,
        user,
        flow_id=flow.id,
        request_id=flow_request.id,
        title=flow_request.title,
    )
    return RedirectResponse(url=f"/flows/{flow.id}/requests?created=1", status_code=303)


@app.get("/flows/{flow_id}/approvals", response_class=HTMLResponse)
def view_flow_approvals(
    flow_id: int, request: Request, saved: int | None = None, db: Session = Depends(get_db)
) -> HTMLResponse:
    flow = get_flow_or_404(flow_id, db)
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="ログインしてください")
    flow_requests = (
        db.query(FlowRequest)
        .filter(FlowRequest.flow_id == flow.id)
        .order_by(FlowRequest.created_at.desc())
        .all()
    )
    approvals_by_request: Dict[int, List[FlowRequestApproval]] = {}
    next_steps: Dict[int, Optional[FlowStep]] = {}
    for record in flow_requests:
        approvals = (
            db.query(FlowRequestApproval)
            .filter(FlowRequestApproval.request_id == record.id)
            .order_by(FlowRequestApproval.created_at.desc())
            .all()
        )
        approvals_by_request[record.id] = approvals
        next_steps[record.id] = get_next_step(flow, approvals)

    return templates.TemplateResponse(
        "flow_approvals.html",
        {
            "request": request,
            "flow": flow,
            "flow_requests": flow_requests,
            "approvals_by_request": approvals_by_request,
            "next_steps": next_steps,
            "user": user,
            "saved": saved,
        },
    )


@app.post("/flows/{flow_id}/approvals")
async def submit_flow_approvals(
    flow_id: int,
    request: Request,
    reviewer: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    flow = get_flow_or_404(flow_id, db)
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="ログインしてください")

    form = await request.form()
    actions: Dict[int, Dict[str, Any]] = {}
    for key, value in form.items():
        if key.startswith("status_"):
            request_id = int(key.split("_")[1])
            actions[request_id] = {"status": value}
        if key.startswith("comment_"):
            request_id = int(key.split("_")[1])
            actions.setdefault(request_id, {})["comment"] = value
        if key.startswith("step_"):
            request_id = int(key.split("_")[1])
            actions.setdefault(request_id, {})["step"] = value

    for request_id, payload in actions.items():
        status = payload.get("status")
        comment = payload.get("comment", "")
        step_name = payload.get("step") or None
        if status not in {"approved", "rejected"}:
            continue

        flow_request = (
            db.query(FlowRequest)
            .filter(FlowRequest.id == request_id, FlowRequest.flow_id == flow.id)
            .first()
        )
        if not flow_request:
            continue
        step_order = None
        if step_name:
            step = (
                db.query(FlowStep)
                .filter(FlowStep.flow_id == flow.id, FlowStep.name == step_name)
                .order_by(FlowStep.order.asc())
                .first()
            )
            step_order = step.order if step else None
        approval = FlowRequestApproval(
            request_id=flow_request.id,
            step_name=step_name,
            step_order=step_order,
            actor=reviewer or (user.full_name or user.username),
            decision=status,
            comment=comment,
        )
        db.add(approval)
        flow_request.status = "approved" if status == "approved" else "rejected"

    db.commit()
    log_action(
        "flow_approval_recorded",
        request,
        user,
        flow_id=flow.id,
        actions=list(actions.keys()),
        reviewer=reviewer or user.username,
    )
    send_email_notification(
        "AllLink フロー承認通知",
        "\n".join(
            [
                f"フロー: {flow.name}",
                f"承認者: {reviewer or user.username}",
                f"対象件数: {len(actions)}",
                f"申請ID一覧: {', '.join(str(item) for item in actions.keys())}",
            ]
        ),
    )
    return RedirectResponse(url=f"/flows/{flow.id}/approvals?saved=1", status_code=303)


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

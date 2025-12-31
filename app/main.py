import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
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

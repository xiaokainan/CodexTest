import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from PIL import Image
import pytesseract

BASE_DIR = Path(__file__).parent.resolve()
DEFAULT_APPLICANT = "XYY"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = (
    os.environ.get("DATABASE_URL")
    or f"sqlite:///{(BASE_DIR / 'instance' / 'receipts.db').as_posix()}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = BASE_DIR / "uploads"

app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
(BASE_DIR / "instance").mkdir(exist_ok=True)


db = SQLAlchemy(app)


class ReceiptApplication(db.Model):
    __tablename__ = "receipt_applications"

    id = db.Column(db.Integer, primary_key=True)
    applicant_name = db.Column(db.String(50), nullable=False, default=DEFAULT_APPLICANT)
    receipt_date = db.Column(db.Date)
    recipient = db.Column(db.String(255))
    amount = db.Column(db.Numeric(12, 2))
    registration_number = db.Column(db.String(50))
    image_filename = db.Column(db.String(255), nullable=False)
    ocr_text = db.Column(db.Text)
    approval_status = db.Column(db.String(20), default="pending", nullable=False)
    approval_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def amount_display(self) -> str:
        if self.amount is None:
            return ""
        return f"{self.amount:,.2f}"

    def date_display(self) -> str:
        return self.receipt_date.strftime("%Y-%m-%d") if self.receipt_date else ""


with app.app_context():
    db.create_all()


def secure_image_filename(filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    sanitized_stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem) or "receipt"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    return f"{sanitized_stem}_{timestamp}{suffix or '.png'}"


def extract_receipt_fields(text: str) -> dict:
    date_regex = re.compile(
        r"(20\d{2}[./-](?:0?[1-9]|1[0-2])[./-](?:0?[1-9]|[12]\d|3[01]))"
    )
    amount_regex = re.compile(r"([¥\$]?\s?\d{1,3}(?:[,.]\d{3})*(?:[.,]\d{2})?)")
    registration_regex = re.compile(r"(T?\d{8,15})")

    receipt_date = None
    amount_value = None
    registration_number = None
    recipient = None

    if text:
        if match := date_regex.search(text):
            try:
                receipt_date = datetime.strptime(
                    match.group(1).replace("/", "-").replace(".", "-"), "%Y-%m-%d"
                ).date()
            except ValueError:
                receipt_date = None

        if match := amount_regex.search(text):
            raw_amount = match.group(1).replace("¥", "").replace(",", "").replace(" ", "")
            try:
                amount_value = Decimal(raw_amount)
            except (InvalidOperation, ValueError):
                amount_value = None

        if match := registration_regex.search(text):
            registration_number = match.group(1)

        # Simple heuristic: use the first non-empty line that is not a date or amount
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if date_regex.search(line) or amount_regex.search(line):
                continue
            recipient = line
            break

    return {
        "receipt_date": receipt_date,
        "amount": amount_value,
        "registration_number": registration_number,
        "recipient": recipient,
    }


def perform_ocr(image_path: Path) -> str:
    try:
        text = pytesseract.image_to_string(Image.open(image_path), lang="jpn+eng")
        return text
    except Exception as exc:  # pylint: disable=broad-except
        app.logger.warning("OCR failed: %s", exc)
        return ""


@app.route("/")
def index():
    return redirect(url_for("submit_application"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/submit", methods=["GET", "POST"])
def submit_application():
    if request.method == "POST":
        file = request.files.get("receipt")
        applicant_name = request.form.get("applicant_name") or DEFAULT_APPLICANT

        if not file or file.filename == "":
            flash("領収書の画像ファイルをアップロードしてください。", "error")
            return redirect(request.url)

        filename = secure_image_filename(file.filename)
        image_path = app.config["UPLOAD_FOLDER"] / filename
        file.save(image_path)

        ocr_text = perform_ocr(image_path)
        extracted = extract_receipt_fields(ocr_text)

        application = ReceiptApplication(
            applicant_name=applicant_name,
            receipt_date=extracted.get("receipt_date"),
            recipient=extracted.get("recipient"),
            amount=extracted.get("amount"),
            registration_number=extracted.get("registration_number"),
            image_filename=filename,
            ocr_text=ocr_text,
        )

        db.session.add(application)
        db.session.commit()

        flash("申請データを登録しました。", "success")
        return redirect(url_for("list_applications"))

    return render_template("submit.html", default_applicant=DEFAULT_APPLICANT)


@app.route("/applications")
def list_applications():
    applications = (
        ReceiptApplication.query.order_by(ReceiptApplication.created_at.desc()).all()
    )
    return render_template("applications.html", applications=applications)


@app.route("/approvals", methods=["GET", "POST"])
def approvals():
    applications = (
        ReceiptApplication.query.order_by(ReceiptApplication.created_at.desc()).all()
    )
    return render_template("approvals.html", applications=applications)


@app.route("/approvals/<int:application_id>", methods=["POST"])
def update_approval(application_id: int):
    status = request.form.get("approval_status")
    notes = request.form.get("approval_notes")

    application = ReceiptApplication.query.get_or_404(application_id)
    application.approval_status = status or application.approval_status
    application.approval_notes = notes
    db.session.commit()

    flash("承認ステータスを更新しました。", "success")
    return redirect(url_for("approvals"))


if __name__ == "__main__":
    app.run(debug=True)

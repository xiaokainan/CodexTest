import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytesseract
from PIL import Image


DATE_PATTERNS = [
    r"(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2})",
    r"(?P<date>\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
]
AMOUNT_PATTERNS = [
    r"(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)",
]
REGISTRATION_PATTERNS = [
    r"(登録|事業|ID)[^\d]*(?P<reg>\d{6,})",
]
RECIPIENT_PATTERNS = [
    r"(宛先|御中|株式会社|有限会社|会社)\s*(?P<recipient>[\w\u3000\u3040-\u30ff\u4e00-\u9fff\-\.・ー\s]{2,})",
]


class OCRService:
    def __init__(self, tesseract_cmd: Optional[str] = None) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def extract_text(self, image_path: Path) -> str:
        try:
            with Image.open(image_path) as img:
                text = pytesseract.image_to_string(img, lang="jpn+eng")
        except Exception:
            text = ""
        return text.strip()

    def parse_fields(self, text: str) -> Dict[str, Any]:
        date = self._find_first_match(text, DATE_PATTERNS, "date")
        parsed_date: Optional[datetime] = None
        if date:
            parsed_date = self._parse_date(date)

        amount = self._find_first_match(text, AMOUNT_PATTERNS, "amount")
        registration_number = self._find_first_match(text, REGISTRATION_PATTERNS, "reg")
        recipient = self._find_first_match(text, RECIPIENT_PATTERNS, "recipient")

        return {
            "date": parsed_date.date() if parsed_date else None,
            "amount": float(amount.replace(",", "")) if amount else None,
            "registration_number": registration_number,
            "recipient": recipient,
        }

    def _find_first_match(self, text: str, patterns: list[str], key: str) -> Optional[str]:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = match.groupdict().get(key)
                if value:
                    return value.strip()
        return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%m.%d.%Y", "%m-%d-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None


def extract_receipt_data(image_path: Path, tesseract_cmd: Optional[str] = None) -> Dict[str, Any]:
    service = OCRService(tesseract_cmd)
    text = service.extract_text(image_path)
    fields = service.parse_fields(text)
    fields["ocr_text"] = text
    return fields

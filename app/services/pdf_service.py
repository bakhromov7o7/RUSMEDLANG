"""PDF hisobotlar.

Ilgari font yo'li faqat macOS'ga xos edi (`/System/Library/Fonts/...`), Linux
serverda esa fpdf standart Helvetica'ga tushib qolardi — u latin-1 kodlashda
ishlaydi va kirill/o'zbek harflarida `UnicodeEncodeError` bilan yiqilardi.
Endi bir nechta nomzod yo'l tekshiriladi, hech biri topilmasa matn xavfsiz
ko'rinishga keltiriladi va PDF baribir yaratiladi.
"""

import logging
import os
import tempfile
import unicodedata
from datetime import datetime
from typing import Optional, Tuple

from fpdf import FPDF

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Regular/Bold juftliklari — birinchi topilgani ishlatiladi.
_FONT_CANDIDATES: list[Tuple[str, str]] = [
    (
        os.getenv("PDF_FONT_REGULAR", ""),
        os.getenv("PDF_FONT_BOLD", ""),
    ),
    (
        os.path.join(_BASE_DIR, "assets", "fonts", "DejaVuSans.ttf"),
        os.path.join(_BASE_DIR, "assets", "fonts", "DejaVuSans-Bold.ttf"),
    ),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
    (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ),
    (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
]

_UNICODE_FONT: Optional[Tuple[str, str]] = None
_FONT_RESOLVED = False


def _resolve_font() -> Optional[Tuple[str, str]]:
    global _UNICODE_FONT, _FONT_RESOLVED
    if _FONT_RESOLVED:
        return _UNICODE_FONT

    _FONT_RESOLVED = True
    for regular, bold in _FONT_CANDIDATES:
        if regular and os.path.exists(regular):
            bold_path = bold if bold and os.path.exists(bold) else regular
            _UNICODE_FONT = (regular, bold_path)
            logger.info("PDF uchun Unicode font topildi: %s", regular)
            return _UNICODE_FONT

    logger.warning(
        "Unicode TTF font topilmadi — PDF'da kirill harflari o'rniga lotin transliteratsiyasi "
        "ishlatiladi. Serverga DejaVu o'rnating (`apt install fonts-dejavu-core`) yoki "
        "PDF_FONT_REGULAR env orqali yo'l ko'rsating."
    )
    return None


_ASCII_REPLACEMENTS = {
    "ʻ": "'", "ʼ": "'", "‘": "'", "’": "'",
    "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
    "№": "No.",
}


class PDFService:
    def __init__(self):
        self._font = _resolve_font()

    # -- matn tayyorlash --------------------------------------------------
    def _clean_text(self, text) -> str:
        if text is None:
            return ""
        text = str(text)
        for old, new in _ASCII_REPLACEMENTS.items():
            text = text.replace(old, new)

        if self._font is not None:
            return text

        # Unicode font yo'q — latin-1 ga sig'maydigan belgilarni xavfsiz
        # ko'rinishga keltiramiz, aks holda fpdf xato beradi.
        normalized = unicodedata.normalize("NFKD", text)
        return normalized.encode("latin-1", "replace").decode("latin-1")

    def _create_pdf(self) -> Tuple[FPDF, str]:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        if self._font is None:
            return pdf, "Helvetica"

        regular, bold = self._font
        try:
            pdf.add_font("AppFont", "", regular)
            pdf.add_font("AppFont", "B", bold)
            return pdf, "AppFont"
        except Exception as exc:  # noqa: BLE001 — font buzuq bo'lishi mumkin
            logger.warning("Font yuklanmadi (%s), Helvetica'ga qaytamiz: %s", regular, exc)
            self._font = None
            return pdf, "Helvetica"

    @staticmethod
    def _temp_path(prefix: str) -> str:
        handle, path = tempfile.mkstemp(prefix=prefix, suffix=".pdf")
        os.close(handle)
        return path

    # -- hisobotlar -------------------------------------------------------
    def generate_quiz_report(
        self,
        user_full_name: str,
        topic_title: str,
        results: list,
        score: int,
        total: int,
    ) -> str:
        user_full_name = self._clean_text(user_full_name)
        topic_title = self._clean_text(topic_title)

        pdf, font_family = self._create_pdf()
        pdf.add_page()

        pdf.set_font(font_family, "B", 16)
        pdf.cell(0, 10, self._clean_text("Ustoz AI - Test Natijalari"), new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_font(font_family, "", 12)
        pdf.cell(0, 10, f"Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(10)

        percent = int(score / total * 100) if total else 0

        pdf.set_font(font_family, "B", 12)
        pdf.cell(0, 10, f"Talaba: {user_full_name}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, f"Mavzu: {topic_title}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, f"Natija: {score} / {total} ({percent}%)", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(10)

        for i, item in enumerate(results or [], 1):
            pdf.set_font(font_family, "B", 11)
            pdf.multi_cell(0, 7, f"{i}. {self._clean_text(item.get('question'))}", new_x="LMARGIN", new_y="NEXT")

            options = item.get("options")
            user_answer = item.get("user_answer")
            correct_option = item.get("correct_option")

            pdf.set_font(font_family, "", 10)
            if isinstance(options, dict) and options:
                for key, value in options.items():
                    if key == user_answer:
                        prefix = "[X]" if user_answer == correct_option else "[!]"
                    elif key == correct_option:
                        prefix = "(*)"
                    else:
                        prefix = "   "
                    pdf.multi_cell(0, 6, f"{prefix} {key}: {self._clean_text(value)}", new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.multi_cell(0, 6, f"To'g'ri javob: {self._clean_text(correct_option)}", new_x="LMARGIN", new_y="NEXT")
                pdf.multi_cell(0, 6, f"Sizning javobingiz: {self._clean_text(user_answer)}", new_x="LMARGIN", new_y="NEXT")

            explanation = item.get("explanation")
            if explanation:
                pdf.set_font(font_family, "", 9)
                pdf.set_text_color(100, 100, 100)
                pdf.multi_cell(0, 6, f"Izoh: {self._clean_text(explanation)}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

        path = self._temp_path("quiz_report_")
        pdf.output(path)
        return path

    def generate_topic_pdf(self, topic_title: str, content: str) -> str:
        topic_title = self._clean_text(topic_title)
        content = self._clean_text(content)

        pdf, font_family = self._create_pdf()
        pdf.add_page()

        pdf.set_font(font_family, "B", 18)
        pdf.multi_cell(0, 10, topic_title, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(10)

        pdf.set_font(font_family, "", 11)
        pdf.multi_cell(0, 7, content or "-", new_x="LMARGIN", new_y="NEXT")

        path = self._temp_path("topic_")
        pdf.output(path)
        return path

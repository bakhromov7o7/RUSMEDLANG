import os
from fpdf import FPDF
from datetime import datetime

class PDFService:
    def _clean_text(self, text: str):
        if not text:
            return ""
        # Replace common Uzbek special characters with compatible equivalents
        replacements = {
            "ʻ": "'",
            "ʼ": "'",
            "“": "\"",
            "”": "\"",
            "–": "-",
            "—": "-",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def _create_pdf(self):
        pdf = FPDF()
        font_family = "Helvetica"
        try:
            pdf.add_font("Arial", "", "/System/Library/Fonts/Supplemental/Arial.ttf")
            pdf.add_font("Arial", "B", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
            font_family = "Arial"
        except Exception as e:
            print(f"Error loading system Arial font: {e}")
        return pdf, font_family

    def generate_quiz_report(self, user_full_name: str, topic_title: str, results: list, score: int, total: int):
        user_full_name = self._clean_text(user_full_name)
        topic_title = self._clean_text(topic_title)
        
        pdf, font_family = self._create_pdf()
        pdf.add_page()
        
        # Title
        pdf.set_font(font_family, "B", 16)
        pdf.cell(0, 10, "Ustoz AI - Test Natijalari", ln=True, align="C")
        pdf.set_font(font_family, "", 12)
        pdf.cell(0, 10, f"Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}", ln=True, align="C")
        pdf.ln(10)
        
        # User Info
        pdf.set_font(font_family, "B", 12)
        pdf.cell(0, 10, f"Talaba: {user_full_name}", ln=True)
        pdf.cell(0, 10, f"Mavzu: {topic_title}", ln=True)
        pdf.cell(0, 10, f"Natija: {score} / {total} ({int(score/total*100)}%)", ln=True)
        pdf.ln(5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(10)
        
        # Questions
        for i, item in enumerate(results, 1):
            pdf.set_font(font_family, "B", 11)
            # Question text
            question_text = self._clean_text(item['question'])
            pdf.multi_cell(0, 7, f"{i}. {question_text}")
            
            # Options (if available)
            if 'options' in item and isinstance(item['options'], dict):
                pdf.set_font(font_family, "", 10)
                for opt, text in item['options'].items():
                    text = self._clean_text(text)
                    prefix = ""
                    if opt == item['user_answer']:
                        prefix = "[X] " if item['user_answer'] == item['correct_option'] else "[!] "
                    elif opt == item['correct_option']:
                        prefix = "(*) "
                    else:
                        prefix = "    "
                    pdf.cell(0, 6, f"{prefix} {opt}: {text}", ln=True)
            else:
                # Basic result for history
                pdf.set_font(font_family, "", 10)
                pdf.cell(0, 6, f"To'g'ri javob: {item['correct_option']}", ln=True)
                pdf.cell(0, 6, f"Sizning javobingiz: {item['user_answer']}", ln=True)
            
            # Explanation (if available)
            if 'explanation' in item and item['explanation']:
                pdf.set_font(font_family, "", 9)
                pdf.set_text_color(100, 100, 100)
                explanation_text = self._clean_text(item['explanation'])
                pdf.multi_cell(0, 6, f"Izoh: {explanation_text}")
                pdf.set_text_color(0, 0, 0)
            pdf.ln(5)
            
            if pdf.get_y() > 250:
                pdf.add_page()

        # Save PDF
        os.makedirs("reports", exist_ok=True)
        filename = f"reports/quiz_{datetime.now().timestamp()}.pdf"
        pdf.output(filename)
        return filename

    def generate_topic_pdf(self, topic_title: str, content: str):
        topic_title = self._clean_text(topic_title)
        content = self._clean_text(content)
        
        pdf, font_family = self._create_pdf()
        pdf.add_page()
        
        # Title
        pdf.set_font(font_family, "B", 18)
        pdf.cell(0, 10, topic_title, ln=True, align="C")
        pdf.ln(5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(10)
        
        # Content
        pdf.set_font(font_family, "", 11)
        pdf.multi_cell(0, 7, content)
        
        # Save PDF
        os.makedirs("reports", exist_ok=True)
        filename = f"reports/topic_{datetime.now().timestamp()}.pdf"
        pdf.output(filename)
        return filename


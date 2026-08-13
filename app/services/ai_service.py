import asyncio
import json
import logging
import os
from typing import Optional

from openai import AsyncOpenAI

from app.core import config

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self):
        # GROQ_API_KEY va GROQ_API_KEY_2, _3 ... ko'rinishidagi barcha kalitlar.
        self.api_keys: list[str] = []
        primary_key = os.getenv("GROQ_API_KEY")
        if primary_key:
            self.api_keys.append(primary_key)

        i = 2
        while True:
            key = os.getenv(f"GROQ_API_KEY_{i}")
            if not key:
                break
            self.api_keys.append(key)
            i += 1

        if not self.api_keys:
            logger.warning(
                "GROQ_API_KEY topilmadi — AI funksiyalari ishlamaydi (quiz generatsiya, tarjima, savol-javob)."
            )
            self.api_keys.append("")

        self.current_key_index = 0
        # Sinxron `OpenAI` klienti async route ichida chaqirilganda butun event
        # loop bloklanardi — AsyncOpenAI bu muammoni yo'q qiladi.
        self.clients = [
            AsyncOpenAI(
                base_url=config.OPENAI_API_BASE,
                api_key=key,
                timeout=config.AI_TIMEOUT_SECONDS,
                max_retries=0,  # qayta urinishni o'zimiz kalit almashtirib boshqaramiz
            )
            for key in self.api_keys
        ]
        self.model = config.OPENAI_MODEL

    @property
    def is_configured(self) -> bool:
        return any(bool(k) for k in self.api_keys)

    def _language_name(self, language: str) -> str:
        lang = str(language or "uz").lower()
        if lang.startswith("ru"):
            return "rus tilida"
        if lang.startswith("en"):
            return "ingliz tilida"
        return "o'zbek tilida"

    def _json_response_format(self):
        return (
            {"type": "json_object"}
            if ("gpt-4" in self.model or "llama" in self.model or "mixtral" in self.model)
            else None
        )

    @staticmethod
    def clean_json(raw: str) -> str:
        """Markdown kod bloki ichidagi JSON'ni ajratib oladi."""
        if not raw:
            return ""
        if "```json" in raw:
            return raw.split("```json", 1)[1].split("```", 1)[0].strip()
        if "```" in raw:
            parts = raw.split("```")
            if len(parts) >= 2:
                return parts[1].strip()
        return raw.strip()

    async def _execute_completion(self, messages, response_format=None) -> str:
        if not self.is_configured:
            raise RuntimeError(
                "AI xizmati sozlanmagan: .env faylida GROQ_API_KEY ko'rsatilmagan"
            )

        max_total_retries = len(self.clients) * 2
        delay = 1.0
        last_error: Optional[Exception] = None

        for attempt in range(max_total_retries):
            client = self.clients[self.current_key_index]
            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format=response_format,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001 — provayder xatolari xilma-xil
                last_error = exc
                old_index = self.current_key_index
                self.current_key_index = (self.current_key_index + 1) % len(self.clients)

                if attempt == max_total_retries - 1:
                    break

                logger.warning(
                    "LLM xatosi (kalit #%s, urinish %s/%s): %s. Kalit #%s ga o'tib %.1fs dan keyin qayta urinamiz.",
                    old_index, attempt + 1, max_total_retries, exc, self.current_key_index, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8.0)

        raise last_error if last_error else RuntimeError("AI so'rovi bajarilmadi")

    async def get_response(self, context: str, user_query: str, language: str = "uz") -> str:
        language_name = self._language_name(language)
        system_prompt = f"""
        Siz "Ustoz AI" yordamchisiz. Quyidagi mavzu bo'yicha berilgan context'dan foydalanib student savoliga javob bering.
        Javobni {language_name} bering.
        Agar javob context'da bo'lmasa, buni muloyimlik bilan ayting.

        Context:
        {context}
        """
        return await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ]
        )

    async def translate_topic(self, title: str, content: str, language: str = "ru") -> dict:
        lang = str(language or "uz").lower()
        if not lang.startswith("ru"):
            return {"title": title, "content": content}

        system_prompt = """
        Siz professional tarjimonsiz. Berilgan universitet mavzusini rus tiliga aniq tarjima qiling.
        Ma'noni o'zgartirmang, Markdown tuzilishini saqlang, qo'shimcha izoh yozmang.
        Faqat valid JSON qaytaring: {"title": "...", "content": "..."}.
        """

        raw = await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"title": title or "", "content": content or ""}, ensure_ascii=False
                    ),
                },
            ],
            response_format=self._json_response_format(),
        )

        try:
            data = json.loads(self.clean_json(raw))
            return {
                "title": data.get("title") or title,
                "content": data.get("content") or content,
            }
        except (ValueError, AttributeError):
            return {"title": title, "content": raw.strip() or content}

    async def answer_topic_question(self, context: str, question: str, language: str = "uz") -> str:
        language_name = self._language_name(language)
        system_prompt = f"""
        Siz "Ustoz AI" o'quv yordamchisisiz.
        Student savoliga FAQAT quyidagi mavzu contexti asosida javob bering.
        Savol mavzudan tashqari bo'lsa, qisqa va muloyim rad eting.
        Javob {language_name} bo'lsin, sodda, tushunarli va 2-5 gapdan oshmasin.

        Context:
        {context}
        """
        return await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )

    async def generate_quiz(self, context: str, count: int = 5, language: str = "uz") -> str:
        lang = "ru" if str(language).lower().startswith("ru") else "uz"
        output_language = "русском языке" if lang == "ru" else "o'zbek tilida"
        user_instruction = (
            f"Составьте {count} академических тестовых вопросов на русском языке в JSON формате."
            if lang == "ru"
            else f"Berilgan matn asosida {count} ta akademik test savollarini o'zbek tilida JSON formatida tayyorlang."
        )
        system_prompt = f"""
        Siz universitet darajasidagi professor va ekspertsiz.
        Quyidagi berilgan matn (Context) asosida studentlar bilimini tekshirish uchun {count} ta murakkab va mantiqiy test savollarini tuzing.
        Savollar, variantlar va izohlar {output_language} bo'lishi shart.

        Xavfsizlik va Sifat qoidalari:
        1. Savollar faqat berilgan matn asosida bo'lishi shart.
        2. Har bir savol uchun 4 ta variant (A, B, C, D) bo'lishi shart.
        3. Faqat bitta to'g'ri javob bo'lishi kerak.
        4. Savollar o'ta aniq, akademik tilda va xatosiz bo'lishi shart.
        5. Javoblar formatini FAQAT JSON ko'rinishida qaytaring.

        JSON formati misoli:
        {{
          "questions": [
            {{
              "question": "Savol matni bu yerda...",
              "options": {{
                "A": "Variant 1",
                "B": "Variant 2",
                "C": "Variant 3",
                "D": "Variant 4"
              }},
              "correct_option": "A",
              "explanation": "Nima uchun bu javob to'g'riligi haqida qisqacha izoh."
            }}
          ]
        }}

        Context:
        {context}
        """

        return await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_instruction},
            ],
            response_format=self._json_response_format(),
        )

    @staticmethod
    def parse_quiz_payload(raw: str) -> list[dict]:
        """AI qaytargan JSON'ni savollar ro'yxatiga aylantiradi.

        Model ba'zan ro'yxat o'rniga obyekt qaytaradi ({"questions": [...]},
        {"1": {...}} va h.k.) — barcha ko'rinishlarni ochamiz.
        """
        data = json.loads(AIService.clean_json(raw))

        if isinstance(data, dict):
            found = None
            for key in ("questions", "quiz", "test", "savollar", "savol"):
                value = data.get(key)
                if isinstance(value, list):
                    found = value
                    break

            if found is None:
                for value in data.values():
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        found = value
                        break

            if found is None:
                values = list(data.values())
                if values and isinstance(values[0], dict) and (
                    "question" in values[0] or "options" in values[0]
                ):
                    found = values

            if found is not None:
                data = found

        if not isinstance(data, list):
            raise ValueError("AI javobi savollar ro'yxati emas")
        return data

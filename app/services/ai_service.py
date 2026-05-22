import os
import json
import asyncio
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class AIService:
    def __init__(self):
        # Collect all keys defined in env matching GROQ_API_KEY or GROQ_API_KEY_*
        self.api_keys = []
        primary_key = os.getenv("GROQ_API_KEY")
        if primary_key:
            self.api_keys.append(primary_key)
        
        # Load additional keys e.g. GROQ_API_KEY_2, GROQ_API_KEY_3...
        i = 2
        while True:
            key = os.getenv(f"GROQ_API_KEY_{i}")
            if not key:
                break
            self.api_keys.append(key)
            i += 1
        
        # Fallback if no keys in env, to prevent crash at init
        if not self.api_keys:
            self.api_keys.append("")

        self.current_key_index = 0
        
        # Initialize OpenAI client wrappers for each key
        self.clients = [
            OpenAI(
                base_url=os.getenv("OPENAI_API_BASE", "https://api.groq.com/openai/v1"),
                api_key=k
            )
            for k in self.api_keys
        ]
        
        self.model = os.getenv("OPENAI_MODEL", "openai/gpt-oss-20b")

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
            if (
                "gpt-4" in self.model
                or "llama" in self.model
                or "mixtral" in self.model
            )
            else None
        )

    def _clean_json(self, raw: str) -> str:
        if "```json" in raw:
            return raw.split("```json")[1].split("```")[0].strip()
        if "```" in raw:
            return raw.split("```")[1].split("```")[0].strip()
        return raw.strip()

    async def _execute_completion(self, messages, response_format=None):
        # Allow retrying each key up to 2 times
        max_total_retries = len(self.clients) * 2
        delay = 1.0
        
        for attempt in range(max_total_retries):
            client = self.clients[self.current_key_index]
            try:
                # Chat completions is blocking in openai SDK, which is fine since the FastAPI routes are async.
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format=response_format,
                )
                return response
            except Exception as e:
                # Rotate key immediately on error
                old_index = self.current_key_index
                self.current_key_index = (self.current_key_index + 1) % len(self.clients)
                
                if attempt == max_total_retries - 1:
                    raise e
                
                print(
                    f"LLM API Error with key index {old_index} (attempt {attempt + 1}/{max_total_retries}): {e}. "
                    f"Rotating to key index {self.current_key_index} and retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8.0)

    async def get_response(self, context: str, user_query: str, language: str = "uz"):
        language_name = self._language_name(language)
        system_prompt = f"""
        Siz "Ustoz AI" botisiz. Quyidagi mavzu bo'yicha berilgan context'dan foydalanib student savoliga javob bering.
        Javobni {language_name} bering.
        Agar javob context'da bo'lmasa, buni muloyimlik bilan ayting.
        
        Context:
        {context}
        """
        
        response = await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ]
        )
        return response.choices[0].message.content

    async def translate_topic(self, title: str, content: str, language: str = "ru"):
        lang = str(language or "uz").lower()
        if not lang.startswith("ru"):
            return {"title": title, "content": content}

        system_prompt = """
        Siz professional tarjimonsiz. Berilgan universitet mavzusini rus tiliga aniq tarjima qiling.
        Ma'noni o'zgartirmang, Markdown tuzilishini saqlang, qo'shimcha izoh yozmang.
        Faqat valid JSON qaytaring: {"title": "...", "content": "..."}.
        """

        response = await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"title": title or "", "content": content or ""},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format=self._json_response_format(),
        )

        raw = response.choices[0].message.content or ""
        try:
            data = json.loads(self._clean_json(raw))
            return {
                "title": data.get("title") or title,
                "content": data.get("content") or content,
            }
        except Exception:
            return {"title": title, "content": raw.strip() or content}

    async def answer_topic_question(self, context: str, question: str, language: str = "uz"):
        language_name = self._language_name(language)
        system_prompt = f"""
        Siz "Ustoz AI" o'quv yordamchisisiz.
        Student savoliga FAQAT quyidagi mavzu contexti asosida javob bering.
        Savol mavzudan tashqari bo'lsa, qisqa va muloyim rad eting.
        Javob {language_name} bo'lsin, sodda, tushunarli va 2-5 gapdan oshmasin.

        Context:
        {context}
        """

        response = await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )
        return response.choices[0].message.content

    async def generate_quiz(self, context: str, count: int = 5, language: str = "uz"):
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

        response = await self._execute_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_instruction}
            ],
            response_format=self._json_response_format(),
        )
        return response.choices[0].message.content

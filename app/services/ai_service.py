import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class AIService:
    def __init__(self):
        self.client = OpenAI(
            base_url=os.getenv("OPENAI_API_BASE", "https://api.groq.com/openai/v1"),
            api_key=os.getenv("GROQ_API_KEY")
        )
        self.model = os.getenv("OPENAI_MODEL", "openai/gpt-oss-20b")

    async def get_response(self, context: str, user_query: str, language: str = "uz"):
        system_prompt = f"""
        Siz "Ustoz AI" botisiz. Quyidagi mavzu bo'yicha berilgan context'dan foydalanib student savoliga javob bering.
        Javobni {language} tilida bering.
        Agar javob context'da bo'lmasa, buni muloyimlik bilan ayting.
        
        Context:
        {context}
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ]
        )
        return response.choices[0].message.content

    async def generate_quiz(self, context: str, count: int = 5):
        system_prompt = f"""
        Siz universitet darajasidagi professor va ekspertsiz. 
        Quyidagi berilgan matn (Context) asosida studentlar bilimini tekshirish uchun {count} ta murakkab va mantiqiy test savollarini tuzing.
        
        Xavfsizlik va Sifat qoidalari:
        1. Savollar faqat berilgan matn asosida bo'lishi shart.
        2. Har bir savol uchun 4 ta variant (A, B, C, D) bo'lishi shart.
        3. Faqat bitta to'g'ri javob bo'lishi kerak.
        4. Savollar o'ta aniq, akademik tilda va xatosiz bo'lishi shart.
        5. Javoblar formatini FAQAT JSON ko'rinishida qaytaring.
        
        JSON formati misoli:
        [
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
        
        Context:
        {context}
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Berilgan matn asosida {count} ta akademik test savollarini JSON formatida tayyorlang."}
            ],
            response_format={ "type": "json_object" } if "gpt-4" in self.model else None
        )
        return response.choices[0].message.content

"""Serverni ishga tushirish uchun qulay skript: python run.py

reload=True rejimi FAQAT dasturchi o'zi lokal kompyuterda kod o'zgartirib
turganda kerak -- u fayllarni kuzatib turish uchun qo'shimcha resurs
sarflaydi va doimiy ishlaydigan (masalan cloudflared tunnel orqali
ochilgan) production serverga mos emas. Shu sabab endi sukut bo'yicha
O'CHIRILGAN, .env faylida DEV_RELOAD=true qilib yoqish mumkin.
"""

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

if __name__ == "__main__":
    reload = os.getenv("DEV_RELOAD", "false").strip().lower() == "true"
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)

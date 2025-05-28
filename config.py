import os
from dotenv import load_dotenv

# .env faylidan atrof-muhit o'zgaruvchilarini yuklash
load_dotenv()

# Telegram bot tokeni
BOT_TOKEN = os.getenv("BOT_TOKEN")
# PostgreSQL ma'lumotlar bazasi ulanish URL'i
DB_URL = os.getenv("DB_URL")
# Redis ma'lumotlar bazasi ulanish URL'i (Aiogram FSM storage uchun)
REDIS_URL = os.getenv("REDIS_URL")
# Text-to-Speech (TTS) API kaliti (agar pulli xizmatdan foydalanilsa)
# Hozircha gTTS dan foydalanamiz, unga kalit kerak emas.
# TTS_API_KEY = os.getenv("TTS_API_KEY")

# Kuniga beriladigan so'zlar soni
WORDS_PER_DAY = 50
# Testdan o'tish uchun minimal foiz
PASS_PERCENTAGE = 92
# Test variantlari soni (to'g'ri javob + noto'g'ri javoblar)
TEST_OPTIONS_COUNT = 3

# Loglash sozlamalari
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO").upper()
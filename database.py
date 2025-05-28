import asyncpg
from datetime import datetime, timedelta
import logging
import random

from config import DB_URL, WORDS_PER_DAY, PASS_PERCENTAGE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ma'lumotlar bazasi ulanish puli (connection pool)
db_pool = None

async def init_db_pool():
    """
    Ma'lumotlar bazasi ulanish pulini (connection pool) ishga tushiradi.
    """
    global db_pool
    if db_pool is None:
        try:
            db_pool = await asyncpg.create_pool(DB_URL)
            logger.info("Ma'lumotlar bazasi ulanish puli muvaffaqiyatli yaratildi.")
        except Exception as e:
            logger.error(f"Ma'lumotlar bazasi ulanish pulini yaratishda xato: {e}")
            raise

async def close_db_pool():
    """
    Ma'lumotlar bazasi ulanish pulini yopadi.
    """
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Ma'lumotlar bazasi ulanish puli yopildi.")

async def create_tables():
    """
    Ma'lumotlar bazasida kerakli jadvallarni yaratadi.
    """
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS words (
                id SERIAL PRIMARY KEY,
                english_word TEXT NOT NULL UNIQUE,
                uzbek_word TEXT NOT NULL,
                audio_url TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL UNIQUE,
                last_word_fetch_date TIMESTAMP DEFAULT NULL,
                last_test_date TIMESTAMP DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS user_words (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                word_id INTEGER REFERENCES words(id),
                is_learned BOOLEAN DEFAULT FALSE,
                correct_attempts INTEGER DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                last_attempt_date TIMESTAMP DEFAULT NULL,
                date_assigned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, word_id)
            );
        ''')
        logger.info("Jadvallar muvaffaqiyatli yaratildi (agar mavjud bo'lmasa).")

async def add_word(english_word: str, uzbek_word: str, audio_url: str = None):
    """
    Yangi so'zni 'words' jadvaliga qo'shadi.
    """
    async with db_pool.acquire() as conn:
        try:
            await conn.execute('''
                INSERT INTO words (english_word, uzbek_word, audio_url)
                VALUES ($1, $2, $3)
                ON CONFLICT (english_word) DO NOTHING;
            ''', english_word, uzbek_word, audio_url)
            logger.info(f"So'z qo'shildi/mavjud: {english_word} - {uzbek_word}")
        except Exception as e:
            logger.error(f"So'z qo'shishda xato ({english_word}): {e}")

async def get_total_words_count():
    """
    Lug'atdagi umumiy so'zlar sonini qaytaradi.
    """
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM words;")
        return count

async def add_sample_words():
    """
    Ma'lumotlar bazasiga namunaviy so'zlarni qo'shadi.
    """
    sample_words = [
        ("apple", "olma"), ("book", "kitob"), ("house", "uy"), ("car", "mashina"),
        ("tree", "daraxt"), ("water", "suv"), ("sun", "quyosh"), ("moon", "oy"),
        ("star", "yulduz"), ("flower", "gul"), ("cat", "mushuk"), ("dog", "it"),
        ("bird", "qush"), ("fish", "baliq"), ("food", "oziq-ovqat"), ("drink", "ichimlik"),
        ("city", "shahar"), ("country", "davlat"), ("world", "dunyo"), ("time", "vaqt"),
        ("day", "kun"), ("night", "tun"), ("morning", "ertalab"), ("evening", "kechqurun"),
        ("friend", "do'st"), ("family", "oila"), ("love", "sevgi"), ("happy", "xursand"),
        ("sad", "xafa"), ("big", "katta"), ("small", "kichik"), ("new", "yangi"),
        ("old", "eski"), ("good", "yaxshi"), ("bad", "yomon"), ("beautiful", "chiroyli"),
        ("ugly", "xunuk"), ("fast", "tez"), ("slow", "sekin"), ("hot", "issiq"),
        ("cold", "sovuq"), ("open", "ochiq"), ("close", "yopiq"), ("read", "o'qimoq"),
        ("write", "yozmoq"), ("speak", "gapirmoq"), ("listen", "tinglamoq"), ("see", "ko'rmoq"),
        ("hear", "eshitmoq"), ("walk", "yurmoq"), ("run", "yugurmoq"), ("sleep", "uxlamoq"),
        ("eat", "yemoq"), ("drink", "ichmoq"), ("work", "ishlamoq"), ("play", "o'ynamoq"),
        ("learn", "o'rganmoq"), ("teach", "o'rgatmoq"), ("help", "yordam bermoq"), ("ask", "so'ramoq"),
        ("answer", "javob bermoq"), ("buy", "sotib olmoq"), ("sell", "sotmoq"), ("give", "bermoq"),
        ("take", "olmoq"), ("come", "kelmoq"), ("go", "bormoq"), ("sit", "o'tirmoq"),
        ("stand", "turmoq"), ("find", "topmoq"), ("lose", "yo'qotmoq"), ("know", "bilmoq"),
        ("think", "o'ylamoq"), ("feel", "his qilmoq"), ("want", "xohlamoq"), ("need", "muhtoj bo'lmoq"),
        ("use", "foydalanmoq"), ("make", "qilmoq"), ("do", "bajarmoq"), ("say", "aytmoq"),
        ("tell", "gapirib bermoq"), ("show", "ko'rsatmoq"), ("start", "boshlamoq"), ("stop", "to'xtatmoq"),
        ("finish", "tugatmoq"), ("begin", "boshlamoq"), ("end", "tugatmoq"), ("wait", "kutmoq"),
        ("send", "yubormoq"), ("receive", "qabul qilmoq"), ("bring", "olib kelmoq"), ("carry", "olib bormoq"),
        ("clean", "tozalamoq"), ("dirty", "iflos"), ("empty", "bo'sh"), ("full", "to'la"),
        ("heavy", "og'ir"), ("light", "engil"), ("long", "uzun"), ("short", "qisqa"),
        ("wide", "keng"), ("narrow", "tor"), ("deep", "chuqur"), ("shallow", "sayoz"),
        ("early", "erta"), ("late", "kech"), ("first", "birinchi"), ("last", "oxirgi"),
        ("next", "keyingi"), ("previous", "oldingi"), ("same", "bir xil"), ("different", "har xil")
    ]
    for eng, uzb in sample_words:
        await add_word(eng, uzb)
    logger.info(f"{len(sample_words)} ta namunaviy so'z bazaga qo'shildi.")


async def get_or_create_user(telegram_id: int):
    """
    Foydalanuvchini topadi yoki yangi foydalanuvchi yaratadi.
    """
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1;", telegram_id)
        if user:
            return user
        else:
            new_user = await conn.fetchrow('''
                INSERT INTO users (telegram_id) VALUES ($1)
                RETURNING *;
            ''', telegram_id)
            logger.info(f"Yangi foydalanuvchi yaratildi: {telegram_id}")
            return new_user

async def get_words_for_user(user_id: int, fetch_new: bool = True):
    """
    Foydalanuvchi uchun kunlik 50 ta so'zni qaytaradi.
    Agar fetch_new True bo'lsa, yangi so'zlarni tanlaydi va bazaga yozadi.
    Aks holda, foydalanuvchining o'rganilmagan so'zlarini qaytaradi.
    """
    async with db_pool.acquire() as conn:
        if fetch_new:
            # Foydalanuvchi allaqachon o'rgangan so'zlar ID'sini olish
            learned_word_ids = await conn.fetch('''
                SELECT word_id FROM user_words
                WHERE user_id = $1 AND is_learned = TRUE;
            ''', user_id)
            learned_word_ids = [row['word_id'] for row in learned_word_ids]

            # Foydalanuvchiga hali berilmagan yoki o'rganilmagan so'zlarni tanlash
            new_words = await conn.fetch(f'''
                SELECT id, english_word, uzbek_word, audio_url FROM words
                WHERE id NOT IN (SELECT word_id FROM user_words WHERE user_id = $1 AND is_learned = TRUE)
                ORDER BY RANDOM()
                LIMIT {WORDS_PER_DAY};
            ''', user_id)

            if not new_words:
                # Agar yangi so'zlar qolmagan bo'lsa, o'rganilmagan so'zlardan berish
                new_words = await conn.fetch(f'''
                    SELECT w.id, w.english_word, w.uzbek_word, w.audio_url
                    FROM words w
                    JOIN user_words uw ON w.id = uw.word_id
                    WHERE uw.user_id = $1 AND uw.is_learned = FALSE
                    ORDER BY RANDOM()
                    LIMIT {WORDS_PER_DAY};
                ''', user_id)
                if not new_words:
                    logger.warning(f"Foydalanuvchi {user_id} uchun yangi so'zlar topilmadi va o'rganilmagan so'zlar ham yo'q.")
                    return [] # Barcha so'zlar o'rganilgan yoki lug'at bo'sh

            # Tanlangan so'zlarni user_words jadvaliga yozish
            for word in new_words:
                await conn.execute('''
                    INSERT INTO user_words (user_id, word_id, date_assigned)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, word_id) DO UPDATE SET date_assigned = $3, is_learned = FALSE, correct_attempts = 0, total_attempts = 0;
                ''', user_id, word['id'], datetime.now())

            # Foydalanuvchining oxirgi so'z olish sanasini yangilash
            await conn.execute('''
                UPDATE users SET last_word_fetch_date = $1 WHERE id = $2;
            ''', datetime.now(), user_id)
            logger.info(f"Foydalanuvchi {user_id} uchun {len(new_words)} ta yangi so'z berildi.")
            return new_words
        else:
            # Foydalanuvchining o'rganilmagan so'zlarini qaytarish (test uchun)
            unlearned_words = await conn.fetch('''
                SELECT w.id, w.english_word, w.uzbek_word, w.audio_url,
                       uw.correct_attempts, uw.total_attempts
                FROM words w
                JOIN user_words uw ON w.id = uw.word_id
                WHERE uw.user_id = $1 AND uw.is_learned = FALSE AND uw.date_assigned >= $2
                ORDER BY uw.date_assigned DESC;
            ''', user_id, datetime.now() - timedelta(days=2)) # Oxirgi 2 kun ichida berilgan so'zlar
            logger.info(f"Foydalanuvchi {user_id} uchun {len(unlearned_words)} ta o'rganilmagan so'z topildi.")
            return unlearned_words


async def get_random_words_for_options(exclude_word_id: int, count: int):
    """
    Test variantlari uchun tasodifiy so'zlarni qaytaradi, berilgan so'zni istisno qilgan holda.
    """
    async with db_pool.acquire() as conn:
        words = await conn.fetch('''
            SELECT id, english_word, uzbek_word FROM words
            WHERE id != $1
            ORDER BY RANDOM()
            LIMIT $2;
        ''', exclude_word_id, count)
        return words

async def update_user_word_progress(user_id: int, word_id: int, is_correct: bool):
    """
    Foydalanuvchining so'z bo'yicha progressini yangilaydi.
    """
    async with db_pool.acquire() as conn:
        if is_correct:
            await conn.execute('''
                UPDATE user_words SET
                    correct_attempts = correct_attempts + 1,
                    total_attempts = total_attempts + 1,
                    last_attempt_date = $1
                WHERE user_id = $2 AND word_id = $3;
            ''', datetime.now(), user_id, word_id)
        else:
            await conn.execute('''
                UPDATE user_words SET
                    total_attempts = total_attempts + 1,
                    last_attempt_date = $1
                WHERE user_id = $2 AND word_id = $3;
            ''', datetime.now(), user_id, word_id)
        logger.info(f"Foydalanuvchi {user_id}, so'z {word_id}: javob {"to\'g\'ri' if is_correct else 'noto\'g\'ri"}")

async def get_user_test_words(user_id: int):
    """
    Foydalanuvchi uchun testga tayyor bo'lgan so'zlarni qaytaradi.
    Bu so'zlar kecha berilgan va hali o'rganilmagan so'zlar bo'lishi kerak.
    """
    async with db_pool.acquire() as conn:
        # Kecha berilgan va hali o'rganilmagan so'zlarni olish
        # Bugun ertalab so'z olgan bo'lsa, kechagi so'zlarni test qilish kerak.
        # last_word_fetch_date dan 24 soat o'tgan bo'lsa testga tayyor deb hisoblaymiz.
        words = await conn.fetch(f'''
            SELECT w.id, w.english_word, w.uzbek_word, w.audio_url,
                   uw.correct_attempts, uw.total_attempts
            FROM words w
            JOIN user_words uw ON w.id = uw.word_id
            WHERE uw.user_id = $1 AND uw.is_learned = FALSE
            AND uw.date_assigned >= (NOW() - INTERVAL '2 days') -- Oxirgi 2 kun ichida berilgan so'zlar
            ORDER BY uw.date_assigned DESC
            LIMIT {WORDS_PER_DAY};
        ''', user_id)
        return words

async def calculate_test_result(user_id: int, word_ids: list[int]):
    """
    Foydalanuvchining test natijasini hisoblaydi va so'zlarni yangilaydi.
    """
    async with db_pool.acquire() as conn:
        total_correct = 0
        total_attempts = 0

        # Faqat joriy testdagi so'zlar uchun natijalarni olish
        for word_id in word_ids:
            row = await conn.fetchrow('''
                SELECT correct_attempts, total_attempts FROM user_words
                WHERE user_id = $1 AND word_id = $2;
            ''', user_id, word_id)
            if row:
                total_correct += row['correct_attempts']
                total_attempts += row['total_attempts']

        if total_attempts == 0:
            return 0.0 # Agar hech qanday urinish bo'lmasa

        percentage = (total_correct / total_attempts) * 100
        logger.info(f"Foydalanuvchi {user_id} test natijasi: {percentage:.2f}%")

        if percentage >= PASS_PERCENTAGE:
            # So'zlarni "o'rganilgan" deb belgilash
            for word_id in word_ids:
                await conn.execute('''
                    UPDATE user_words SET is_learned = TRUE
                    WHERE user_id = $1 AND word_id = $2;
                ''', user_id, word_id)
            logger.info(f"Foydalanuvchi {user_id} testdan o'tdi. So'zlar o'rganilgan deb belgilandi.")
            return percentage
        else:
            # So'zlarni qayta urinish uchun tayyor holatga qaytarish
            # Ya'ni, is_learned FALSE qoladi, correct_attempts va total_attempts nolga qaytarilmaydi
            # Lekin keyingi kun yana shu so'zlar test qilinadi.
            logger.info(f"Foydalanuvchi {user_id} testdan o'tmadi. So'zlar qayta takrorlanadi.")
            return percentage

async def update_user_last_test_date(user_id: int):
    """
    Foydalanuvchining oxirgi test sanasini yangilaydi.
    """
    async with db_pool.acquire() as conn:
        await conn.execute('''
            UPDATE users SET last_test_date = $1 WHERE id = $2;
        ''', datetime.now(), user_id)
        logger.info(f"Foydalanuvchi {user_id} oxirgi test sanasi yangilandi.")


from gtts import gTTS
import os
import logging
import aiofiles # Asinxron fayl operatsiyalari uchun

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def generate_audio(text: str, lang: str = 'en'):
    """
    Berilgan matnni audio faylga aylantiradi va fayl yo'lini qaytaradi.
    """
    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        # Fayl nomini noyob qilish uchun
        audio_filename = f"audio_{text.replace(' ', '_')}_{os.urandom(4).hex()}.ogg"
        audio_path = os.path.join("audio_cache", audio_filename)

        # audio_cache papkasini yaratish (agar mavjud bo'lmasa)
        os.makedirs("audio_cache", exist_ok=True)

        # Asinxron ravishda faylni saqlash
        await tts.save(audio_path)
        logger.info(f"Audio fayl yaratildi: {audio_path}")
        return audio_path
    except Exception as e:
        logger.error(f"Audio yaratishda xato ({text}): {e}")
        return None

async def delete_audio_file(audio_path: str):
    """
    Yaratilgan audio faylni o'chiradi.
    """
    try:
        if audio_path and os.path.exists(audio_path):
            await aiofiles.os.remove(audio_path)
            logger.info(f"Audio fayl o'chirildi: {audio_path}")
    except Exception as e:
        logger.error(f"Audio faylni o'chirishda xato ({audio_path}): {e}")


import logging
import asyncio
from datetime import datetime, timedelta
import random
import os
# Webhook uchun yangi importlar
from aiohttp import web # HTTP server yaratish uchun
from aiogram.types import Update # Telegramdan keladigan update turi
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage, Redis
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart, Command
from aiogram.utils.markdown import hbold
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import BOT_TOKEN, REDIS_URL, WORDS_PER_DAY, PASS_PERCENTAGE, TEST_OPTIONS_COUNT
from aiogram.fsm.state import StatesGroup
from database import (
    init_db_pool, close_db_pool, create_tables, add_sample_words,
    get_or_create_user, get_words_for_user, get_user_test_words,
    get_random_words_for_options, update_user_word_progress,
    calculate_test_result, update_user_last_test_date, get_total_words_count
)
from tts_service import generate_audio, delete_audio_file

# Loglash sozlamalari
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Redis ulanishi
redis = Redis.from_url(REDIS_URL)
# Aiogram FSM storage
storage = RedisStorage(redis=redis)

# Bot va Dispatcher obyektlari

dp = Dispatcher(storage=storage)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
# Foydalanuvchi holatlari (FSM)
class UserState(StatesGroup):
    """
    Foydalanuvchi holatlari:
    - waiting_for_word_request: So'z olishni kutmoqda
    - in_test: Test jarayonida
    """
    waiting_for_word_request =State() 
    in_test = State()

@dp.message(CommandStart())
async def command_start_handler(message: types.Message, state: FSMContext) -> None:
    """
    /start komandasiga javob beradi.
    Foydalanuvchini bazaga qo'shadi va keyingi qadamni taklif qiladi.
    """
    telegram_id = message.from_user.id
    user = await get_or_create_user(telegram_id)
    await state.update_data(db_user_id=user['id'])

    await message.answer(
        f"Salom, {hbold(message.from_user.full_name)}! Til o'rganish botiga xush kelibsiz!\n\n"
        "Men sizga har kuni yangi inglizcha so'zlarni o'zbekcha tarjimasi bilan beraman. "
        "Ertasi kuni esa o'rgangan so'zlaringizni test qilaman.\n\n"
        "So'zlar olishni boshlash uchun /words buyrug'ini bosing."
    )
    await state.set_state(UserState.waiting_for_word_request)

@dp.message(Command("words"))
async def get_daily_words_handler(message: types.Message, state: FSMContext) -> None:
    """
    /words komandasiga javob beradi.
    Foydalanuvchiga kunlik so'zlarni beradi yoki testga yo'naltiradi.
    """
    user_data = await state.get_data()
    db_user_id = user_data.get('db_user_id')

    if not db_user_id:
        # Agar foydalanuvchi /start ni bosmagan bo'lsa
        await message.answer("Iltimos, avval /start buyrug'ini bosing.")
        return

    user = await get_or_create_user(message.from_user.id) # Foydalanuvchi ma'lumotlarini yangilash
    last_word_fetch_date = user['last_word_fetch_date']
    last_test_date = user['last_test_date']

    now = datetime.now()
    # So'zlar berish uchun 24 soat o'tgan bo'lishi kerak
    can_get_new_words = (last_word_fetch_date is None or
                         (now - last_word_fetch_date) > timedelta(hours=23)) # 23 soat qilib qo'ydim, biroz ertaroq testga tayyor bo'lishi uchun

    # Testga tayyor bo'lish uchun 24 soat o'tgan bo'lishi kerak
    is_test_due = (last_word_fetch_date is not None and
                   (now - last_word_fetch_date) > timedelta(hours=24) and
                   (last_test_date is None or (now - last_test_date) > timedelta(hours=23))) # Testdan keyin ham 23 soat kutish

    if is_test_due:
        # Test vaqti kelgan
        test_words = await get_user_test_words(db_user_id)
        if test_words:
            await message.answer("Sizning kechagi so'zlaringiz bo'yicha test vaqti keldi!")
            await start_test(message, state, test_words)
        else:
            await message.answer("Kechagi so'zlaringiz bo'yicha test topilmadi yoki barcha so'zlar o'rganilgan. Yangi so'zlar olishingiz mumkin.")
            await give_new_words(message, state, db_user_id)
    elif can_get_new_words:
        # Yangi so'zlar olish vaqti kelgan
        await give_new_words(message, state, db_user_id)
    else:
        # Hali vaqt kelmagan
        next_words_time = last_word_fetch_date + timedelta(hours=23)
        remaining_time = next_words_time - now
        hours, remainder = divmod(remaining_time.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        await message.answer(
            f"Sizga yangi so'zlar berish uchun hali vaqt kelmadi. "
            f"Taxminan {int(hours)} soat {int(minutes)} daqiqadan so'ng qayta urinib ko'ring."
        )


async def give_new_words(message: types.Message, state: FSMContext, db_user_id: int):
    """
    Foydalanuvchiga yangi 50 ta so'zni yuboradi.
    """
    words = await get_words_for_user(db_user_id, fetch_new=True)

    if not words:
        await message.answer("Lug'atda yangi so'zlar qolmadi yoki barcha so'zlar o'rganilgan!")
        return

    words_text = "Bugungi <b>50</b> ta yangi so'zlar:\n\n"
    for i, word in enumerate(words):
        words_text += f"<b>{i+1}. {word['english_word']}</b> - {word['uzbek_word']}\n"
    words_text += "\nUlarni o'rganishga harakat qiling! Ertaga test bo'ladi."

    await message.answer(words_text, parse_mode=ParseMode.HTML)
    await state.set_state(UserState.waiting_for_word_request) # So'zlar berilgandan keyin holatni tiklash

async def start_test(message: types.Message, state: FSMContext, test_words: list):
    """
    Testni boshlaydi.
    """
    await state.update_data(test_words=test_words, current_question_index=0, correct_answers_count=0)
    await state.set_state(UserState.in_test)
    await send_next_test_question(message, state)

async def send_next_test_question(message: types.Message, state: FSMContext):
    """
    Navbatdagi test savolini yuboradi.
    """
    user_data = await state.get_data()
    test_words = user_data.get('test_words')
    current_question_index = user_data.get('current_question_index')

    if current_question_index >= len(test_words):
        # Test tugadi
        await finish_test(message, state)
        return

    word_to_test = test_words[current_question_index]
    correct_word_id = word_to_test['id']
    english_word = word_to_test['english_word']
    uzbek_word = word_to_test['uzbek_word']

    # Savol turi: Inglizcha yoki O'zbekcha
    is_english_question = random.choice([True, False])

    if is_english_question:
        question_text = f"<b>'{english_word}'</b> so'zining o'zbekcha tarjimasini toping:"
        correct_answer = uzbek_word
        # Noto'g'ri variantlar uchun so'zlarni olish
        wrong_options_db = await get_random_words_for_options(correct_word_id, TEST_OPTIONS_COUNT - 1)
        wrong_options = [w['uzbek_word'] for w in wrong_options_db]
    else:
        question_text = f"<b>'{uzbek_word}'</b> so'zining inglizcha tarjimasini toping:"
        correct_answer = english_word
        # Noto'g'ri variantlar uchun so'zlarni olish
        wrong_options_db = await get_random_words_for_options(correct_word_id, TEST_OPTIONS_COUNT - 1)
        wrong_options = [w['english_word'] for w in wrong_options_db]

    options = [correct_answer] + wrong_options
    random.shuffle(options)

    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=option, callback_data=f"test_answer_{correct_word_id}_{option}_{correct_answer}")
    builder.adjust(1) # Har bir tugma alohida qatorda

    await message.answer(question_text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

    # Talaffuzni yuborish (agar inglizcha savol bo'lsa)
    if is_english_question and english_word:
        audio_path = await generate_audio(english_word, lang='en')
        if audio_path:
            with open(audio_path, 'rb') as audio_file:
                await bot.send_audio(message.chat.id, types.BufferedInputFile(audio_file.read(), filename=os.path.basename(audio_path)))
            await delete_audio_file(audio_path) # Faylni o'chirish


@dp.callback_query(UserState.in_test, F.data.startswith("test_answer_"))
async def process_test_answer_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Test javobini qayta ishlaydi.
    """
    await callback_query.answer() # Callback so'rovini yopish

    data_parts = callback_query.data.split('_')
    # Format: test_answer_{word_id}_{selected_answer}_{correct_answer}
    word_id = int(data_parts[2])
    selected_answer = data_parts[3]
    correct_answer = data_parts[4]

    user_data = await state.get_data()
    db_user_id = user_data.get('db_user_id')
    current_question_index = user_data.get('current_question_index')
    correct_answers_count = user_data.get('correct_answers_count')

    is_correct = (selected_answer == correct_answer)

    # Foydalanuvchi progressini yangilash
    await update_user_word_progress(db_user_id, word_id, is_correct)

    if is_correct:
        correct_answers_count += 1
        await callback_query.message.edit_text(
            f"✅ To'g'ri javob! Siz <b>'{selected_answer}'</b> ni tanladingiz.",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback_query.message.edit_text(
            f"❌ Noto'g'ri javob. Siz <b>'{selected_answer}'</b> ni tanladingiz. To'g'ri javob: <b>'{correct_answer}'</b>",
            parse_mode=ParseMode.HTML
        )

    # Keyingi savolga o'tish
    current_question_index += 1
    await state.update_data(current_question_index=current_question_index, correct_answers_count=correct_answers_count)

    await asyncio.sleep(1) # Foydalanuvchiga javobni ko'rishga imkon berish
    await send_next_test_question(callback_query.message, state)


async def finish_test(message: types.Message, state: FSMContext):
    """
    Testni yakunlaydi, natijalarni hisoblaydi va foydalanuvchiga xabar beradi.
    """
    user_data = await state.get_data()
    db_user_id = user_data.get('db_user_id')
    test_words = user_data.get('test_words')
    correct_answers_count = user_data.get('correct_answers_count')

    # Testdagi so'zlar ID'lari ro'yxati
    word_ids_in_test = [word['id'] for word in test_words]

    # Test natijasini hisoblash va bazani yangilash
    percentage = await calculate_test_result(db_user_id, word_ids_in_test)
    await update_user_last_test_date(db_user_id) # Oxirgi test sanasini yangilash

    if percentage >= PASS_PERCENTAGE:
        await message.answer(
            f"🎉 Tabriklaymiz! Siz testdan muvaffaqiyatli o'tdingiz! "
            f"Sizning natijangiz: <b>{percentage:.2f}%</b>. "
            f"Ertaga sizga yangi so'zlar beriladi.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer(
            f"😔 Afsuski, siz testdan o'ta olmadingiz. "
            f"Sizning natijangiz: <b>{percentage:.2f}%</b>. "
            f"O'tish uchun kamida {PASS_PERCENTAGE}% to'g'ri javob berish kerak edi. "
            f"Bugungi so'zlar qayta takrorlanadi. Ularni yaxshilab o'rganing va ertaga yana urinib ko'ring!",
            parse_mode=ParseMode.HTML
        )
    await state.set_state(UserState.waiting_for_word_request) # Holatni tiklash

@dp.message()
async def echo_handler(message: types.Message, state: FSMContext) -> None:
    """
    Boshqa barcha xabarlarga javob beradi (agar boshqa handler topilmasa).
    """
    current_state = await state.get_state()
    if current_state == UserState.waiting_for_word_request:
        await message.answer("Men sizni tushunmadim. Yangi so'zlar olish uchun /words buyrug'ini bosing.")
    elif current_state == UserState.in_test:
        await message.answer("Iltimos, test savoliga javob berish uchun tugmalardan foydalaning.")
    else:
        await message.answer("Iltimos, botni ishga tushirish uchun /start buyrug'ini bosing.")


async def main() -> None:
    """
    Botni ishga tushirish uchun asosiy funksiya.
    """
    logger.info("Bot ishga tushirilmoqda...")
    await init_db_pool() # Ma'lumotlar bazasi ulanishini ishga tushirish
    await create_tables() # Jadvallarni yaratish (agar mavjud bo'lmasa)

    # Agar lug'atda so'zlar bo'lmasa, namunaviy so'zlarni qo'shish
    words_count = await get_total_words_count()
    if words_count < WORDS_PER_DAY * 2: # Kamida 2 kunlik so'z bo'lishi kerak
        logger.info("Lug'atda yetarli so'zlar yo'q, namunaviy so'zlar qo'shilmoqda...")
        await add_sample_words()

    # Botni polling rejimida ishga tushirish
    try:
        await dp.start_polling(bot)
    finally:
        await close_db_pool() # Bot to'xtaganda ma'lumotlar bazasi ulanishini yopish
        await redis.close() # Redis ulanishini yopish
        logger.info("Bot to'xtatildi.")
async def on_startup(dispatcher: Dispatcher, bot_obj: Bot, webhook_url: str):
    """
    Bot ishga tushganda bajariladigan funksiya.
    Webhookni o'rnatadi.
    """
    logger.info("Bot ishga tushirilmoqda (Webhook)...")
    await init_db_pool() # Ma'lumotlar bazasi ulanishini ishga tushirish
    await create_tables() # Jadvallarni yaratish (agar mavjud bo'lmasa)

    # Agar lug'atda so'zlar bo'lmasa, namunaviy so'zlarni qo'shish
    words_count = await get_total_words_count()
    if words_count < WORDS_PER_DAY * 2:
        logger.info("Lug'atda yetarli so'zlar yo'q, namunaviy so'zlar qo'shilmoqda...")
        await add_sample_words()

    await bot_obj.set_webhook(webhook_url)
    logger.info(f"Webhook o'rnatildi: {webhook_url}")

async def on_shutdown(dispatcher: Dispatcher, bot_obj: Bot):
    """
    Bot to'xtaganda bajariladigan funksiya.
    Webhookni o'chiradi va DB ulanishini yopadi.
    """
    logger.info("Bot to'xtatilmoqda (Webhook)...")
    await bot_obj.delete_webhook()
    await close_db_pool()
    await redis.close()
    logger.info("Webhook o'chirildi va resurslar yopildi.")

async def webhook_handler(request: web.Request):
    """
    Telegramdan kelgan Webhook so'rovlarini qayta ishlaydi.
    """
    if request.match_info.get('token') == BOT_TOKEN:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
        return web.Response()
    else:
        raise web.HTTPUnauthorized()

async def main_webhook():
    """
    Webhook rejimida botni ishga tushirish uchun asosiy funksiya.
    """
    # Render.com tomonidan berilgan PORT va URL'ni olish
    # Render avtomatik ravishda $PORT ni beradi
    WEB_SERVER_HOST = '0.0.0.0'
    WEB_SERVER_PORT = os.getenv("PORT") # Render tomonidan beriladi
    WEBHOOK_PATH = f'/webhook/{BOT_TOKEN}' # Har xil botlar uchun noyob yo'l
    WEBHOOK_URL = os.getenv("WEBHOOK_URL") # Render.com domen nomini beradi

    if not WEBHOOK_URL:
        # Lokal test uchun yoki boshqa holatda
        WEBHOOK_URL = "http://localhost" # Test uchun Placeholder
        logger.warning("RENDER_EXTERNAL_HOSTNAME topilmadi, lokal URL ishlatilmoqda.")

    WEBHOOK_URL = f"https://{WEBHOOK_URL}{WEBHOOK_PATH}" if "https" not in WEBHOOK_URL else f"{WEBHOOK_URL}{WEBHOOK_PATH}"

    # Botni ishga tushganda va to'xtaganda chaqiriladigan funksiyalarni ro'yxatdan o'tkazish
    dp.startup.register(lambda: on_startup(dp, bot, WEBHOOK_URL))
    dp.shutdown.register(lambda: on_shutdown(dp, bot))

    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)

    # Webhook serverini ishga tushirish
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()
    logger.info(f"Webhook server {WEB_SERVER_HOST}:{WEB_SERVER_PORT} da ishga tushdi.")

    # Server doimiy ishlashi uchun cheksiz tsikl
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main_webhook()) # Asosiy funksiyani o'zgartirdik
    except KeyboardInterrupt:
        logger.info("Bot qo'lda to'xtatildi.")
    except Exception as e:
        logger.error(f"Bot ishga tushirishda kutilmagan xato: {e}")


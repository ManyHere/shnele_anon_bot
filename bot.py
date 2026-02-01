from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import asyncio
import sqlite3

TOKEN = "your_bot_token"
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

waiting_users = []           # очередь ожидания
active_chats = {}            # активные чаты: user_id -> partner_id
lock = asyncio.Lock()        # блокировка

# --- SQLite ---
DB_PATH = "users.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    messages_count INTEGER DEFAULT 0
)
""")
conn.commit()

def increment_message_count(user_id):
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def get_message_count(user_id):
    cursor.execute("SELECT messages_count FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

# --- Клавиатуры ---
def keyboard_start():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Начать общение")
    return kb

def keyboard_waiting():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Остановить поиск")
    return kb

def keyboard_active():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Остановить диалог")
    kb.add("Следующий собеседник")
    return kb

# --- Логика чата ---
async def connect_user(user_id):
    async with lock:
        # Если уже есть в очереди, ничего не делаем
        if user_id in waiting_users:
            await bot.send_message(user_id, "Ты уже ожидаешь собеседника.", reply_markup=keyboard_waiting())
            return

        if waiting_users:
            partner_id = waiting_users.pop(0)
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id

            await bot.send_message(user_id, "Подключен к собеседнику!", reply_markup=keyboard_active())
            await bot.send_message(partner_id, "Подключен к собеседнику!", reply_markup=keyboard_active())
        else:
            waiting_users.append(user_id)
            await bot.send_message(user_id, "Ожидание собеседника...", reply_markup=keyboard_waiting())

async def disconnect_user(user_id, notify=True):
    async with lock:
        # Разрыв активного чата
        partner_id = active_chats.pop(user_id, None)
        if partner_id:
            active_chats.pop(partner_id, None)
            if notify:
                await bot.send_message(partner_id, "Собеседник остановил диалог.",
                                       reply_markup=keyboard_start())
            await bot.send_message(user_id, "Диалог завершён.", reply_markup=keyboard_start())

        # Удаление из очереди ожидания
        if user_id in waiting_users:
            waiting_users.remove(user_id)
            await bot.send_message(user_id, "Поиск собеседника остановлен.", reply_markup=keyboard_start())

# --- Команды ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(
        "Добро пожаловать в анонимный чат!\nНажми кнопку 'Начать общение', чтобы подключиться.",
        reply_markup=keyboard_start()
    )

@dp.message_handler(commands=['stop'])
async def stop_command(message: types.Message):
    await disconnect_user(message.from_user.id)

@dp.message_handler(commands=['next'])
async def next_command(message: types.Message):
    await disconnect_user(message.from_user.id, notify=False)
    await connect_user(message.from_user.id)

@dp.message_handler(commands=['stats'])
async def stats(message: types.Message):
    count = get_message_count(message.from_user.id)
    await message.answer(f"Ты отправил всего {count} сообщений в этом боте.")

# --- Кнопки ReplyKeyboard ---
@dp.message_handler(lambda m: m.text == "Начать общение")
async def start_chat_button(message: types.Message):
    await connect_user(message.from_user.id)

@dp.message_handler(lambda m: m.text == "Остановить поиск")
async def stop_search_button(message: types.Message):
    await disconnect_user(message.from_user.id)

@dp.message_handler(lambda m: m.text == "Остановить диалог")
async def stop_chat_button(message: types.Message):
    await disconnect_user(message.from_user.id)

@dp.message_handler(lambda m: m.text == "Следующий собеседник")
async def next_chat_button(message: types.Message):
    await disconnect_user(message.from_user.id, notify=False)
    await connect_user(message.from_user.id)

# --- Обработка любых сообщений ---
@dp.message_handler(content_types=types.ContentType.ANY)
async def handle_message(message: types.Message):
    user_id = message.from_user.id

    # Команды не пересылаем
    if message.text and message.text.startswith('/'):
        return

    increment_message_count(user_id)
    partner_id = active_chats.get(user_id)

    if not partner_id:
        await message.answer(
            "Собеседник пока не подключен.\nНажми 'Начать общение', чтобы подключиться.",
            reply_markup=keyboard_start()
        )
        return

    # Пересылка мультимедиа
    content_type = message.content_type
    try:
        if content_type == 'text':
            await bot.send_message(partner_id, message.text)
        elif content_type == 'photo':
            await bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
        elif content_type == 'video':
            await bot.send_video(partner_id, message.video.file_id, caption=message.caption)
        elif content_type == 'voice':
            await bot.send_voice(partner_id, message.voice.file_id)
        elif content_type == 'sticker':
            await bot.send_sticker(partner_id, message.sticker.file_id)
        elif content_type == 'audio':
            await bot.send_audio(partner_id, message.audio.file_id)
        elif content_type == 'document':
            await bot.send_document(partner_id, message.document.file_id)
        else:
            await bot.send_message(partner_id, f"Получено сообщение (тип: {content_type})")
    except Exception as e:
        print(f"Ошибка пересылки: {e}")

# --- Запуск ---
if __name__ == "__main__":
    print("Бот работает исправно")
    executor.start_polling(dp, skip_updates=True)

import sys
import asyncio
import logging
import re

# Event loop sozlamasi
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiogram import Bot, Dispatcher, F, html
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pyrogram import Client
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import SessionPasswordNeeded, FloodWait

import config
import database

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# --- FSM HOLATLARI ---
class UserbotAuth(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()

class MailingState(StatesGroup):
    waiting_for_text = State()
    waiting_for_loop = State()
    waiting_for_edit_text = State()

class TagState(StatesGroup):
    waiting_for_text = State()
    waiting_for_limit = State()
    waiting_for_edit_text = State()

# --- GLOBAL LUG'ATLAR ---
active_auth_clients = {}
running_userbots = {}
mailing_jobs = {}
tag_jobs = {}


def escape_markdown_v1(text: str) -> str:
    """Markdown formatlashda xatolik bermasligi uchun maxsus belgilarni tozalash"""
    return re.sub(r'([\[\]\(\)\*\_`])', r'\\\1', text)


async def start_userbot_worker(user_id: int, session_string: str):
    if user_id in running_userbots:
        return
    client = Client(
        name=f"worker_{user_id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session_string,
        no_updates=True  # Background update xatoliklarini to'xtatish
    )
    await client.start()
    running_userbots[user_id] = client
    logging.info(f"Userbot worker muvaffaqiyatli yoqildi: {user_id}")


def get_main_keyboard(user_id: int):
    buttons = [
        [KeyboardButton(text="⚙️ Userbot menyusi")],
        [KeyboardButton(text="📚 Qo'llanma")]
    ]
    if int(user_id) == int(config.ADMIN_ID):
        buttons.append([KeyboardButton(text="📊 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Assalomu alaykum, {html.bold(message.from_user.full_name)}! 👋\n\n"
        "Men profilingiz nomidan guruhlarga xabar yuboruvchi va a'zolarni otmetka qiluvchi botman.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )


@dp.message(F.text == "⚙️ Userbot menyusi")
async def userbot_menu(message: Message):
    user_id = message.from_user.id
    if user_id in running_userbots:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🚀 Guruhga xabar jo'natish")],
                [KeyboardButton(text="🏷 Userni belgilash")],
                [KeyboardButton(text="❌ Userbotni o'chirish")],
                [KeyboardButton(text="⬅️ Orqaga")]
            ],
            resize_keyboard=True
        )
        await message.answer("✅ Sizning userbotingiz faol holatda. Quyidagi bo'limni tanlang:", reply_markup=keyboard)
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Userbotni ulash")], [KeyboardButton(text="⬅️ Orqaga")]],
            resize_keyboard=True
        )
        await message.answer("Sizda hali userbot ulanmagan. Profilingizni ulashingiz mumkin:", reply_markup=keyboard)


# --- GURUHGA XABAR YUBORISH (MAILING) ---
@dp.message(F.text == "🚀 Guruhga xabar jo'natish")
async def start_mailing_process(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in running_userbots:
        await message.answer("Avval userbotni ulashingiz kerak!")
        return
    
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        try: await message.delete()
        except Exception: pass

    await bot.send_message(user_id, "1️⃣ Guruhga yubormoqchi bo'lgan **matningizni** kiriting:", parse_mode="markdown")
    await state.set_state(MailingState.waiting_for_text)


@dp.message(MailingState.waiting_for_text)
async def process_mailing_text(message: Message, state: FSMContext):
    await state.update_data(mailing_text=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Cheksiz yuborish", callback_data="loop_infinite")]
    ])
    await message.answer(
        "2️⃣ Xabar nechta yuborilsin? \n\n"
        "Son kiriting (masalan: `10`, `50`) yoki quyidagi **Cheksiz yuborish** tugmasini bosing:",
        reply_markup=keyboard,
        parse_mode="markdown"
    )
    await state.set_state(MailingState.waiting_for_loop)


@dp.callback_query(F.data == "loop_infinite", MailingState.waiting_for_loop)
async def process_infinite_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(loop_count="infinite")
    await callback.answer()
    await ask_for_groups(callback.message, state, mode="mail")


@dp.message(MailingState.waiting_for_loop)
async def process_loop_count_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Iltimos, faqat butun son kiriting yoki tugmani bosing!")
        return
    await state.update_data(loop_count=int(text))
    await ask_for_groups(message, state, mode="mail")


# --- USERNI BELGILASH (TAG) ---
@dp.message(F.text == "🏷 Userni belgilash")
async def start_tag_process(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in running_userbots:
        await message.answer("Avval userbotni ulashingiz kerak!")
        return
    
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        try: await message.delete()
        except Exception: pass

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Matnsiz (O'tkazib yuborish)", callback_data="skip_tag_text")]
    ])
    await bot.send_message(
        user_id,
        "1️⃣ Atmetka bilan birga yuboriladigan **sarlavha matnini** kiriting:\n\n"
        "_(Agar sarlavha kerak bo'lmasa, pastdagi tugmani bosing)_",
        reply_markup=keyboard,
        parse_mode="markdown"
    )
    await state.set_state(TagState.waiting_for_text)


@dp.callback_query(F.data == "skip_tag_text", TagState.waiting_for_text)
async def skip_tag_text_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(tag_text="NO_TEXT")
    await callback.answer()
    await ask_tag_limit(callback.message, state)


@dp.message(TagState.waiting_for_text)
async def process_tag_text(message: Message, state: FSMContext):
    await state.update_data(tag_text=message.text)
    await ask_tag_limit(message, state)


async def ask_tag_limit(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Hammani belgilash", callback_data="tag_all_users")]
    ])
    await message.answer(
        "2️⃣ Nechta user atmetka qilinsin?\n\n"
        "Son kiriting (masalan: `10`, `50`) yoki hammani atmetka qilish uchun quyidagi tugmani bosing:",
        reply_markup=keyboard,
        parse_mode="markdown"
    )
    await state.set_state(TagState.waiting_for_limit)


@dp.callback_query(F.data == "tag_all_users", TagState.waiting_for_limit)
async def tag_all_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(tag_limit="all")
    await callback.answer()
    await ask_for_groups(callback.message, state, mode="tag")


@dp.message(TagState.waiting_for_limit)
async def process_tag_limit(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Iltimos, faqat butun son kiriting yoki tugmani bosing!")
        return
    await state.update_data(tag_limit=int(text))
    await ask_for_groups(message, state, mode="tag")


async def ask_for_groups(message: Message, state: FSMContext, mode="mail"):
    user_id = message.chat.id
    cl = running_userbots[user_id]
    
    await message.answer("🔄 Profilingizdagi guruhlar yuklanmoqda...")
    
    inline_keyboard = []
    prefix = "send_to_" if mode == "mail" else "tag_to_"
    try:
        async for dialog in cl.get_dialogs(limit=100):
            if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                title = dialog.chat.title[:25]
                inline_keyboard.append([InlineKeyboardButton(text=f"👥 {title}", callback_data=f"{prefix}{dialog.chat.id}")])
    except Exception as e:
        await message.answer(f"Guruhlarni yuklashda xatolik yuz berdi: {e}")
        await state.clear()
        return

    if not inline_keyboard:
        await message.answer("Profilingizda hech qanday guruh topilmadi.")
        await state.clear()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer("3️⃣ Amaliyot bajarilishi kerak bo'lgan guruhingizni tanlang:", reply_markup=keyboard)


def get_control_panel(status="running", job_type="mail"):
    buttons = []
    prefix = "mail_" if job_type == "mail" else "tag_"
    
    if status == "running":
        buttons.append(InlineKeyboardButton(text="⏸ Pause", callback_data=f"{prefix}pause"))
    elif status == "paused":
        buttons.append(InlineKeyboardButton(text="▶️ Resume", callback_data=f"{prefix}resume"))
        
    buttons.append(InlineKeyboardButton(text="🛑 Stop", callback_data=f"{prefix}stop"))
    buttons.append(InlineKeyboardButton(text="📝 Edit Message", callback_data=f"{prefix}edit"))
    
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


# --- BACKGROUND TASKS ---
@dp.callback_query(F.data.startswith("send_to_"))
async def start_mailing_job(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_chat_id = int(callback.data.split("_")[2])
    
    data = await state.get_data()
    mailing_text = data.get("mailing_text")
    loop_count = data.get("loop_count")
    await state.clear()
    
    if not mailing_text or loop_count is None:
        await callback.answer("❌ Seans eskirgan. Qaytadan urinib ko'ring.", show_alert=True)
        return

    if user_id in mailing_jobs:
        mailing_jobs[user_id]["status"] = "stopped"

    mailing_jobs[user_id] = {
        "status": "running",
        "text": mailing_text,
        "loop_count": loop_count,
        "chat_id": target_chat_id,
        "current_step": 0
    }
    
    await callback.message.answer(
        f"🚀 **Xabar yuborish boshlandi!**\n\nMatn: `{mailing_text}`\nLimit: `{loop_count}`",
        reply_markup=get_control_panel("running", "mail"),
        parse_mode="markdown"
    )
    await callback.answer()
    asyncio.create_task(background_mailing_task(user_id))


async def background_mailing_task(user_id: int):
    cl = running_userbots[user_id]
    
    while user_id in mailing_jobs:
        job = mailing_jobs[user_id]
        
        if job["status"] == "stopped":
            del mailing_jobs[user_id]
            break
            
        if job["status"] == "paused":
            await asyncio.sleep(0.5)
            continue
            
        loop_count = job.get("loop_count")
        if loop_count != "infinite" and isinstance(loop_count, int) and job["current_step"] >= loop_count:
            await bot.send_message(user_id, "✅ **Belgilangan miqdordagi xabarlar yuborib bo'lindi!**")
            del mailing_jobs[user_id]
            break
            
        try:
            await cl.send_message(job["chat_id"], job["text"])
            job["current_step"] += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            await bot.send_message(user_id, f"⚠️ Xabar yuborishda xatolik: {e}")
            del mailing_jobs[user_id]
            break
            
        # HAR 1 SONIYADA 1 TA XABAR:
        await asyncio.sleep(1.0)


@dp.callback_query(F.data.startswith("tag_to_"))
async def start_tagging_job(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_chat_id = int(callback.data.split("_")[2])
    
    data = await state.get_data()
    tag_text = data.get("tag_text")
    tag_limit = data.get("tag_limit")
    await state.clear()
    
    if tag_text is None or tag_limit is None:
        await callback.answer("❌ Seans eskirgan. Qaytadan urinib ko'ring.", show_alert=True)
        return

    if user_id in tag_jobs:
        tag_jobs[user_id]["status"] = "stopped"

    tag_jobs[user_id] = {
        "status": "running",
        "text": "" if tag_text == "NO_TEXT" else tag_text,
        "limit": tag_limit,
        "chat_id": target_chat_id,
        "current_step": 0
    }
    
    display_text = "Matnsiz (Faqat Nik/Username)" if tag_text == "NO_TEXT" else tag_text
    display_limit = "Hammasi" if tag_limit == "all" else f"{tag_limit} ta"
    
    await callback.message.answer(
        f"⚡️ **Belgilash boshlandi (Tezlik: 1 sek/msg)!**\n\nSarlavha: `{display_text}`\nLimit: `{display_limit}`",
        reply_markup=get_control_panel("running", "tag"),
        parse_mode="markdown"
    )
    await callback.answer()
    asyncio.create_task(background_tagging_task(user_id))


async def background_tagging_task(user_id: int):
    cl = running_userbots[user_id]
    
    if user_id not in tag_jobs:
        return

    job = tag_jobs[user_id]
    chat_id = job["chat_id"]
    limit = job["limit"]
    
    try:
        me = await cl.get_me()
        
        # A'zolarni saralash
        members = []
        async for member in cl.get_chat_members(chat_id):
            if member.user and not member.user.is_bot and not member.user.is_deleted:
                if member.user.id != me.id:
                    members.append(member.user)

        if isinstance(limit, int):
            members = members[:limit]

        for u in members:
            if user_id not in tag_jobs or tag_jobs[user_id]["status"] == "stopped":
                await bot.send_message(user_id, "🛑 **Belgilash jarayoni to'xtatildi.**")
                if user_id in tag_jobs: del tag_jobs[user_id]
                return

            while user_id in tag_jobs and tag_jobs[user_id]["status"] == "paused":
                await asyncio.sleep(0.5)

            # USERNAME BOR BO'LSA - USERNAME, YO'Q BO'LSA - ISMI (NIKI) BILAN ATMETKA
            if u.username:
                tag_mention = f"@{u.username}"
            else:
                clean_name = escape_markdown_v1(u.first_name or "Foydalanuvchi")
                tag_mention = f"[{clean_name}](tg://user?id={u.id})"

            header = tag_jobs[user_id]["text"]
            msg_text = f"📢 **{header}**\n\n{tag_mention}" if header else tag_mention

            try:
                await cl.send_message(chat_id, msg_text.strip(), parse_mode=ParseMode.MARKDOWN)
                job["current_step"] += 1
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                logging.error(f"Tag yuborishda xato: {e}")

            # HAR 1 SONIYADA 1 TA ATMETKA MESSAGE:
            await asyncio.sleep(1.0)

        await bot.send_message(
            user_id, 
            f"⚡️ **A'zolar muvaffaqiyatli belgilandi!**\nJami: `{job['current_step']}` ta foydalanuvchi otmetka qilindi.",
            parse_mode="markdown"
        )

    except Exception as e:
        await bot.send_message(user_id, f"⚠️ Belgilashda xatolik yuz berdi: {e}")

    if user_id in tag_jobs:
        del tag_jobs[user_id]


# --- TUGMA WORKERLARI ---
@dp.callback_query(F.data.in_({"mail_pause", "tag_pause"}))
async def action_pause(callback: CallbackQuery):
    user_id = callback.from_user.id
    job_type = "mail" if callback.data == "mail_pause" else "tag"
    jobs_dict = mailing_jobs if job_type == "mail" else tag_jobs
    
    if user_id in jobs_dict:
        jobs_dict[user_id]["status"] = "paused"
        await callback.message.edit_reply_markup(reply_markup=get_control_panel("paused", job_type))
        await callback.answer("Jarayon pauzaga qo'yildi.")
    else:
        await callback.answer("Faol jarayon topilmadi.", show_alert=True)


@dp.callback_query(F.data.in_({"mail_resume", "tag_resume"}))
async def action_resume(callback: CallbackQuery):
    user_id = callback.from_user.id
    job_type = "mail" if callback.data == "mail_resume" else "tag"
    jobs_dict = mailing_jobs if job_type == "mail" else tag_jobs
    
    if user_id in jobs_dict:
        jobs_dict[user_id]["status"] = "running"
        await callback.message.edit_reply_markup(reply_markup=get_control_panel("running", job_type))
        await callback.answer("Jarayon davom ettirilmoqda...")
    else:
        await callback.answer("Faol jarayon topilmadi.", show_alert=True)


@dp.callback_query(F.data.in_({"mail_stop", "tag_stop"}))
async def action_stop(callback: CallbackQuery):
    user_id = callback.from_user.id
    job_type = "mail" if callback.data == "mail_stop" else "tag"
    jobs_dict = mailing_jobs if job_type == "mail" else tag_jobs
    
    if user_id in jobs_dict:
        jobs_dict[user_id]["status"] = "stopped"
        await callback.message.edit_text("🛑 **Jarayon to'xtatildi.**")
        await callback.answer("To'xtatildi.")
    else:
        await callback.answer("Faol jarayon topilmadi.", show_alert=True)


@dp.callback_query(F.data.in_({"mail_edit", "tag_edit"}))
async def action_edit_request(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    job_type = "mail" if callback.data == "mail_edit" else "tag"
    jobs_dict = mailing_jobs if job_type == "mail" else tag_jobs
    
    if user_id not in jobs_dict:
        await callback.answer("Faol jarayon topilmadi.", show_alert=True)
        return
        
    await callback.message.answer("📝 Yangi matnni kiriting:")
    if job_type == "mail":
        await state.set_state(MailingState.waiting_for_edit_text)
    else:
        await state.set_state(TagState.waiting_for_edit_text)
    await callback.answer()


@dp.message(MailingState.waiting_for_edit_text)
async def process_edited_mail_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in mailing_jobs:
        mailing_jobs[user_id]["text"] = message.text
        await message.answer("✅ **Xabar matni yangilandi!**")
    else:
        await message.answer("Tahrirlashga faol sikl topilmadi.")
    await state.clear()


@dp.message(TagState.waiting_for_edit_text)
async def process_edited_tag_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in tag_jobs:
        tag_jobs[user_id]["text"] = message.text
        await message.answer("✅ **Atmetka sarlavhasi yangilandi!**")
    else:
        await message.answer("Tahrirlashga faol sikl topilmadi.")
    await state.clear()


# --- AUTHENTICATION VA ADMIN PANEL ---
@dp.message(F.text == "📱 Userbotni ulash")
async def start_auth(message: Message, state: FSMContext):
    await message.answer("Iltimos, Telegram raqamingizni kiriting:\nFormat: `+998901234567`", parse_mode="markdown")
    await state.set_state(UserbotAuth.waiting_for_phone)


@dp.message(UserbotAuth.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    await state.update_data(phone=phone)
    await message.answer("Telegramdan tasdiqlash kodi so'ralmoqda...")
    client = Client(
        name=f"auth_{message.from_user.id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        in_memory=True,
        no_updates=True
    )
    await client.connect()
    try:
        code_info = await client.send_code(phone)
        active_auth_clients[message.from_user.id] = {"client": client, "phone_code_hash": code_info.phone_code_hash}
        await message.answer("⚠️ **Kodni raqamlar orasiga nuqta qo'yib yuboring!** (Masalan: `5.4.3.2.1`)", parse_mode="markdown")
        await state.set_state(UserbotAuth.waiting_for_code)
    except Exception as e:
        await message.answer(f"Xatolik: {str(e)}")
        await client.disconnect()
        await state.clear()


@dp.message(UserbotAuth.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    user_id = message.from_user.id
    code = message.text.strip().replace(".", "").replace(" ", "").replace("-", "")
    if user_id not in active_auth_clients:
        await state.clear()
        return
    data = await state.get_data()
    phone = data['phone']
    client = active_auth_clients[user_id]["client"]
    phone_code_hash = active_auth_clients[user_id]["phone_code_hash"]
    try:
        await client.sign_in(phone, phone_code_hash, code)
        session_string = await client.export_session_string()
        database.save_session(user_id, phone, session_string)
        await message.answer("✅ Userbot muvaffaqiyatli ulandi va faollashtirildi!", reply_markup=get_main_keyboard(user_id))
        await start_userbot_worker(user_id, session_string)
        await client.disconnect()
        del active_auth_clients[user_id]
        await state.clear()
    except SessionPasswordNeeded:
        await message.answer("2FA parolingizni kiriting:")
        await state.set_state(UserbotAuth.waiting_for_password)
    except Exception:
        await message.answer("Kod noto'g'ri. Qaytadan kiriting:")


@dp.message(UserbotAuth.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()
    client = active_auth_clients[user_id]["client"]
    data = await state.get_data()
    phone = data['phone']
    try:
        await client.check_password(password)
        session_string = await client.export_session_string()
        database.save_session(user_id, phone, session_string)
        await message.answer("✅ Userbot muvaffaqiyatli ulandi.", reply_markup=get_main_keyboard(user_id))
        await start_userbot_worker(user_id, session_string)
        await client.disconnect()
        del active_auth_clients[user_id]
        await state.clear()
    except Exception:
        await message.answer("Noto'g'ri parol. Qayta urinib ko'ring:")


@dp.message(F.text == "❌ Userbotni o'chirish")
async def stop_userbot(message: Message):
    user_id = message.from_user.id
    if user_id in running_userbots:
        try: await running_userbots[user_id].stop()
        except Exception: pass
        del running_userbots[user_id]
        database.delete_session(user_id)
        await message.answer("Userbot o'chirildi.", reply_markup=get_main_keyboard(user_id))


@dp.message(F.text == "📊 Admin Panel")
async def admin_panel(message: Message):
    if int(message.from_user.id) != int(config.ADMIN_ID): 
        return
    total_users = database.get_users_count()
    users_list = database.get_users_list()
    response_text = f"📊 **Admin Panel:**\n👥 Jami ulanganlar: `{total_users}` ta\n\n📝 **Ro'yxat:**\n"
    if users_list:
        for idx, (u_id, phone) in enumerate(users_list, 1):
            response_text += f"{idx}. ID: `{u_id}` | Raqam: `{phone}`\n"
    else:
        response_text += "_Hozircha hech kim ulanmagan._"
    await message.answer(response_text, parse_mode="markdown")


@dp.message(F.text == "📚 Qo'llanma")
async def cmd_guide(message: Message):
    await message.answer(
        "📚 **Qo'llanma:**\n\n"
        "1. **Userbot menyusi** orqali raqamingizni ulang (Kodni nuqta bilan yuboring).\n"
        "2. **Guruhga xabar jo'natish** — Matn va sonini kiritib guruhga yuborasiz.\n"
        "3. **Userni belgilash** — Har bir a'zoga alohida soniyasiga 1 tadan otmetka qiladi.\n"
        "4. Jarayon davomida **Pause, Resume, Stop, Edit** tugmalari bilan boshqarishingiz mumkin.",
        parse_mode="markdown"
    )


@dp.message(F.text == "⬅️ Orqaga")
async def cmd_back(message: Message, state: FSMContext):
    await cmd_start(message, state)


async def on_startup():
    database.init_db()
    for user_id, session_string in database.get_all_sessions():
        try:
            await start_userbot_worker(user_id, session_string)
        except Exception as e:
            logging.error(f"Sessiyani yuklashda xato (User {user_id}): {e}")


async def main():
    await on_startup()
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")
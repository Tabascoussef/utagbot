import sys
import asyncio
import logging
import re

# Python 3.10+ va 3.14 yadroviy o'zgarishi: pyrogram sync moduli import qilinishidan oldin event loop bo'lishi shart
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
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import SessionPasswordNeeded, FloodWait
from pyrogram.types import (
    InlineKeyboardMarkup as PyroInlineKeyboardMarkup,
    InlineKeyboardButton as PyroInlineKeyboardButton
)

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

class GroupTagSession(StatesGroup):
    waiting_for_text = State()
    waiting_for_limit = State()

# --- GLOBAL LUG'ATLAR ---
active_auth_clients = {}
running_userbots = {}
mailing_jobs = {}
tag_jobs = {}

# Guruhdagi faol seanslar: group_sessions[chat_id] = {"caller_id": int, "caller_name": str, "text": str, "limit": val}
group_sessions = {}


def escape_markdown_v1(text: str) -> str:
    """Markdown formatlashda xatolik bermasligi uchun maxsus belgilarni tozalash"""
    if not text:
        return ""
    return re.sub(r'([\[\]\(\)\*\_`])', r'\\\1', str(text))


def get_group_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Matn biriktirish", callback_data="gtag_text")],
        [InlineKeyboardButton(text="🔢 Limit belgilash", callback_data="gtag_limit")],
        [InlineKeyboardButton(text="🚀 Otmetkani boshlash", callback_data="gtag_start")],
        [InlineKeyboardButton(text="🛑 To'xtatish", callback_data="gtag_stop")]
    ])


async def start_userbot_worker(user_id: int, session_string: str):
    if user_id in running_userbots:
        return

    client = Client(
        name=f"worker_{user_id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session_string,
        no_updates=False
    )

    # GURUHDA ;utag CHAQRILGANDA ISHLAYDIGAN HANDLER
    @client.on_message(filters.group & filters.command(["utag"], prefixes=";"))
    async def handle_semicolon_utag(cl: Client, message):
        sender_id = message.from_user.id if message.from_user else None
        chat_id = message.chat.id
        chat_title = message.chat.title or "Guruh"

        if not sender_id or sender_id not in running_userbots:
            return

        # Tekshiruv: Faqat faoliyat olib borayotgan tegishli userbot javob berishi kerak
        try:
            me = await cl.get_me()
            if sender_id != me.id:
                return
        except Exception as e:
            logging.error(f"Userbot ma'lumotlarini olishda xato: {e}")
            return

        # Guruhdagi ;utag xabarini o'chirish
        try:
            await message.delete()
        except Exception:
            pass

        # Guruh seansini saqlash
        group_sessions[chat_id] = {
            "caller_id": sender_id,
            "caller_name": message.from_user.first_name or "Foydalanuvchi",
            "text": "",
            "limit": "all"
        }

        safe_chat_title = escape_markdown_v1(chat_title)
        safe_first_name = escape_markdown_v1(message.from_user.first_name or "Foydalanuvchi")

        # Boshqaruv menyusini GURUHGA yuborish
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚙️ **{safe_chat_title}** uchun otmetka menyusi\n"
                    f"👤 Buyruq beruvchi: [{safe_first_name}](tg://user?id={sender_id})\n\n"
                    f"📌 **Joriy sozlama:**\n"
                    f"• Sarlavha: `Matnsiz`\n"
                    f"• Limit: `Hammasi`\n\n"
                    f"🔒 *Ushbu menyu tugmalaridan faqat {safe_first_name} foydalana oladi!*"
                ),
                reply_markup=get_group_menu_keyboard(),
                parse_mode="markdown"
            )
        except Exception as e:
            logging.error(f"Guruhga menyu yuborishda xato: {e}")
            
            # Bot username'ini aniqlash va PYROGRAM tugmasini yaratish
            try:
                bot_info = await bot.get_me()
                add_to_group_kb = PyroInlineKeyboardMarkup([
                    [PyroInlineKeyboardButton(
                        text="➕ Botni guruhga qo'shish", 
                        url=f"https://t.me/{bot_info.username}?startgroup=true"
                    )]
                ])
                
                # Userbot orqali tugmali ogohlantirish yuborish
                await cl.send_message(
                    chat_id,
                    "⚠️ **Menyu chiqishi uchun rasmiy botga guruhda xabar yuborish huquqini bering yoki uni Admin qiling!**\n\n"
                    "Tugma orqali botni guruhga qayta qo'shishingiz/sozlamasini yangilashingiz mumkin 👇",
                    reply_markup=add_to_group_kb
                )
            except Exception as ex:
                logging.error(f"Userbot orqali ogohlantirish yuborishda xato: {ex}")

    try:
        await client.start()
    except Exception as e:
        logging.error(f"Userbot worker start xatosi (User {user_id}): {e}")
        return

    try:
        async for _ in client.get_dialogs(limit=50):
            pass
    except Exception:
        pass

    running_userbots[user_id] = client
    logging.info(f"Userbot worker muvaffaqiyatli yoqildi: {user_id}")


def get_main_keyboard(user_id: int):
    buttons = [
        [KeyboardButton(text="🚀 Guruhga xabar jo'natish"), KeyboardButton(text="🏷 Userni belgilash")],
        [KeyboardButton(text="⚙️ Userbot menyusi"), KeyboardButton(text="📚 Qo'llanma")]
    ]
    if int(user_id) == int(config.ADMIN_ID):
        buttons.append([KeyboardButton(text="📊 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    bot_info = await bot.get_me()
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➕ Botni guruhga qo'shish", 
            url=f"https://t.me/{bot_info.username}?startgroup=true"
        )]
    ])
    
    await message.answer(
        f"Assalomu alaykum, {html.bold(message.from_user.full_name)}! 👋\n\n"
        "Men profilingiz nomidan guruhlarda otmetka qiluvchi va xabar yuboruvchi botman.\n\n"
        "💡 Guruh ichida **`;utag`** deb yozsangiz, bot boshqaruv menyusini guruhda chiqaradi!",
        reply_markup=inline_kb
    )
    
    await message.answer(
        "Quyidagi menyulardan foydalanishingiz mumkin:",
        reply_markup=get_main_keyboard(message.from_user.id)
    )


# --- GURUH MENYUSI HANDLERLARI (EKSKLYUZIV) ---

@dp.callback_query(F.data.startswith("gtag_"))
async def handle_group_menu_callbacks(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    if chat_id not in group_sessions:
        await callback.answer("❌ Bu seans eskirgan. Qaytadan ;utag yuboring.", show_alert=True)
        return

    session = group_sessions[chat_id]

    # TEKSHIRUV: Buyruq bergan user bilan tugmani bosgan user bir xilmi?
    if user_id != session["caller_id"]:
        await callback.answer("🔒 Bu menyu faqat buyruq bergan foydalanuvchi uchun!", show_alert=True)
        return

    action = callback.data.split("_")[1]
    safe_caller_name = escape_markdown_v1(session.get("caller_name", "Foydalanuvchi"))

    if action == "text":
        await callback.message.answer(f"📝 [{safe_caller_name}](tg://user?id={user_id}), otmetka uchun sarlavha matnini yuboring:", parse_mode="markdown")
        await state.set_state(GroupTagSession.waiting_for_text)
        await state.update_data(target_chat_id=chat_id)
        await callback.answer()

    elif action == "limit":
        await callback.message.answer(f"🔢 [{safe_caller_name}](tg://user?id={user_id}), nechta user otmetka qilinsin? Son kiriting (masalan: `20`) yoki `all` deb yozing:", parse_mode="markdown")
        await state.set_state(GroupTagSession.waiting_for_limit)
        await state.update_data(target_chat_id=chat_id)
        await callback.answer()

    elif action == "start":
        await execute_group_tag(chat_id, user_id)
        await callback.answer()

    elif action == "stop":
        if user_id in tag_jobs:
            tag_jobs[user_id]["status"] = "stopped"
            await callback.message.answer("🛑 **Otmetka jarayoni to'xtatildi.**")
        else:
            await callback.message.answer("Faol otmetka topilmadi.")
        await callback.answer()


@dp.message(GroupTagSession.waiting_for_text)
async def process_group_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get("target_chat_id")
    user_id = message.from_user.id

    if chat_id in group_sessions and group_sessions[chat_id]["caller_id"] == user_id:
        group_sessions[chat_id]["text"] = message.text
        safe_text = escape_markdown_v1(message.text)
        await message.reply(f"✅ **Sarlavha o'rnatildi:** `{safe_text}`", parse_mode="markdown")
    await state.clear()


@dp.message(GroupTagSession.waiting_for_limit)
async def process_group_limit_input(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get("target_chat_id")
    user_id = message.from_user.id
    text = message.text.strip().lower()

    if chat_id in group_sessions and group_sessions[chat_id]["caller_id"] == user_id:
        if text.isdigit():
            group_sessions[chat_id]["limit"] = int(text)
            await message.reply(f"✅ **Limit o'rnatildi:** `{text} ta`", parse_mode="markdown")
        else:
            group_sessions[chat_id]["limit"] = "all"
            await message.reply("✅ **Limit o'rnatildi:** `Hammasi`", parse_mode="markdown")
    await state.clear()


async def execute_group_tag(chat_id: int, user_id: int):
    if chat_id not in group_sessions:
        return

    session = group_sessions[chat_id]
    tag_text = session["text"]
    limit = session["limit"]

    if user_id in tag_jobs:
        tag_jobs[user_id]["status"] = "stopped"

    tag_jobs[user_id] = {
        "status": "running",
        "text": tag_text,
        "limit": limit,
        "chat_id": chat_id,
        "current_step": 0
    }

    display_text = escape_markdown_v1(tag_text) if tag_text else "Matnsiz"
    display_limit = "Hammasi" if limit == "all" else f"{limit} ta"

    await bot.send_message(
        chat_id,
        f"⚡️ **Otmetka boshlandi!**\n📝 Sarlavha: `{display_text}`\n🔢 Limit: `{display_limit}`",
        parse_mode="markdown"
    )

    asyncio.create_task(background_tagging_task(user_id))


# --- BOTNING SHAXSIY CHATIDAGI HANDLERLARI ---

@dp.message(F.text == "🚀 Guruhga xabar jo'natish")
async def start_mailing_process(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in running_userbots:
        await message.answer("Avval userbotni ulashingiz kerak!")
        return

    await message.answer("1️⃣ Guruhga yubormoqchi bo'lgan **matningizni** kiriting:", parse_mode="markdown")
    await state.set_state(MailingState.waiting_for_text)


@dp.message(MailingState.waiting_for_text)
async def process_mailing_text(message: Message, state: FSMContext):
    await state.update_data(mailing_text=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Cheksiz yuborish", callback_data="loop_infinite")]
    ])
    await message.answer(
        "2️⃣ Xabar nechta yuborilsin? \n\nSon kiriting yoki tugmani bosing:",
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
        await message.answer("Iltimos, faqat butun son kiriting!")
        return
    await state.update_data(loop_count=int(text))
    await ask_for_groups(message, state, mode="mail")


@dp.message(F.text == "🏷 Userni belgilash")
async def start_tag_process(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in running_userbots:
        await message.answer("Avval userbotni ulashingiz kerak!")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Matnsiz (O'tkazib yuborish)", callback_data="skip_tag_text")]
    ])
    await message.answer(
        "1️⃣ Otmetka sarlavha matnini kiriting:",
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
        "2️⃣ Nechta user atmetka qilinsin? Son kiriting yoki tugmani bosing:",
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
        await message.answer("Iltimos, faqat butun son kiriting!")
        return
    await state.update_data(tag_limit=int(text))
    await ask_for_groups(message, state, mode="tag")


async def ask_for_groups(message: Message, state: FSMContext, mode="mail"):
    user_id = message.chat.id
    if user_id not in running_userbots:
        await message.answer("❌ Userbotingiz faol emas. Qayta ulashingiz kerak.")
        await state.clear()
        return

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
        await message.answer(f"Guruhlarni yuklashda xatolik: {e}")
        await state.clear()
        return

    if not inline_keyboard:
        await message.answer("Profilingizda hech qanday guruh topilmadi.")
        await state.clear()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer("3️⃣ Guruhingizni tanlang:", reply_markup=keyboard)


# --- BACKGROUND TASKS (MAILING & TAGGING) ---

@dp.callback_query(F.data.startswith("send_to_"))
async def start_mailing_job(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_chat_id = int(callback.data.split("_")[2])

    data = await state.get_data()
    mailing_text = data.get("mailing_text", "Assalomu alaykum!")
    loop_count = data.get("loop_count", 10)
    await state.clear()

    if user_id in mailing_jobs:
        mailing_jobs[user_id]["status"] = "stopped"

    mailing_jobs[user_id] = {
        "status": "running",
        "text": mailing_text,
        "loop_count": loop_count,
        "chat_id": target_chat_id,
        "current_step": 0
    }

    safe_text = escape_markdown_v1(mailing_text)
    await callback.message.answer(f"🚀 **Xabar yuborish boshlandi!**\n\nMatn: `{safe_text}`", parse_mode="markdown")
    await callback.answer()
    asyncio.create_task(background_mailing_task(user_id))


async def background_mailing_task(user_id: int):
    if user_id not in running_userbots:
        await bot.send_message(user_id, "⚠️ Userbotingiz faol emas. Qayta ulashingiz kerak.")
        return

    cl = running_userbots[user_id]

    while user_id in mailing_jobs:
        job = mailing_jobs[user_id]

        if job["status"] == "stopped":
            del mailing_jobs[user_id]
            break

        loop_count = job.get("loop_count")
        if loop_count != "infinite" and isinstance(loop_count, int) and job["current_step"] >= loop_count:
            await bot.send_message(user_id, "✅ **Xabarlar yuborib bo'lindi!**")
            del mailing_jobs[user_id]
            break

        try:
            await cl.send_message(job["chat_id"], job["text"])
            job["current_step"] += 1
        except Exception as e:
            await bot.send_message(user_id, f"⚠️ Xatolik: {e}")
            del mailing_jobs[user_id]
            break

        await asyncio.sleep(1.0)


@dp.callback_query(F.data.startswith("tag_to_"))
async def start_tagging_job(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    target_chat_id = int(callback.data.split("_")[2])

    data = await state.get_data()
    tag_text = data.get("tag_text", "")
    tag_limit = data.get("tag_limit", "all")
    await state.clear()

    if user_id in tag_jobs:
        tag_jobs[user_id]["status"] = "stopped"

    tag_jobs[user_id] = {
        "status": "running",
        "text": "" if tag_text == "NO_TEXT" else tag_text,
        "limit": tag_limit,
        "chat_id": target_chat_id,
        "current_step": 0
    }

    await callback.message.answer("⚡️ **Belgilash boshlandi!**", parse_mode="markdown")
    await callback.answer()
    asyncio.create_task(background_tagging_task(user_id))


async def background_tagging_task(user_id: int):
    if user_id not in running_userbots:
        await bot.send_message(user_id, "⚠️ Userbotingiz faol emas. Qayta ulashingiz kerak.")
        return

    cl = running_userbots[user_id]

    if user_id not in tag_jobs:
        return

    job = tag_jobs[user_id]
    chat_id = job["chat_id"]
    limit = job["limit"]

    try:
        try:
            await cl.get_chat(chat_id)
        except Exception:
            pass

        me = await cl.get_me()

        members = []
        async for member in cl.get_chat_members(chat_id):
            if member.user and not member.user.is_bot and not member.user.is_deleted:
                if member.user.id != me.id:
                    members.append(member.user)

        if isinstance(limit, int):
            members = members[:limit]

        for u in members:
            if user_id not in tag_jobs or tag_jobs[user_id]["status"] == "stopped":
                await bot.send_message(user_id, "🛑 **Otmetka to'xtatildi.**")
                if user_id in tag_jobs: del tag_jobs[user_id]
                return

            if u.username:
                tag_mention = f"@{u.username}"
            else:
                clean_name = escape_markdown_v1(u.first_name or "Foydalanuvchi")
                tag_mention = f"[{clean_name}](tg://user?id={u.id})"

            header = tag_jobs[user_id]["text"]
            safe_header = escape_markdown_v1(header) if header else ""
            msg_text = f"📢 **{safe_header}**\n\n{tag_mention}" if safe_header else tag_mention

            try:
                await cl.send_message(chat_id, msg_text.strip(), parse_mode=ParseMode.MARKDOWN)
                job["current_step"] += 1
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                logging.error(f"Tag yuborishda xato: {e}")

            await asyncio.sleep(1.0)

        await bot.send_message(user_id, f"⚡️ **Otmetka yakunlandi!** Jami: `{job['current_step']}` ta.")

    except Exception as e:
        await bot.send_message(user_id, f"⚠️ Xatolik: {e}")

    if user_id in tag_jobs:
        del tag_jobs[user_id]


# --- SOZLAMALAR VA AUTHENTICATION ---

@dp.message(F.text == "⚙️ Userbot menyusi")
async def userbot_menu(message: Message):
    user_id = message.from_user.id
    if user_id in running_userbots:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Userbotni o'chirish")], [KeyboardButton(text="⬅️ Orqaga")]],
            resize_keyboard=True
        )
        await message.answer("✅ Sizning userbotingiz faol holatda.", reply_markup=keyboard)
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Userbotni ulash")], [KeyboardButton(text="⬅️ Orqaga")]],
            resize_keyboard=True
        )
        await message.answer("Sizda hali userbot ulanmagan:", reply_markup=keyboard)


@dp.message(F.text == "📱 Userbotni ulash")
async def start_auth(message: Message, state: FSMContext):
    await message.answer("Iltimos, Telegram raqamingizni kiriting:\nFormat: `+998901234567`", parse_mode="markdown")
    await state.set_state(UserbotAuth.waiting_for_phone)


@dp.message(UserbotAuth.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    user_id = message.from_user.id

    if user_id in active_auth_clients:
        try:
            await active_auth_clients[user_id]["client"].disconnect()
        except Exception:
            pass
        del active_auth_clients[user_id]

    await state.update_data(phone=phone)
    await message.answer("Telegramdan tasdiqlash kodi so'ralmoqda...")
    client = Client(
        name=f"auth_{user_id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        in_memory=True,
        no_updates=True
    )
    await client.connect()
    try:
        code_info = await client.send_code(phone)
        active_auth_clients[user_id] = {"client": client, "phone_code_hash": code_info.phone_code_hash}
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
        await message.answer("❌ Seans eskirgan. Qaytadan /start bosing.")
        await state.clear()
        return

    data = await state.get_data()
    phone = data.get('phone')
    client = active_auth_clients[user_id]["client"]
    phone_code_hash = active_auth_clients[user_id]["phone_code_hash"]

    try:
        await client.sign_in(phone, phone_code_hash, code)
        session_string = await client.export_session_string()

        await client.disconnect()
        del active_auth_clients[user_id]

        database.save_session(user_id, phone, session_string)
        await start_userbot_worker(user_id, session_string)

        await message.answer("✅ Userbot ulandi!", reply_markup=get_main_keyboard(user_id))
        await state.clear()
    except SessionPasswordNeeded:
        await message.answer("2FA parolingizni kiriting:")
        await state.set_state(UserbotAuth.waiting_for_password)
    except Exception as e:
        logging.error(f"Kod xatosi: {e}")
        await message.answer("❌ Kod noto'g'ri. Qaytadan kiriting:")


@dp.message(UserbotAuth.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()

    if user_id not in active_auth_clients:
        await message.answer("❌ Seans eskirgan. Qaytadan /start bosing.")
        await state.clear()
        return

    client = active_auth_clients[user_id]["client"]
    data = await state.get_data()
    phone = data.get('phone')

    try:
        await client.check_password(password)
        session_string = await client.export_session_string()
    except Exception as e:
        logging.error(f"2FA Parol xatosi: {e}")
        await message.answer("❌ Noto'g'ri parol. Qayta urinib ko'ring:")
        return

    try:
        await client.disconnect()
        del active_auth_clients[user_id]

        database.save_session(user_id, phone, session_string)
        await start_userbot_worker(user_id, session_string)

        await message.answer("✅ Userbot ulandi!", reply_markup=get_main_keyboard(user_id))
        await state.clear()
    except Exception as e:
        logging.error(f"Workerni yurgizishda xatolik: {e}")
        await message.answer(f"⚠️ Xatolik: {e}")


@dp.message(F.text == "❌ Userbotni o'chirish")
async def stop_userbot(message: Message):
    user_id = message.from_user.id
    if user_id in running_userbots:
        try:
            await running_userbots[user_id].stop()
        except Exception:
            pass
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
        "1. Guruhda **`;utag`** deb yozing. Bot menyuni shu guruhga yuboradi.\n"
        "2. Menyudagi tugmalarni faqat buyruq bergan odam bosishi mumkin.\n"
        "3. Botning shaxsiy chatidan ham xabar yuborish va otmetka qilish menyularidan foydalanishingiz mumkin.",
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
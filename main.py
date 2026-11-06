import sys
import io
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List

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
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    BufferedInputFile,
    WebAppInfo
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pyrogram import Client, filters, raw, utils
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import (
    SessionPasswordNeeded,
    FloodWait,
    AuthKeyUnregistered,
    AuthKeyInvalid,
    UserDeactivated,
    UserDeactivatedBan,
    Unauthorized,
    PeerIdInvalid
)
from pyrogram.types import (
    InlineKeyboardMarkup as PyroInlineKeyboardMarkup,
    InlineKeyboardButton as PyroInlineKeyboardButton
)

import pyrogram.utils

# Pyrogram 64-bit yangi Telegram kanal/superguruh ID lari uchun patch (Peer id invalid xatosini butunlay yo'qotish)
pyrogram.utils.MIN_CHANNEL_ID = -100999999999999
pyrogram.utils.MAX_USER_ID = 99999999999999

def _patched_get_peer_type(peer_id: int) -> str:
    if peer_id < 0:
        if peer_id < pyrogram.utils.MAX_CHANNEL_ID:
            return "channel"
        return "chat"
    elif peer_id > 0:
        return "user"
    raise ValueError(f"Peer id invalid: {peer_id}")

pyrogram.utils.get_peer_type = _patched_get_peer_type

# Pyrogram sessiya yopilganda 'Cannot operate on a closed database' xatosini xavfsiz bartaraf etish
import sqlite3
from pyrogram.storage.sqlite_storage import SQLiteStorage

_orig_update_peers = SQLiteStorage.update_peers
async def _safe_update_peers(self, peers):
    try:
        return await _orig_update_peers(self, peers)
    except (sqlite3.ProgrammingError, sqlite3.OperationalError):
        pass

SQLiteStorage.update_peers = _safe_update_peers

_orig_get_peer_by_id = SQLiteStorage.get_peer_by_id
async def _safe_get_peer_by_id(self, peer_id):
    try:
        return await _orig_get_peer_by_id(self, peer_id)
    except (sqlite3.ProgrammingError, sqlite3.OperationalError):
        raise KeyError(f"Storage closed: {peer_id}")

SQLiteStorage.get_peer_by_id = _safe_get_peer_by_id

import config
import database
import webapp
import tunnel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

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

class PaymentProofState(StatesGroup):
    waiting_for_plan = State()
    waiting_for_proof = State()

# --- GLOBAL LUG'ATLAR ---
active_auth_clients = {}
running_userbots = {}
mailing_jobs = {}
tag_jobs = {}

# Guruhdagi faol seanslar: group_sessions[chat_id] = {"caller_id": int, "caller_name": str, "text": str, "limit": val}
group_sessions = {}


def escape_markdown_v1(text: str) -> str:
    """Markdown formatlashda xatolik bermasligi uchun maxsus belgilarni tozalash."""
    if not text:
        return ""
    return re.sub(r'([\[\]\(\)\*\_`])', r'\\\1', str(text))


def extract_pyrogram_html_text(message) -> str:
    """Pyrogram xabaridan (matn, sticker, premium custom emoji) formatlangan HTML matnini oladi."""
    if not message:
        return ""
    if getattr(message, "sticker", None):
        stk = message.sticker
        if getattr(stk, "custom_emoji_id", None):
            return f'<emoji id="{stk.custom_emoji_id}">{stk.emoji or ""}</emoji>'
        return stk.emoji or ""

    if not getattr(message, "text", None):
        return ""

    if getattr(message, "entities", None):
        try:
            from pyrogram.parser.html import HTML as PyroHTML
            full_html = PyroHTML.unparse(message.text, message.entities)
        except Exception:
            full_html = message.text
    else:
        full_html = message.text

    parts = full_html.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def extract_aiogram_html_text(message: Message) -> str:
    """Aiogram xabaridan (matn, sticker, premium sticker) Pyrogramga mos HTML matnini oladi."""
    if not message:
        return ""
    if message.sticker:
        stk = message.sticker
        if getattr(stk, "custom_emoji_id", None):
            return f'<emoji id="{stk.custom_emoji_id}">{stk.emoji or ""}</emoji>'
        return stk.emoji or ""

    raw_html = message.html_text if hasattr(message, "html_text") and message.html_text else (message.text or "")
    if not raw_html:
        return ""
    # Aiogram <tg-emoji emoji-id="..."> ni Pyrogram <emoji id="..."> ga o'tkazish
    pyro_html = re.sub(r'<tg-emoji emoji-id=[\"\']?(\d+)[\"\']?>', r'<emoji id="\1">', raw_html)
    pyro_html = pyro_html.replace('</tg-emoji>', '</emoji>')
    return pyro_html.strip()


async def warm_up_cache(client: Client):
    """
    Pyrogram cache yuklanishi: PeerIdInvalid va KeyError xatolarini oldini olish
    uchun userbotning get_dialogs keshi avvaldan to'ldiriladi.
    """
    try:
        async for _ in client.get_dialogs(limit=100):
            pass
    except Exception as e:
        logging.warning(f"Cache warm up warning: {e}")


# --- KLAVIATURALAR VA MENYULAR ---

def get_main_keyboard(user_id: int):
    """Asosiy reply klaviatura."""
    buttons = [
        [KeyboardButton(text="🚀 Guruhga xabar jo'natish"), KeyboardButton(text="🏷 Userni belgilash")],
        [KeyboardButton(text="⚡️ Tezlikni sozlash"), KeyboardButton(text="💎 Obuna va Tariflar")],
        [KeyboardButton(text="⚙️ Userbot menyusi"), KeyboardButton(text="📚 Qo'llanma")]
    ]
    if database.is_super_admin(user_id):
        buttons.append([
            KeyboardButton(text="📊 Admin Panel")
        ])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_cancel_reply_keyboard():
    """FSM bosqichlaridan xavfsiz chiqish uchun orqaga tugmasi."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Orqaga")]],
        resize_keyboard=True
    )


def get_group_menu_keyboard(current_speed: float = 2.0):
    """Guruh ichida otmetkani sozlash menyusi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Matn biriktirish", callback_data="gtag_text")],
        [InlineKeyboardButton(text="🔢 Limit belgilash (max 400)", callback_data="gtag_limit")],
        [InlineKeyboardButton(text=f"⚡️ Tezlik: {current_speed}s", callback_data="gtag_speed")],
        [InlineKeyboardButton(text="🚀 Otmetkani boshlash (/1)", callback_data="gtag_start")],
        [InlineKeyboardButton(text="🛑 To'xtatish (/2)", callback_data="gtag_stop")]
    ])


def get_group_control_keyboard(status: str = "running", user_id: int = 0):
    """Guruh ichida otmetka jarayonini boshqarish tugmalari (Pauza, Davom ettirish, To'xtatish)."""
    if status == "running":
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⏸ Pauza", callback_data=f"gtag_pause_{user_id}"),
                InlineKeyboardButton(text="🛑 To'xtatish (/2)", callback_data=f"gtag_stop_{user_id}")
            ]
        ])
    else:  # "paused"
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Davom ettirish", callback_data=f"gtag_resume_{user_id}"),
                InlineKeyboardButton(text="🛑 To'xtatish (/2)", callback_data=f"gtag_stop_{user_id}")
            ]
        ])


def get_control_panel(status="running", job_type="mail"):
    """Botning shaxsiy chatida jarayonni boshqarish paneli."""
    buttons = []
    prefix = "mail_" if job_type == "mail" else "tag_"

    if status == "running":
        buttons.append(InlineKeyboardButton(text="⏸ Pauza", callback_data=f"{prefix}pause"))
    elif status == "paused":
        buttons.append(InlineKeyboardButton(text="▶️ Davom ettirish", callback_data=f"{prefix}resume"))

    buttons.append(InlineKeyboardButton(text="🛑 To'xtatish", callback_data=f"{prefix}stop"))
    buttons.append(InlineKeyboardButton(text="📝 Tahrirlash", callback_data=f"{prefix}edit"))

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def get_speed_keyboard(current_speed: float = 2.0, prefix: str = "set_speed_"):
    """Tezlikni tanlash inline klaviaturasi (1.5s, 2s, 3s, 5s)."""
    buttons = []
    for sp in config.ALLOWED_SPEEDS:
        mark = "✅ " if sp == current_speed else ""
        buttons.append(InlineKeyboardButton(text=f"{mark}{sp} soniya", callback_data=f"{prefix}{sp}"))
    
    # 2 qator qilib joylashtiramiz
    rows = [buttons[:2], buttons[2:]]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_subscription_menu_keyboard():
    """Tariflar va obuna bo'lish menyusi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Haftalik (7 kun) — {config.WEEKLY_STARS} Stars", callback_data="buy_stars_weekly")],
        [InlineKeyboardButton(text=f"Oylik (30 kun) — {config.MONTHLY_STARS} Stars", callback_data="buy_stars_monthly")],
        [InlineKeyboardButton(text="Karta / Admin lichkasi orqali to'lov", callback_data="pay_via_admin")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_main_menu")]
    ])


def get_admin_approval_keyboard(request_id: int):
    """Admin uchun to'lovni tasdiqlash yoki bekor qilish tugmalari."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Tasdiqlash", callback_data=f"pay_approve_{request_id}"),
            InlineKeyboardButton(text="Bekor qilish", callback_data=f"pay_reject_{request_id}")
        ]
    ])


# --- OBUNA TEKSHIRUVI ---

async def check_user_access(message_or_call, user_id: int) -> bool:
    """
    Foydalanuvchida xizmatlardan foydalanish uchun ruxsat (obuna) borligini tekshiradi.
    Adminlar uchun to'lov talab qilinmaydi (doimiy ruxsat).
    """
    if database.is_admin(user_id):
        return True

    if database.is_subscribed(user_id):
        return True

    text = (
        "<b>Faol obuna talab qilinadi</b>\n\n"
        "Xizmatdan to'liq foydalanish, guruhlarda xabar yuborish va a'zolarni teglash "
        "uchun tarif rejalaridan biriga obuna bo'ling.\n\n"
        f"• Haftalik paket (7 kun): <code>{config.WEEKLY_STARS} Telegram Stars</code>\n"
        f"• Oylik paket (30 kun): <code>{config.MONTHLY_STARS} Telegram Stars</code>"
    )
    kb = get_subscription_menu_keyboard()

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=kb, parse_mode="HTML")
    elif isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await message_or_call.answer("Obuna faol emas!", show_alert=True)
    return False


# --- USERBOT WORKER ---

async def start_userbot_worker(user_id: int, session_string: str):
    """Har bir foydalanuvchi uchun Pyrogram userbot workerini ishga tushiradi."""
    if not session_string or not str(session_string).strip():
        logging.warning(f"User {user_id} sessiyasi bo'sh, worker o'tkazib yuborildi.")
        return

    if user_id in running_userbots:
        return

    client = Client(
        name=f"worker_{user_id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session_string,
        in_memory=True,
        no_updates=False
    )

    # 1. GURUHDA ;utag, .utag, !utag buyrug'i
    @client.on_message(filters.group & filters.command(["utag", "tag"], prefixes=[";", ".", "!"]))
    async def handle_semicolon_utag(cl: Client, message):
        sender_id = message.from_user.id if message.from_user else None
        chat_id = message.chat.id
        chat_title = message.chat.title or "Guruh"

        if not sender_id or sender_id not in running_userbots:
            return

        try:
            me = await cl.get_me()
            if sender_id != me.id:
                return
        except Exception as e:
            logging.error(f"Userbot me olishda xato: {e}")
            return

        if not database.is_subscribed(sender_id):
            try:
                await message.reply("⚠️ **Userbot egasida faol obuna mavjud emas!** Iltimos, bot orqali obuna bo'ling.")
            except Exception:
                pass
            return

        initial_text = extract_pyrogram_html_text(message)

        try:
            await message.delete()
        except Exception:
            pass

        group_sessions[chat_id] = {
            "caller_id": sender_id,
            "caller_name": message.from_user.first_name or "Foydalanuvchi",
            "text": initial_text,
            "limit": config.HARD_TAG_LIMIT
        }

        user_speed = database.get_user_speed(sender_id)
        safe_chat_title = escape_markdown_v1(chat_title)
        safe_first_name = escape_markdown_v1(message.from_user.first_name or "Foydalanuvchi")
        display_initial_text = escape_markdown_v1(initial_text) if initial_text else "Matnsiz"

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚙️ **{safe_chat_title}** uchun otmetka menyusi\n"
                    f"👤 Buyruq beruvchi: [{safe_first_name}](tg://user?id={sender_id})\n\n"
                    f"📌 **Joriy sozlama:**\n"
                    f"• Sarlavha: `{display_initial_text}`\n"
                    f"• Limit: `400 ta (Hard limit)`\n"
                    f"• Tezlik: `{user_speed}s`\n\n"
                    f"⚡️ *Tezkor buyruqlar: `/1` — Boshlash, `/2` — To'xtatish*\n"
                    f"🔒 *Ushbu menyu tugmalaridan faqat {safe_first_name} foydalana oladi!*"
                ),
                reply_markup=get_group_menu_keyboard(user_speed),
                parse_mode="markdown"
            )
        except Exception as e:
            logging.error(f"Guruhga menyu yuborishda xato: {e}")
            try:
                bot_info = await bot.get_me()
                add_to_group_kb = PyroInlineKeyboardMarkup([
                    [PyroInlineKeyboardButton(
                        text="➕ Botni guruhga qo'shish",
                        url=f"https://t.me/{bot_info.username}?startgroup=true"
                    )]
                ])
                await cl.send_message(
                    chat_id,
                    "⚠️ **Menyu chiqishi uchun rasmiy botga guruhda xabar yuborish huquqini bering yoki uni Admin qiling!**\n\n"
                    "Tugma orqali botni guruhga qayta qo'shishingiz/sozlamasini yangilashingiz mumkin 👇",
                    reply_markup=add_to_group_kb
                )
            except Exception as ex:
                logging.error(f"Userbot ogohlantirish yuborish xatosi: {ex}")

    # 2. GURUHDA USERBOT ORQALI TEZKOR /1 (Boshlash) VA /2 (To'xtatish)
    @client.on_message(filters.group & filters.command(["1", "starttag"], prefixes=["/", ".", ";", "!"]))
    async def handle_userbot_cmd_one(cl: Client, message):
        sender_id = message.from_user.id if message.from_user else None
        chat_id = message.chat.id
        if not sender_id:
            return
        try:
            me = await cl.get_me()
            if sender_id != me.id:
                return
        except Exception:
            return

        if not database.is_subscribed(sender_id):
            return

        # Guruh seansi mavjud bo'lmasa standart yaratiladi
        if chat_id not in group_sessions:
            group_sessions[chat_id] = {
                "caller_id": sender_id,
                "caller_name": message.from_user.first_name or "Foydalanuvchi",
                "text": "",
                "limit": config.HARD_TAG_LIMIT
            }
        try:
            await message.delete()
        except Exception:
            pass
        await execute_group_tag(chat_id, sender_id)

    @client.on_message(filters.group & filters.command(["2", "stoptag"], prefixes=["/", ".", ";", "!"]))
    async def handle_userbot_cmd_two(cl: Client, message):
        sender_id = message.from_user.id if message.from_user else None
        chat_id = message.chat.id
        if not sender_id:
            return
        try:
            me = await cl.get_me()
            if sender_id != me.id:
                return
        except Exception:
            return

        if sender_id in tag_jobs and tag_jobs[sender_id].get("chat_id") == chat_id:
            tag_jobs[sender_id]["status"] = "stopped"
            step = tag_jobs[sender_id].get("current_step", 0)
            try:
                await bot.send_message(
                    chat_id,
                    f"🛑 **Otmetka to'xtatildi (/2 buyrug'i).**\n📊 Jami: `{step}` ta a'zo belgilandi.",
                    parse_mode="markdown"
                )
            except Exception:
                pass
            try:
                await message.delete()
            except Exception:
                pass

    try:
        await client.start()
    except (AuthKeyUnregistered, AuthKeyInvalid, UserDeactivated, UserDeactivatedBan, Unauthorized) as e:
        logging.warning(f"User {user_id} sessiyasi bekor qilingan: {e}. Bazadan o'chirildi.")
        database.delete_session(user_id)
        return
    except Exception as e:
        err_msg = str(e)
        if "AUTH_KEY_UNREGISTERED" in err_msg or "401" in err_msg or "USER_DEACTIVATED" in err_msg:
            logging.warning(f"User {user_id} sessiyasi yaroqsiz ({err_msg}).")
            database.delete_session(user_id)
        else:
            logging.error(f"Userbot worker start xatosi (User {user_id}): {e}")
        return

    # Dialog keshini oldindan to'ldirish (PeerIdInvalid, KeyError oldini olish)
    await warm_up_cache(client)

    # Foydalanuvchi ma'lumotlarini (username, ism) bazada yangilash
    try:
        me = await client.get_me()
        database.update_user_info(user_id, me.username, me.first_name)
    except Exception as e:
        logging.warning(f"Userbot me ma'lumotini olishda xato ({user_id}): {e}")

    running_userbots[user_id] = client
    logging.info(f"Userbot worker muvaffaqiyatli yoqildi: {user_id}")


# --- ASOSIY VA ROLLBACK (ORQAGA) HANDLERLARI ---

@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    database.update_user_info(user_id, message.from_user.username, message.from_user.first_name)

    bot_info = await bot.get_me()
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Botni guruhga qo'shish",
            url=f"https://t.me/{bot_info.username}?startgroup=true"
        )],
        [InlineKeyboardButton(text="Obuna va Tariflar", callback_data="open_sub_menu")]
    ])

    start_text = (
        "💎 <b>MAFIA GURUHLARI UCHUN UTAG BOT</b> 💎\n\n"
        "🎭 <b>Mafia guruhingizni yanada qulay va zamonaviy boshqaring!</b>\n\n"
        "🤖 <b>UTAG BOT — obuna va tariflar tizimi bir joyda!</b>\n\n"
        "✨ <b>IMKONIYATLAR:</b>\n"
        f"🔷 Haftalik obuna — 7 kun / {config.WEEKLY_STARS} ⭐\n"
        f"🔷 Oylik obuna — 30 kun / {config.MONTHLY_STARS} ⭐\n"
        "🔷 Telegram Stars orqali avtomatik faollashtirish\n"
        "🔷 Karta yoki admin orqali to‘lov imkoniyati @abduxalilov017\n\n"
        "🛡 <b>ISHONCH VA XAVFSIZLIK</b>\n"
        "✅ To‘lovlar bo‘yicha tasdiq va nazorat\n"
        "✅ Userlarni sababsiz chetlatmaslik\n"
        "✅ Hech qanday shaxsiy muammo yoki adovatga qarab munosabat qilmaslik\n"
        "✅ Har bir foydalanuvchiga xolis va hurmat bilan yondashish\n\n"
        "🤝 <b>Biz uchun ishonch, adolat va foydalanuvchilar roziligi muhim!</b>\n\n"
        "📩 <b>UTAG BOT — mafia guruhingiz uchun qulay yechim.</b>\n\n"
        "♠️ <b>*Adolatli boshqaruv. Ishonchli xizmat. Qulay tizim.*</b> ♠️"
    )

    await message.answer(
        start_text,
        reply_markup=inline_kb,
        parse_mode="HTML"
    )

    await message.answer(
        "Kerakli bo'limni tanlang:",
        reply_markup=get_main_keyboard(user_id)
    )


@dp.message(F.text == "⬅️ Orqaga")
async def cmd_back(message: Message, state: FSMContext):
    """Universal orqaga qaytish: FSM holatini tozalab, bosh menyuga qaytaradi."""
    await state.clear()
    await message.answer("Bosh menyuga qaytildi.", reply_markup=get_main_keyboard(message.from_user.id))


@dp.callback_query(F.data == "back_to_main_menu")
async def callback_back_to_main(callback: CallbackQuery, state: FSMContext):
    """Inline klaviaturalardan orqaga qaytish."""
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("Bosh menyu:", reply_markup=get_main_keyboard(callback.from_user.id))
    await callback.answer()


# --- TEZKOR SLASH RAQAMLI BUYRUQLAR (/1 VA /2) ---

@dp.message(F.text.startswith("/1"))
async def handle_slash_one(message: Message, state: FSMContext):
    """
    /1 — UTAG boshlash (start tagging).
    Guruhda yozilsa: ushbu guruhda otmetkani boshlaydi.
    Shaxsiy chatda yozilsa: guruhlar ro'yxatini chiqarib boshlashni taklif qiladi.
    """
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not await check_user_access(message, user_id):
        return

    if user_id not in running_userbots:
        await message.answer("⚠️ Avval Userbotni ulashingiz kerak!")
        return

    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        # Guruh ichida /1 buyrug'i
        if chat_id not in group_sessions:
            group_sessions[chat_id] = {
                "caller_id": user_id,
                "caller_name": message.from_user.first_name or "Foydalanuvchi",
                "text": "",
                "limit": config.HARD_TAG_LIMIT
            }
        await execute_group_tag(chat_id, user_id)
    else:
        # Shaxsiy chatda /1 bosilganda
        await message.answer("🚀 Guruh tanlash orqali otmetkani boshlashingiz mumkin:")
        await start_tag_process(message, state)


@dp.message(F.text.startswith("/2"))
async def handle_slash_two(message: Message, state: FSMContext):
    """
    /2 — UTAG to'xtatish (stop tagging).
    Guruhda yozilsa: shu guruhdagi jarayonni to'xtatadi.
    Shaxsiyda yozilsa: foydalanuvchining faol jarayonini to'xtatadi.
    """
    user_id = message.from_user.id
    chat_id = message.chat.id

    stopped_anything = False

    # 1. Tag job to'xtatish
    if user_id in tag_jobs:
        tag_jobs[user_id]["status"] = "stopped"
        step = tag_jobs[user_id].get("current_step", 0)
        stopped_anything = True
        await message.answer(f"🛑 **Otmetka jarayoni to'xtatildi!**\n📊 Jami: `{step}` ta a'zo belgilandi.", parse_mode="markdown")

    # 2. Mailing job to'xtatish
    if user_id in mailing_jobs:
        mailing_jobs[user_id]["status"] = "stopped"
        stopped_anything = True
        await message.answer("🛑 **Xabar yuborish jarayoni to'xtatildi!**", parse_mode="markdown")

    if not stopped_anything:
        # Guruhdagi boshqa seans egasi bo'lsa
        session = group_sessions.get(chat_id)
        if session and session.get("caller_id") == user_id and user_id in tag_jobs:
            tag_jobs[user_id]["status"] = "stopped"
            await message.answer("🛑 **Otmetka jarayoni to'xtatildi!**", parse_mode="markdown")
        else:
            await message.answer("⚠️ Hozirda faol ishlayotgan otmetka jarayoni topilmadi.")


# --- TEZLIKNI SOZLASH BO'LIMI ---

@dp.message(F.text == "⚡️ Tezlikni sozlash")
async def cmd_speed_settings(message: Message):
    user_id = message.from_user.id
    current_speed = database.get_user_speed(user_id)
    await message.answer(
        f"⚡️ **Otmetka tezligini sozlash:**\n\n"
        f"Hozirgi oraliq (interval): `{current_speed} soniya`\n\n"
        "Tag yuborish tezligini tanlang (1.5s dan 5.0s gacha):",
        reply_markup=get_speed_keyboard(current_speed),
        parse_mode="markdown"
    )


@dp.callback_query(F.data.startswith("set_speed_"))
async def callback_set_speed(callback: CallbackQuery):
    user_id = callback.from_user.id
    speed_val = float(callback.data.replace("set_speed_", ""))
    database.set_user_speed(user_id, speed_val)
    await callback.answer(f"✅ Tezlik {speed_val} soniyaga o'rnatildi!")
    try:
        await callback.message.edit_reply_markup(reply_markup=get_speed_keyboard(speed_val))
    except Exception:
        pass


# --- OBUNA VA TO'LOV TIZIMI (TARIFLAR) ---

@dp.message(F.text == "💎 Obuna va Tariflar")
@dp.callback_query(F.data == "open_sub_menu")
async def show_subscription_plans(event: Any):
    user_id = event.from_user.id

    # Adminlar uchun to'lov talab qilinmaydi
    if database.is_admin(user_id):
        admin_text = (
            "<b>Siz tizim adminisiz!</b>\n\n"
            "Siz uchun barcha funksiyalar (UTAG, mailing, tezlik va boshqaruv) "
            "cheksiz va bepul faollashtirilgan.\n\n"
            "• Obuna holati: <code>Faol (Cheksiz)</code>\n"
            "• Sizdan hech qanday to'lov talab qilinmaydi."
        )
        if isinstance(event, Message):
            await event.answer(admin_text, parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            try:
                await event.message.edit_text(admin_text, parse_mode="HTML")
            except Exception:
                await event.message.answer(admin_text, parse_mode="HTML")
            await event.answer()
        return

    sub_info = database.get_subscription_info(user_id)
    status_text = sub_info.get("display_text", "Obuna yo'q")

    text = (
        "<b>UTAG Obuna va Tarif rejalari</b>\n\n"
        f"<b>Sizning holatingiz:</b> <code>{status_text}</code>\n\n"
        "<b>Tarif rejalarimiz:</b>\n"
        f"• Haftalik paket (7 kun) — {config.WEEKLY_STARS} Telegram Stars\n"
        f"• Oylik paket (30 kun) — {config.MONTHLY_STARS} Telegram Stars\n\n"
        "<b>To'lov turlari:</b>\n"
        "• Telegram Stars orqali avtomatik aktivatsiya\n"
        "• Karta orqali / Admin lichkasi (chek tasdiqlash)"
    )

    kb = get_subscription_menu_keyboard()
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    elif isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await event.answer()


# A) TELEGRAM STARS ORQALI TO'LOV (INVOICES)

@dp.callback_query(F.data.in_({"buy_stars_weekly", "buy_stars_monthly"}))
async def process_stars_invoice(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_weekly = callback.data == "buy_stars_weekly"

    title = "Haftalik UTAG obunasi (7 kun)" if is_weekly else "Oylik UTAG obunasi (30 kun)"
    desc = "Guruhlarda tezkor UTAG va cheksiz xabar jo'natish xizmati"
    stars_amount = config.WEEKLY_STARS if is_weekly else config.MONTHLY_STARS
    payload = f"stars_sub_{'weekly' if is_weekly else 'monthly'}_{user_id}"

    prices = [LabeledPrice(label=title, amount=stars_amount)]

    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=desc,
            payload=payload,
            provider_token="",  # Telegram Stars uchun bo'sh qoldiriladi
            currency="XTR",     # Telegram Stars valyutasi
            prices=prices,
            start_parameter=f"sub_{user_id}"
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Invoice yuborishda xato: {e}")
        await callback.answer(f"Invoys yaratishda xato: {e}", show_alert=True)


@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    """Stars to'lovi tasdiqlanishidan oldingi tekshiruv."""
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    """Muvaffaqiyatli Stars to'lovi qabul qilinganda avtomatik aktivatsiya."""
    payment = message.successful_payment
    payload = payment.invoice_payload
    user_id = message.from_user.id

    days = 7
    plan_name = "Haftalik"
    if "monthly" in payload:
        days = 30
        plan_name = "Oylik"

    new_end_date = database.add_subscription(user_id, days=days, payment_type="stars")
    try:
        database.record_stars_payment(
            user_id=user_id,
            plan="monthly" if days == 30 else "weekly",
            stars=payment.total_amount,
            charge_id=getattr(payment, "telegram_payment_charge_id", "stars")
        )
    except Exception as e:
        logging.warning(f"Stars payment record error: {e}")

    await message.answer(
        f"🎉 **To'lov muvaffaqiyatli qabul qilindi!**\n\n"
        f"📦 Tarif: `{plan_name} paket (+{days} kun)`\n"
        f"⭐️ To'landi: `{payment.total_amount} Stars`\n"
        f"📅 Obuna tugash muddati: `{new_end_date}`\n\n"
        "Barcha UTAG va mailing imkoniyatlaridan to'liq foydalanishingiz mumkin!",
        reply_markup=get_main_keyboard(user_id),
        parse_mode="markdown"
    )

    # Adminga xabar berish
    for adm_id in getattr(config, 'ADMIN_IDS', [config.ADMIN_ID]):
        try:
            await bot.send_message(
                adm_id,
                f"⭐️ **Yangi Stars to'lovi!**\n"
                f"👤 Foydalanuvchi: {message.from_user.full_name} (`{user_id}`)\n"
                f"📦 Tarif: `{plan_name}` ({payment.total_amount} Stars)\n"
                f"📅 Yangi muddat: `{new_end_date}`",
                parse_mode="markdown"
            )
        except Exception as e:
            logging.warning(f"Adminga Stars xabari yuborilmadi: {e}")


# B) ADMIN LICHKASI ORQALI TO'LOV VA APPROVAL TIZIMI

@dp.callback_query(F.data == "pay_via_admin")
async def choose_admin_payment_plan(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Haftalik ({config.WEEKLY_STARS} Stars ekvivalenti)", callback_data="proof_plan_weekly")],
        [InlineKeyboardButton(text=f"Oylik ({config.MONTHLY_STARS} Stars ekvivalenti)", callback_data="proof_plan_monthly")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="open_sub_menu")]
    ])
    await callback.message.edit_text(
        "<b>Karta / Admin lichkasi orqali to'lov</b>\n\n"
        "Qaysi tarifni tanlamoqchisiz? Tanlang va keyingi qadamda to'lov chekini yuboring:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.in_({"proof_plan_weekly", "proof_plan_monthly"}))
async def ask_payment_proof(callback: CallbackQuery, state: FSMContext):
    plan = "weekly" if callback.data == "proof_plan_weekly" else "monthly"
    stars = config.WEEKLY_STARS if plan == "weekly" else config.MONTHLY_STARS
    await state.update_data(payment_plan=plan, payment_stars=stars)

    plan_title = "Haftalik (7 kun)" if plan == "weekly" else "Oylik (30 kun)"
    await callback.message.answer(
        "<b>To'lov chekini yuboring</b>\n\n"
        f"Tanlangan tarif: <code>{plan_title}</code>\n\n"
        "To'lovni amalga oshirgach, chekning skrinshotini (rasm yoki fayl ko'rinishida) shu yerga yuboring.\n"
        "Admin tasdiqlashi bilan obunangiz avtomatik faollashadi.\n\n"
        "Bekor qilish uchun: <b>⬅️ Orqaga</b> tugmasini bosing.",
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(PaymentProofState.waiting_for_proof)
    await callback.answer()


@dp.message(PaymentProofState.waiting_for_proof, F.photo | F.document)
async def process_payment_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    plan = data.get("payment_plan", "weekly")
    stars = data.get("payment_stars", config.WEEKLY_STARS)
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    username = f"@{message.from_user.username}" if message.from_user.username else "Usernamesiz"

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id

    req_id = database.create_payment_request(user_id, plan, stars, file_id)
    await state.clear()

    await message.answer(
        "✅ **To'lov chekingiz adminga yuborildi!**\n\n"
        "Admin tekshirib tasdiqlagach, obunangiz faollashadi va sizga xabar keladi.",
        reply_markup=get_main_keyboard(user_id),
        parse_mode="markdown"
    )

    # Adminga so'rov yuborish
    admin_caption = (
        f"📩 **Yangi to'lov so'rovi (#{req_id})**\n\n"
        f"👤 Foydalanuvchi: {user_name} ({username})\n"
        f"🆔 ID: `{user_id}`\n"
        f"📦 Tarif: `{'Haftalik (7 kun)' if plan == 'weekly' else 'Oylik (30 kun)'}`\n"
        f"⭐️ Miqdor: `{stars} Stars ekvivalenti`\n\n"
        "To'lovni tasdiqlaysizmi?"
    )

    for adm_id in getattr(config, 'ADMIN_IDS', [config.ADMIN_ID]):
        try:
            if message.photo:
                await bot.send_photo(
                    chat_id=adm_id,
                    photo=file_id,
                    caption=admin_caption,
                    reply_markup=get_admin_approval_keyboard(req_id),
                    parse_mode="markdown"
                )
            else:
                await bot.send_document(
                    chat_id=adm_id,
                    document=file_id,
                    caption=admin_caption,
                    reply_markup=get_admin_approval_keyboard(req_id),
                    parse_mode="markdown"
                )
        except Exception as e:
            logging.error(f"Adminga so'rov yuborishda xato: {e}")


@dp.callback_query(F.data.startswith("pay_approve_"))
async def admin_approve_payment(callback: CallbackQuery):
    if not database.is_admin(callback.from_user.id):
        await callback.answer("Faqat admin uchun!", show_alert=True)
        return

    req_id = int(callback.data.replace("pay_approve_", ""))
    req = database.get_payment_request(req_id)
    if not req or req["status"] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan!", show_alert=True)
        return

    user_id = req["user_id"]
    plan = req["plan"]
    days = 7 if plan == "weekly" else 30

    new_end_date = database.add_subscription(user_id, days=days, payment_type="admin_approved")
    database.update_payment_request_status(req_id, "approved")

    # Foydalanuvchiga xabar yuborish
    try:
        await bot.send_message(
            user_id,
            f"✅ **To'lovingiz admin tomonidan tasdiqlandi!** 🎉\n\n"
            f"📦 Tarif: `{'Haftalik (+7 kun)' if plan == 'weekly' else 'Oylik (+30 kun)'}`\n"
            f"📅 Yangi obuna muddati: `{new_end_date}` gacha uzaytirildi.\n\n"
            "Endi UTAG tizimidan cheklovlarsiz foydalanishingiz mumkin!",
            reply_markup=get_main_keyboard(user_id),
            parse_mode="markdown"
        )
    except Exception as e:
        logging.warning(f"Foydalanuvchiga xabar borishida xato: {e}")

    try:
        await callback.message.edit_caption(
            caption=(callback.message.caption or "") + f"\n\n✅ **ADMIN TOMONIDAN TASDIQLANDI!** (+{days} kun berildi)",
            reply_markup=None,
            parse_mode="markdown"
        )
    except Exception:
        pass
    await callback.answer("✅ To'lov tasdiqlandi!")


@dp.callback_query(F.data.startswith("pay_reject_"))
async def admin_reject_payment(callback: CallbackQuery):
    if not database.is_admin(callback.from_user.id):
        await callback.answer("Faqat admin uchun!", show_alert=True)
        return

    req_id = int(callback.data.replace("pay_reject_", ""))
    req = database.get_payment_request(req_id)
    if not req or req["status"] != "pending":
        await callback.answer("Bu so'rov allaqachon ko'rib chiqilgan!", show_alert=True)
        return

    user_id = req["user_id"]
    database.update_payment_request_status(req_id, "rejected")

    try:
        await bot.send_message(
            user_id,
            "❌ **Afsuski, to'lov so'rovingiz admin tomonidan rad etildi.**\n"
            "Iltimos, chek to'g'riligini tekshiring yoki adminga to'g'ridan-to'g'ri murojaat qiling.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode="markdown"
        )
    except Exception:
        pass

    try:
        await callback.message.edit_caption(
            caption=(callback.message.caption or "") + "\n\n❌ **ADMIN TOMONIDAN BEKOR QILINDI!**",
            reply_markup=None,
            parse_mode="markdown"
        )
    except Exception:
        pass
    await callback.answer("❌ To'lov bekor qilindi.")


# --- GURUH MENYUSI VA OTMETKA AMALLARI ---

@dp.callback_query(F.data.startswith("gtag_"))
async def handle_group_menu_callbacks(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    data_parts = callback.data.split("_")
    action = data_parts[1]

    target_user_id = int(data_parts[2]) if len(data_parts) > 2 and data_parts[2].isdigit() else None
    session = group_sessions.get(chat_id)
    caller_id = target_user_id or (session["caller_id"] if session else None)

    # 1. Pauza / Davom ettirish / To'xtatish
    if action in ["pause", "resume", "stop"]:
        if caller_id and user_id != caller_id:
            await callback.answer("🔒 Bu tugmadan faqat otmetka boshlagan foydalanuvchi foydalana oladi!", show_alert=True)
            return

        effective_user_id = caller_id or user_id

        if action == "pause":
            if effective_user_id in tag_jobs and tag_jobs[effective_user_id]["status"] == "running":
                tag_jobs[effective_user_id]["status"] = "paused"
                try:
                    await callback.message.edit_reply_markup(reply_markup=get_group_control_keyboard("paused", effective_user_id))
                except Exception:
                    pass
                await callback.answer("⏸ Otmetka vaqtincha to'xtatildi (Pauza).")
            else:
                await callback.answer("Faol otmetka topilmadi yoki allaqachon to'xtatilgan.", show_alert=True)
            return

        elif action == "resume":
            if effective_user_id in tag_jobs and tag_jobs[effective_user_id]["status"] == "paused":
                tag_jobs[effective_user_id]["status"] = "running"
                try:
                    await callback.message.edit_reply_markup(reply_markup=get_group_control_keyboard("running", effective_user_id))
                except Exception:
                    pass
                await callback.answer("▶️ Otmetka davom ettirilmoqda...")
            else:
                await callback.answer("Faol otmetka topilmadi.", show_alert=True)
            return

        elif action == "stop":
            if effective_user_id in tag_jobs:
                step = tag_jobs[effective_user_id].get("current_step", 0)
                tag_jobs[effective_user_id]["status"] = "stopped"
                try:
                    await callback.message.edit_text(
                        f"🛑 **Otmetka jarayoni to'xtatildi.**\n📊 Jami: `{step}` ta a'zo belgilandi.",
                        parse_mode="markdown"
                    )
                except Exception:
                    pass
                await callback.answer("🛑 Otmetka to'xtatildi.")
            else:
                try:
                    await callback.message.edit_text("🛑 **Otmetka to'xtatildi.**", parse_mode="markdown")
                except Exception:
                    pass
                await callback.answer("Faol otmetka topilmadi.")
            return

    # 2. Boshqa menyu amallari
    if chat_id not in group_sessions:
        await callback.answer("❌ Bu seans eskirgan. Qaytadan ;utag yuboring.", show_alert=True)
        return

    session = group_sessions[chat_id]
    if user_id != session["caller_id"]:
        await callback.answer("🔒 Bu menyu faqat buyruq bergan foydalanuvchi uchun!", show_alert=True)
        return

    safe_caller_name = escape_markdown_v1(session.get("caller_name", "Foydalanuvchi"))

    if action == "text":
        await callback.message.answer(
            f"📝 [{safe_caller_name}](tg://user?id={user_id}), otmetka sarlavhasini yuboring (Bekor qilish uchun '⬅️ Orqaga'):",
            parse_mode="markdown"
        )
        await state.set_state(GroupTagSession.waiting_for_text)
        await state.update_data(target_chat_id=chat_id)
        await callback.answer()

    elif action == "limit":
        await callback.message.answer(
            f"🔢 [{safe_caller_name}](tg://user?id={user_id}), nechta user otmetka qilinsin? Son kiriting (maksimal 400 ta) yoki `all` deb yozing:",
            parse_mode="markdown"
        )
        await state.set_state(GroupTagSession.waiting_for_limit)
        await state.update_data(target_chat_id=chat_id)
        await callback.answer()

    elif action == "speed":
        current_spd = database.get_user_speed(user_id)
        # Guruh ichidagi tezlik tugmalari
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1.5s", callback_data="gtagspeed_1.5"),
                InlineKeyboardButton(text="2.0s", callback_data="gtagspeed_2.0"),
                InlineKeyboardButton(text="3.0s", callback_data="gtagspeed_3.0"),
                InlineKeyboardButton(text="5.0s", callback_data="gtagspeed_5.0")
            ]
        ])
        await callback.message.answer(f"⚡️ Otmetka tezligini tanlang (Hozirgi: `{current_spd}s`):", reply_markup=kb, parse_mode="markdown")
        await callback.answer()

    elif action == "start":
        await execute_group_tag(chat_id, user_id)
        await callback.answer()


@dp.callback_query(F.data.startswith("gtagspeed_"))
async def handle_group_speed_change(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    speed_val = float(callback.data.replace("gtagspeed_", ""))
    database.set_user_speed(user_id, speed_val)
    await callback.answer(f"⚡️ Tezlik {speed_val} soniyaga o'rnatildi!")
    try:
        await callback.message.edit_text(f"✅ Otmetka tezligi `{speed_val} soniya` qilib belgilandi.", parse_mode="markdown")
    except Exception:
        pass


@dp.message(GroupTagSession.waiting_for_text, F.text | F.sticker)
async def process_group_text_input(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await state.clear()
        await message.reply("Bekor qilindi.")
        return

    data = await state.get_data()
    chat_id = data.get("target_chat_id")
    user_id = message.from_user.id

    formatted_text = extract_aiogram_html_text(message)
    if chat_id in group_sessions and group_sessions[chat_id]["caller_id"] == user_id:
        group_sessions[chat_id]["text"] = formatted_text
        display_preview = message.text or (message.sticker.emoji if message.sticker else "Matn/Sticker")
        safe_preview = escape_markdown_v1(display_preview)
        await message.reply(f"✅ **Matn biriktirildi:** `{safe_preview}`", parse_mode="markdown")
    await state.clear()


@dp.message(GroupTagSession.waiting_for_limit)
async def process_group_limit_input(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await state.clear()
        await message.reply("Bekor qilindi.")
        return

    data = await state.get_data()
    chat_id = data.get("target_chat_id")
    user_id = message.from_user.id
    text = message.text.strip().lower()

    if chat_id in group_sessions and group_sessions[chat_id]["caller_id"] == user_id:
        if text.isdigit():
            user_val = int(text)
            final_limit = min(user_val, config.HARD_TAG_LIMIT)
            group_sessions[chat_id]["limit"] = final_limit
            if user_val > config.HARD_TAG_LIMIT:
                await message.reply(f"⚠️ Chegara: 400 tadan oshishi mumkin emas. **Limit {final_limit} ta** qilib belgilandi.", parse_mode="markdown")
            else:
                await message.reply(f"✅ **Limit o'rnatildi:** `{final_limit} ta`", parse_mode="markdown")
        else:
            group_sessions[chat_id]["limit"] = config.HARD_TAG_LIMIT
            await message.reply(f"✅ **Limit o'rnatildi:** `400 ta (Hard limit)`", parse_mode="markdown")
    await state.clear()


async def execute_group_tag(chat_id: int, user_id: int):
    """Guruh ichida otmetka jarayonini ishga tushirish."""
    if not database.is_subscribed(user_id):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="⚠️ **Otmetka boshlanmadi:** Userbot egasining obuna muddati tugagan! Bot orqali obunani yangilang."
            )
        except Exception:
            pass
        return

    if chat_id not in group_sessions:
        return

    session = group_sessions[chat_id]
    tag_text = session["text"]
    limit = session["limit"]

    if user_id in tag_jobs:
        tag_jobs[user_id]["status"] = "stopped"

    effective_limit = min(limit, config.HARD_TAG_LIMIT) if isinstance(limit, int) else config.HARD_TAG_LIMIT

    tag_jobs[user_id] = {
        "status": "running",
        "text": tag_text,
        "limit": effective_limit,
        "chat_id": chat_id,
        "current_step": 0
    }

    asyncio.create_task(background_tagging_task(user_id))


# --- BOTNING SHAXSIY CHATIDAGI MAILING VA TAGGING ---

@dp.message(F.text == "🚀 Guruhga xabar jo'natish")
async def start_mailing_process(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_user_access(message, user_id):
        return

    if user_id not in running_userbots:
        await message.answer("⚠️ Avval userbotni ulashingiz kerak!")
        return

    await message.answer(
        "1️⃣ Guruhga yubormoqchi bo'lgan **matningizni** kiriting:\n(Bekor qilish uchun: '⬅️ Orqaga')",
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="markdown"
    )
    await state.set_state(MailingState.waiting_for_text)


@dp.message(MailingState.waiting_for_text)
async def process_mailing_text(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await cmd_back(message, state)
        return

    await state.update_data(mailing_text=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Cheksiz yuborish", callback_data="loop_infinite")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_main_menu")]
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
    if message.text == "⬅️ Orqaga":
        await cmd_back(message, state)
        return

    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Iltimos, faqat butun son kiriting!")
        return
    await state.update_data(loop_count=int(text))
    await ask_for_groups(message, state, mode="mail")


@dp.message(F.text == "🏷 Userni belgilash")
async def start_tag_process(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_user_access(message, user_id):
        return

    if user_id not in running_userbots:
        await message.answer("⚠️ Avval userbotni ulashingiz kerak!")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Matnsiz (O'tkazib yuborish)", callback_data="skip_tag_text")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_main_menu")]
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


@dp.message(TagState.waiting_for_text, F.text | F.sticker)
async def process_tag_text(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await cmd_back(message, state)
        return

    formatted_text = extract_aiogram_html_text(message)
    await state.update_data(tag_text=formatted_text)
    await ask_tag_limit(message, state)


async def ask_tag_limit(message: Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔢 400 ta (Hard limit)", callback_data="tag_max_400")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_main_menu")]
    ])
    await message.answer(
        "2️⃣ Nechta user atmetka qilinsin? Son kiriting (maksimal 400) yoki tugmani bosing:",
        reply_markup=keyboard,
        parse_mode="markdown"
    )
    await state.set_state(TagState.waiting_for_limit)


@dp.callback_query(F.data == "tag_max_400", TagState.waiting_for_limit)
async def tag_max_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(tag_limit=config.HARD_TAG_LIMIT)
    await callback.answer()
    await ask_for_groups(callback.message, state, mode="tag")


@dp.message(TagState.waiting_for_limit)
async def process_tag_limit(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await cmd_back(message, state)
        return

    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Iltimos, faqat butun son kiriting!")
        return

    val = int(text)
    final_limit = min(val, config.HARD_TAG_LIMIT)
    await state.update_data(tag_limit=final_limit)
    if val > config.HARD_TAG_LIMIT:
        await message.answer(f"⚠️ Chegara: 400 tadan oshishi mumkin emas. Limit `{final_limit} ta` deb belgilandi.", parse_mode="markdown")
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
        # get_dialogs cache yuklash va guruhlarni saralash
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

    inline_keyboard.append([InlineKeyboardButton(text="⬅️ Bekor qilish", callback_data="back_to_main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer("3️⃣ Guruhingizni tanlang:", reply_markup=keyboard)


# --- BACKGROUND JOBS (MAILING & TAGGING) ---

@dp.callback_query(F.data.startswith("send_to_"))
async def start_mailing_job(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not await check_user_access(callback, user_id):
        return

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
    display_count = "Cheksiz" if loop_count == "infinite" else f"{loop_count} ta"
    await callback.message.answer(
        f"🚀 **Xabar yuborish boshlandi!**\n\n📝 Matn: `{safe_text}`\n🔢 Soni: `{display_count}`\n\n"
        "To'xtatish uchun: `/2` yoki quyidagi paneldan foydalaning:",
        reply_markup=get_control_panel("running", "mail"),
        parse_mode="markdown"
    )
    await callback.answer()
    asyncio.create_task(background_mailing_task(user_id))


async def send_background_message(cl: Client, chat_id: int | str, text: str, parse_mode: Optional[ParseMode] = ParseMode.HTML):
    """
    Xabarni Telegram MTProto `background=True` bayrog'i bilan yuborish.
    Bu xabarni guruhda to'liq saqlab qoladi (o'chirilmaydi), lekin Telegram ilovasida
    ekranning avtomatik ravishda yangi yuborilgan xabarga pastga surilib (scroll bo'lib) ketishini oldini oladi.
    """
    try:
        message, entities = (await utils.parse_text_entities(cl, text, parse_mode, None)).values()
        peer = await cl.resolve_peer(chat_id)
        return await cl.invoke(
            raw.functions.messages.SendMessage(
                peer=peer,
                message=message,
                entities=entities,
                random_id=cl.rnd_id(),
                background=True,
                no_webpage=True
            )
        )
    except FloodWait:
        raise
    except (AuthKeyUnregistered, AuthKeyInvalid, UserDeactivated, Unauthorized):
        raise
    except Exception as e:
        logging.warning(f"Background invoke ogohlantirish: {e}, fallback send_message ishlatilmoqda...")
        return await cl.send_message(chat_id, text, parse_mode=parse_mode)


async def background_mailing_task(user_id: int):
    if user_id not in running_userbots:
        try:
            await bot.send_message(user_id, "⚠️ Userbotingiz faol emas. Qayta ulashingiz kerak.")
        except Exception:
            pass
        return

    cl = running_userbots[user_id]

    try:
        while True:
            # Pauza / To'xtatilganlik holatini tekshirish
            while True:
                if user_id not in mailing_jobs or mailing_jobs[user_id].get("status") == "stopped":
                    return
                if mailing_jobs[user_id].get("status") == "paused":
                    await asyncio.sleep(0.5)
                else:
                    break

            job = mailing_jobs.get(user_id)
            if not job or job.get("status") == "stopped":
                return

            loop_count = job.get("loop_count")
            if loop_count != "infinite" and isinstance(loop_count, int) and job.get("current_step", 0) >= loop_count:
                try:
                    await bot.send_message(user_id, "✅ **Xabarlar yuborib bo'lindi!**")
                except Exception:
                    pass
                return

            try:
                await send_background_message(cl, job["chat_id"], job["text"], parse_mode=None)
                job["current_step"] += 1
            except FloodWait as e:
                logging.warning(f"Mailing FloodWait: {e.value} soniya kutilmoqda...")
                await asyncio.sleep(e.value)
            except (AuthKeyUnregistered, AuthKeyInvalid, UserDeactivated, Unauthorized) as e:
                logging.warning(f"User {user_id} sessiyasi bekor qilindi: {e}")
                database.delete_session(user_id)
                if user_id in running_userbots:
                    del running_userbots[user_id]
                try:
                    await bot.send_message(user_id, "⚠️ Telegram sessiyangiz bekor qilindi. Iltimos, userbotni qayta ulang.")
                except Exception:
                    pass
                return
            except Exception as e:
                try:
                    await bot.send_message(user_id, f"⚠️ Xatolik: {e}")
                except Exception:
                    pass
                return

            await asyncio.sleep(2.0)
    finally:
        if user_id in mailing_jobs:
            del mailing_jobs[user_id]


@dp.callback_query(F.data.startswith("tag_to_"))
async def start_tagging_job(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not await check_user_access(callback, user_id):
        return

    target_chat_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    tag_text = data.get("tag_text", "")
    tag_limit = data.get("tag_limit", config.HARD_TAG_LIMIT)
    await state.clear()

    if user_id in tag_jobs:
        tag_jobs[user_id]["status"] = "stopped"

    effective_limit = min(tag_limit, config.HARD_TAG_LIMIT) if isinstance(tag_limit, int) else config.HARD_TAG_LIMIT

    tag_jobs[user_id] = {
        "status": "running",
        "text": "" if tag_text == "NO_TEXT" else tag_text,
        "limit": effective_limit,
        "chat_id": target_chat_id,
        "current_step": 0
    }

    user_speed = database.get_user_speed(user_id)
    safe_text = escape_markdown_v1(tag_text) if tag_text and tag_text != "NO_TEXT" else "Matnsiz"
    await callback.message.answer(
        f"⚡️ **Otmetka qilish boshlandi!**\n\n📝 Sarlavha: `{safe_text}`\n🔢 Limit: `{effective_limit} ta`\n⏱ Tezlik: `{user_speed} soniya`\n\n"
        "Tezkor to'xtatish: `/2`",
        reply_markup=get_control_panel("running", "tag"),
        parse_mode="markdown"
    )
    await callback.answer()
    asyncio.create_task(background_tagging_task(user_id))


# SHAXSIY CHATDAGI BOSHQARUV TUGMALARI
@dp.callback_query(F.data.in_({"mail_pause", "tag_pause"}))
async def action_pause(callback: CallbackQuery):
    user_id = callback.from_user.id
    job_type = "mail" if callback.data == "mail_pause" else "tag"
    jobs_dict = mailing_jobs if job_type == "mail" else tag_jobs

    if user_id in jobs_dict and jobs_dict[user_id]["status"] == "running":
        jobs_dict[user_id]["status"] = "paused"
        try:
            await callback.message.edit_reply_markup(reply_markup=get_control_panel("paused", job_type))
        except Exception:
            pass
        await callback.answer("⏸ Jarayon vaqtincha to'xtatildi (Pauza).")
    else:
        await callback.answer("Faol jarayon topilmadi yoki allaqachon to'xtatilgan.", show_alert=True)


@dp.callback_query(F.data.in_({"mail_resume", "tag_resume"}))
async def action_resume(callback: CallbackQuery):
    user_id = callback.from_user.id
    job_type = "mail" if callback.data == "mail_resume" else "tag"
    jobs_dict = mailing_jobs if job_type == "mail" else tag_jobs

    if user_id in jobs_dict and jobs_dict[user_id]["status"] == "paused":
        jobs_dict[user_id]["status"] = "running"
        try:
            await callback.message.edit_reply_markup(reply_markup=get_control_panel("running", job_type))
        except Exception:
            pass
        await callback.answer("▶️ Jarayon davom ettirilmoqda...")
    else:
        await callback.answer("Faol jarayon topilmadi.", show_alert=True)


@dp.callback_query(F.data.in_({"mail_stop", "tag_stop"}))
async def action_stop(callback: CallbackQuery):
    user_id = callback.from_user.id
    job_type = "mail" if callback.data == "mail_stop" else "tag"
    jobs_dict = mailing_jobs if job_type == "mail" else tag_jobs

    if user_id in jobs_dict:
        step = jobs_dict[user_id].get("current_step", 0)
        jobs_dict[user_id]["status"] = "stopped"
        try:
            await callback.message.edit_text(f"🛑 **Jarayon to'xtatildi.** (Jami: `{step}` ta)", parse_mode="markdown")
        except Exception:
            pass
        await callback.answer("🛑 To'xtatildi.")
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
        safe_text = escape_markdown_v1(message.text)
        await message.answer(f"✅ **Xabar matni yangilandi:** `{safe_text}`", parse_mode="markdown")
    else:
        await message.answer("Tahrirlashga faol jarayon topilmadi.")
    await state.clear()


@dp.message(TagState.waiting_for_edit_text, F.text | F.sticker)
async def process_edited_tag_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    formatted_text = extract_aiogram_html_text(message)
    if user_id in tag_jobs:
        tag_jobs[user_id]["text"] = formatted_text
        display_preview = message.text or (message.sticker.emoji if message.sticker else "Matn/Sticker")
        safe_text = escape_markdown_v1(display_preview)
        await message.answer(f"✅ **Otmetka matni yangilandi:** `{safe_text}`", parse_mode="markdown")
    else:
        await message.answer("Tahrirlashga faol jarayon topilmadi.")
    await state.clear()


async def background_tagging_task(user_id: int):
    """
    Asinxron tag yuborish foni.
    - Sozlanadigan tezlik (1.5s - 5.0s)
    - 400 ta Hard Limit
    - Pyrogram PeerIdInvalid, KeyError va FloodWait xatolarini to'liq bartaraf etuvchi himoya
    """
    if user_id not in running_userbots:
        try:
            await bot.send_message(user_id, "⚠️ Userbotingiz faol emas. Qayta ulashingiz kerak.")
        except Exception:
            pass
        return

    cl = running_userbots[user_id]
    if user_id not in tag_jobs:
        return

    job = tag_jobs[user_id]
    chat_id = job["chat_id"]
    limit = job["limit"]

    # Foydalanuvchining bazadagi joriy tezligi
    sleep_interval = database.get_user_speed(user_id)

    try:
        # PeerIdInvalid va KeyError ni oldini olish uchun chatni xavfsiz keshlash
        try:
            await cl.get_chat(chat_id)
        except PeerIdInvalid:
            await warm_up_cache(cl)
            try:
                await cl.get_chat(chat_id)
            except Exception:
                pass
        except Exception:
            pass

        me = await cl.get_me()

        members = []
        try:
            async for member in cl.get_chat_members(chat_id):
                if member.user and not member.user.is_bot and not member.user.is_deleted:
                    if member.user.id != me.id:
                        members.append(member.user)
                # Hard limit 400 tadan oshib ketmasligi uchun
                if len(members) >= config.HARD_TAG_LIMIT:
                    break
        except Exception as e:
            logging.warning(f"Guruh a'zolarini olishda ogohlantirish: {e}")

        # Limitni qat'iy tekshirish
        hard_limit = min(limit, config.HARD_TAG_LIMIT) if isinstance(limit, int) else config.HARD_TAG_LIMIT
        members = members[:hard_limit]

        for u in members:
            # Pauza / To'xtatilganlik holatini tekshirish
            while True:
                if user_id not in tag_jobs or tag_jobs[user_id].get("status") == "stopped":
                    return
                if tag_jobs[user_id].get("status") == "paused":
                    await asyncio.sleep(0.5)
                else:
                    break

            current_job = tag_jobs.get(user_id)
            if not current_job or current_job.get("status") == "stopped":
                return

            if current_job.get("current_step", 0) >= config.HARD_TAG_LIMIT:
                logging.info(f"User {user_id} 400 ta hard limitga yetdi.")
                break

            if u.username:
                tag_mention = f"@{u.username}"
            else:
                clean_name = html.quote(u.first_name or "Foydalanuvchi")
                tag_mention = f'<a href="tg://user?id={u.id}">{clean_name}</a>'

            header = (current_job.get("text", "") or "").strip()
            if header and header != "NO_TEXT":
                msg_text = f"{tag_mention}   {header}"
            else:
                msg_text = tag_mention

            try:
                await send_background_message(cl, chat_id, msg_text, parse_mode=ParseMode.HTML)
                current_job["current_step"] += 1
            except FloodWait as e:
                logging.warning(f"FloodWait: {e.value} soniya kutilmoqda...")
                await asyncio.sleep(e.value)
            except (AuthKeyUnregistered, AuthKeyInvalid, UserDeactivated, Unauthorized) as e:
                logging.warning(f"User {user_id} sessiyasi bekor qilindi: {e}")
                database.delete_session(user_id)
                if user_id in running_userbots:
                    del running_userbots[user_id]
                try:
                    await bot.send_message(user_id, "⚠️ Telegram sessiyangiz bekor qilindi. Iltimos, userbotni qayta ulang.")
                except Exception:
                    pass
                return
            except Exception as e:
                try:
                    await send_background_message(cl, chat_id, msg_text, parse_mode=None)
                    current_job["current_step"] += 1
                except FloodWait as fw:
                    logging.warning(f"FloodWait: {fw.value} soniya kutilmoqda...")
                    await asyncio.sleep(fw.value)
                except Exception as ex:
                    logging.error(f"Tag yuborishda xato: {ex}")

            # Belgilangan tezlik (1.5s - 5.0s) bo'yicha kutish
            await asyncio.sleep(sleep_interval)

        # Otmetka yakunlanganda
        if user_id in tag_jobs and tag_jobs[user_id].get("status") == "running":
            final_step = tag_jobs[user_id].get("current_step", 0)
            reason = " (400 ta limitga yetdi)" if final_step >= config.HARD_TAG_LIMIT else ""
            if chat_id:
                try:
                    await bot.send_message(
                        chat_id,
                        f"✅ **Otmetka yakunlandi!**{reason}\n📊 Jami: `{final_step}` ta a'zo belgilandi.",
                        parse_mode="markdown"
                    )
                except Exception:
                    pass
            if user_id != chat_id:
                try:
                    await bot.send_message(user_id, f"⚡️ **Otmetka yakunlandi!** Jami: `{final_step}` ta.")
                except Exception:
                    pass

    except Exception as e:
        logging.error(f"Background tagging task error: {e}")
        try:
            await bot.send_message(user_id, f"⚠️ Xatolik: {e}")
        except Exception:
            pass
    finally:
        if user_id in tag_jobs:
            del tag_jobs[user_id]


# --- USERBOT SIKLI VA AUTHENTICATION ---

@dp.message(F.text == "⚙️ Userbot menyusi")
async def userbot_menu(message: Message):
    user_id = message.from_user.id
    is_running = user_id in running_userbots
    saved_session = database.get_saved_session(user_id)

    if is_running:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="⏸ Userbotni to'xtatish")],
                [KeyboardButton(text="🚪 Hisobdan chiqish (Logout)")],
                [KeyboardButton(text="⬅️ Orqaga")]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "✅ **Sizning userbotingiz faol holatda ishlamoqda.**\n\n"
           
           
          
        )
    elif saved_session:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="▶️ Userbotni yoqish")],
                [KeyboardButton(text="🚪 Hisobdan chiqish (Logout)")],
                [KeyboardButton(text="⬅️ Orqaga")]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "⏸ **Userbotingiz vaqtincha to'xtatilgan.**\n\n"
            "Telegram hisobingiz tizimda xavfsiz saqlangan. Qaytadan kod kiritmasdan ishga tushirish uchun "
            "**▶️ Userbotni yoqish** tugmasini bosing.",
            reply_markup=keyboard,
            parse_mode="markdown"
        )
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Userbotni ulash")], [KeyboardButton(text="⬅️ Orqaga")]],
            resize_keyboard=True
        )
        await message.answer("Sizda hali userbot ulanmagan:", reply_markup=keyboard)


@dp.message(F.text == "📱 Userbotni ulash")
async def start_auth(message: Message, state: FSMContext):
    await message.answer(
        "Iltimos, Telegram raqamingizni kiriting:\nFormat: `+998901234567`\n\n(Bekor qilish uchun: '⬅️ Orqaga')",
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="markdown"
    )
    await state.set_state(UserbotAuth.waiting_for_phone)


@dp.message(UserbotAuth.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await cmd_back(message, state)
        return

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
        await message.answer(
            "⚠️ **Kodni raqamlar orasiga nuqta qo'yib yuboring!** (Masalan: `5.4.3.2.1`)\n(Bekor qilish: '⬅️ Orqaga')",
            reply_markup=get_cancel_reply_keyboard(),
            parse_mode="markdown"
        )
        await state.set_state(UserbotAuth.waiting_for_code)
    except Exception as e:
        await message.answer(f"Xatolik: {str(e)}", reply_markup=get_main_keyboard(user_id))
        await client.disconnect()
        await state.clear()


@dp.message(UserbotAuth.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await cmd_back(message, state)
        return

    user_id = message.from_user.id
    code = message.text.strip().replace(".", "").replace(" ", "").replace("-", "")

    if user_id not in active_auth_clients:
        await message.answer("❌ Seans eskirgan. Qaytadan urinib ko'ring.", reply_markup=get_main_keyboard(user_id))
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

        database.save_session(
            user_id,
            phone,
            session_string,
            username=message.from_user.username,
            first_name=message.from_user.first_name
        )
        await start_userbot_worker(user_id, session_string)

        await message.answer("✅ **Userbot muvaffaqiyatli ulandi!**", reply_markup=get_main_keyboard(user_id), parse_mode="markdown")
        await state.clear()
    except SessionPasswordNeeded:
        await message.answer("🔐 2FA (Ikki bosqichli) parolingizni kiriting:", reply_markup=get_cancel_reply_keyboard())
        await state.set_state(UserbotAuth.waiting_for_password)
    except Exception as e:
        logging.error(f"Kod xatosi: {e}")
        await message.answer("❌ Kod noto'g'ri. Qaytadan kiriting (yoki '⬅️ Orqaga'):", reply_markup=get_cancel_reply_keyboard())


@dp.message(UserbotAuth.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    if message.text == "⬅️ Orqaga":
        await cmd_back(message, state)
        return

    user_id = message.from_user.id
    password = message.text.strip()

    if user_id not in active_auth_clients:
        await message.answer("❌ Seans eskirgan. Qaytadan urinib ko'ring.", reply_markup=get_main_keyboard(user_id))
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
        await message.answer("❌ Noto'g'ri parol. Qayta urinib ko'ring (yoki '⬅️ Orqaga'):", reply_markup=get_cancel_reply_keyboard())
        return

    try:
        await client.disconnect()
        del active_auth_clients[user_id]

        database.save_session(
            user_id,
            phone,
            session_string,
            username=message.from_user.username,
            first_name=message.from_user.first_name
        )
        await start_userbot_worker(user_id, session_string)

        await message.answer("✅ **Userbot muvaffaqiyatli ulandi!**", reply_markup=get_main_keyboard(user_id), parse_mode="markdown")
        await state.clear()
    except Exception as e:
        logging.error(f"Workerni yurgizish xatosi: {e}")
        await message.answer(f"⚠️ Xatolik: {e}", reply_markup=get_main_keyboard(user_id))


@dp.message(F.text.in_({"⏸ Userbotni to'xtatish", "❌ Userbotni o'chirish"}))
async def stop_userbot(message: Message):
    """Userbotni vaqtincha to'xtatadi, lekin sessiyani bazada xavfsiz saqlaydi (logout bo'lmaydi)."""
    user_id = message.from_user.id
    if user_id in running_userbots:
        try:
            await running_userbots[user_id].stop()
        except Exception as e:
            logging.warning(f"Userbot to'xtatish ogohlantirish ({user_id}): {e}")
        del running_userbots[user_id]
        
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="▶️ Userbotni yoqish")],
                [KeyboardButton(text="🚪 Hisobdan chiqish (Logout)")],
                [KeyboardButton(text="⬅️ Orqaga")]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "⏸ **Userbot vaqtincha to'xtatildi!**\n\n"
            "✅ Sessiyangiz bazada xavfsiz saqlandi (logout bo'lmadi).\n"
            "Istalgan vaqt **▶️ Userbotni yoqish** tugmasini bosib, qayta kod kiritmasdan ishga tushirishingiz mumkin.",
            reply_markup=keyboard,
            parse_mode="markdown"
        )
    else:
        saved_session = database.get_saved_session(user_id)
        if saved_session:
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="▶️ Userbotni yoqish")],
                    [KeyboardButton(text="🚪 Hisobdan chiqish (Logout)")],
                    [KeyboardButton(text="⬅️ Orqaga")]
                ],
                resize_keyboard=True
            )
            await message.answer(
                "⏸ Userbotingiz allaqachon to'xtatilgan holatda.",
                reply_markup=keyboard
            )
        else:
            await message.answer("Sizda faol userbot topilmadi.", reply_markup=get_main_keyboard(user_id))


@dp.message(F.text == "▶️ Userbotni yoqish")
async def start_saved_userbot(message: Message):
    """Saqlangan sessiya orqali userbotni qayta kod so'ramasdan 1 soniyada yoqadi."""
    user_id = message.from_user.id
    if user_id in running_userbots:
        await message.answer("✅ Userbotingiz allaqachon faol ishlab turibdi!", reply_markup=get_main_keyboard(user_id))
        return

    saved_session = database.get_saved_session(user_id)
    if not saved_session:
        await message.answer("⚠️ Saqlangan sessiya topilmadi. Iltimos, userbotni qaytadan ulang.", reply_markup=get_main_keyboard(user_id))
        return

    msg = await message.answer("🔄 Userbot ishga tushirilmoqda...")
    try:
        await start_userbot_worker(user_id, saved_session)
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="⏸ Userbotni to'xtatish")],
                [KeyboardButton(text="🚪 Hisobdan chiqish (Logout)")],
                [KeyboardButton(text="⬅️ Orqaga")]
            ],
            resize_keyboard=True
        )
        await msg.edit_text("✅ **Userbot muvaffaqiyatli ishga tushirildi!**", parse_mode="markdown")
        await message.answer("Siz botdan to'liq foydalanishingiz mumkin:", reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Userbotni qayta yoqishda xato ({user_id}): {e}")
        await msg.edit_text(f"⚠️ Userbotni ishga tushirishda xatolik: {e}")


@dp.message(F.text == "🚪 Hisobdan chiqish (Logout)")
async def prompt_logout(message: Message):
    """Foydalanuvchi hisobdan butunlay chiqmoqchi bo'lsa tasdiqlash so'raydi."""
    user_id = message.from_user.id
    saved_session = database.get_saved_session(user_id)
    if not saved_session and user_id not in running_userbots:
        await message.answer("Sizda ulangan hisob mavjud emas.", reply_markup=get_main_keyboard(user_id))
        return

    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚪 Ha, hisobdan chiqish", callback_data="confirm_userbot_logout"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_userbot_logout")
        ]
    ])
    await message.answer(
        "⚠️ **Haqiqatan ham Telegram userbot hisobingizdan chiqmoqchimisiz?**\n\n"
        "❗️ *Hisobdan chiqsangiz, sessiyangiz o'chiriladi va keyingi safar qaytadan telefon raqam hamda SMS kod kiritishingiz kerak bo'ladi.*",
        reply_markup=confirm_keyboard,
        parse_mode="markdown"
    )


@dp.callback_query(F.data == "confirm_userbot_logout")
async def handle_confirm_logout(callback: CallbackQuery):
    """Foydalanuvchi hisobdan chiqishni tasdiqlaganda sessiyani tozalaydi."""
    user_id = callback.from_user.id
    if user_id in running_userbots:
        try:
            await running_userbots[user_id].stop()
        except Exception:
            pass
        del running_userbots[user_id]
    database.delete_session(user_id)

    try:
        await callback.message.edit_text("🚪 **Siz userbot hisobingizdan muvaffaqiyatli chiqdingiz.**\nSessiya tozalandi.", parse_mode="markdown")
    except Exception:
        pass
    await callback.message.answer("Asosiy menyu:", reply_markup=get_main_keyboard(user_id))
    await callback.answer("Hisobdan chiqildi.")


@dp.callback_query(F.data == "cancel_userbot_logout")
async def handle_cancel_logout(callback: CallbackQuery):
    """Hisobdan chiqishni bekor qiladi."""
    try:
        await callback.message.edit_text("Amal bekor qilindi.")
    except Exception:
        pass
    await callback.answer("Bekor qilindi.")


# --- MA'LUMOTLARNI CHIQARISH (EXPORT & INFO) ---

@dp.message(F.text.in_({"ℹ️ Mening ma'lumotlarim", "/myinfo"}))
async def cmd_my_info(message: Message):
    """Guruh tahlili va ma'lumotlar faqat Adminlar uchun ochiq."""
    if not database.is_admin(message.from_user.id):
        await message.answer("🔒 Ushbu bo'lim o'chirilgan. Guruhlar tahlilini faqat Adminlar amalga oshira oladi!")
        return
    await message.answer("ℹ️ Guruhlar va foydalanuvchilar tahlilini faqat **📊 Admin Panel** orqali amalga oshirishingiz mumkin.", parse_mode="markdown")


@dp.message(F.text.in_({"📥 Barcha ma'lumotlarni eksport", "/export_all"}))
async def cmd_export_all(message: Message, user_id: Optional[int] = None):
    """Admin uchun barcha ulangan foydalanuvchilar va ularning guruhlarini to'liq eksport qilish."""
    target_user_id = user_id if user_id is not None else (message.from_user.id if message.from_user else None)
    if not database.is_super_admin(target_user_id):
        await message.answer("🔒 Bu ma'lumotlarni eksport qilish faqat Bosh Adminlar (ADMIN_ID_1 va ADMIN_ID_2) uchun ruxsat etilgan!")
        return

    await message.answer("🔄 Barcha foydalanuvchilar va guruhlar ma'lumotlari to'planmoqda...")

    users = database.get_all_users_full()
    total_userbots = len(running_userbots)

    report_lines = [
        "==================================================",
        "          UTAG TIZIMI UMUMIY EKSPORT HISOBOTI     ",
        f"          Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "==================================================\n",
        f"Jami foydalanuvchilar: {len(users)} ta",
        f"Faol Userbotlar: {total_userbots} ta\n",
        "--------------------------------------------------"
    ]

    for idx, u in enumerate(users, 1):
        uid = u["user_id"]
        phone = u.get("phone", "Noma'lum")
        sub_end = u.get("subscription_end") or "Obuna yo'q"
        speed = u.get("speed", 2.0)
        is_running = "FAOL" if uid in running_userbots else "NOFAOL"

        uname = f"@{u.get('username')}" if u.get("username") else "Usernamesiz"
        fname = f" ({u.get('first_name')})" if u.get("first_name") else ""
        report_lines.append(f"\n[{idx}] FOYDALANUVCHI: ID {uid} | Username: {uname}{fname} | Tel: {phone}")
        report_lines.append(f"    - Holati: {is_running} | Tezlik: {speed}s")
        report_lines.append(f"    - Obuna muddati: {sub_end}")

        # Guruhlarini olish
        if uid in running_userbots:
            cl = running_userbots[uid]
            try:
                g_list = []
                async for dialog in cl.get_dialogs(limit=50):
                    if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                        g_list.append(f"      • {dialog.chat.title} (ID: {dialog.chat.id})")
                if g_list:
                    report_lines.append(f"    - A'zo bo'lgan guruhlari ({len(g_list)} ta):")
                    report_lines.extend(g_list)
                else:
                    report_lines.append("    - Guruhlar: Topilmadi")
            except Exception as e:
                report_lines.append(f"    - Guruhlarni yuklashda xato: {e}")
        else:
            report_lines.append("    - Guruhlar: (Userbot ulanmagan)")

    full_report = "\n".join(report_lines)
    file_bytes = full_report.encode("utf-8")
    input_file = BufferedInputFile(file_bytes, filename=f"utag_export_{datetime.now().strftime('%Y%m%d_%H%M')}.txt")

    await message.answer_document(
        document=input_file,
        caption="📊 **Barcha foydalanuvchilar va guruhlar bo'yicha to'liq hisobot.**",
        parse_mode="markdown"
    )


# --- ADMIN PANEL VA WEB APP TUGMASI ---

@dp.message(F.text == "📊 Admin Panel")
async def admin_panel(message: Message):
    if not database.is_super_admin(message.from_user.id):
        await message.answer("🔒 Ushbu panel faqat Bosh Adminlar (1784313012 va 1052561222) uchun ruxsat etilgan!")
        return

    stats = database.get_stats()
    current_url = (config.WEBAPP_URL or "").strip().rstrip("/")
    is_localhost = not current_url or any(h in current_url.lower() for h in ["localhost", "127.0.0.1", "0.0.0.0"])

    buttons = []
    hint_text = ""

    if not is_localhost and current_url.startswith("https://"):
        base_admin = f"{current_url}/admin" if not current_url.endswith("/admin") else current_url
        webapp_url = f"{base_admin}?admin_id={message.from_user.id}"
        buttons.append([InlineKeyboardButton(text="🌐 Web App Admin Panel", web_app=WebAppInfo(url=webapp_url))])
    elif not is_localhost and current_url.startswith("http://"):
        base_admin = f"{current_url}/admin" if not current_url.endswith("/admin") else current_url
        webapp_url = f"{base_admin}?admin_id={message.from_user.id}"
        buttons.append([InlineKeyboardButton(text="🌐 Web App Admin Panel", url=webapp_url)])
    else:
        # Telegram serveri localhost havolali tugmalarni qabul qilmaydi (Wrong HTTP URL xatosi beradi)
        local_url = f"http://localhost:{config.WEBAPP_PORT}/admin?admin_id={message.from_user.id}"
        hint_text = (
            "\n\n⚠️ <b>Telegram Web App (HTTPS) sozlanmagan:</b>\n"
            "Telegram inline tugmalari faqat rasmiy internet manzillari (HTTPS) bilan ishlaydi.\n\n"
            f"💻 <b>Brauzer orqali kirish (Lokal):</b>\n<code>{local_url}</code>\n\n"
            "💡 <b>Telegram tugmasini yoqish uchun:</b>\n"
            "Render 'Environment' bo'limida <code>WEBAPP_URL</code> o'zgaruvchisiga HTTPS havolangizni kiriting "
            "(masalan: <code>https://your-service.onrender.com</code>)."
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    response_text = (
        "<b>UTAG Boshqaruv Paneli:</b>\n\n"
        f"• Jami foydalanuvchilar: <code>{stats['total_users']}</code> ta\n"
        f"• Faol Userbotlar: <code>{len(running_userbots)}</code> ta\n"
        f"• Faol obunalar: <code>{stats['active_subs']}</code> ta\n"
        f"• Obunasi tugaganlar: <code>{stats['expired_subs']}</code> ta\n"
        f"• Kutilayotgan so'rovlar: <code>{stats['pending_requests']}</code> ta"
        f"{hint_text}"
    )

    try:
        await message.answer(response_text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        logging.error(f"Admin panel xabarini yuborishda xatolik: {e}")
        await message.answer(response_text, parse_mode="HTML")


@dp.message(F.text == "📚 Qo'llanma")
async def cmd_guide(message: Message):
    await message.answer(
        "📚 **UTAG Foydalanish Qo'llanmasi:**\n\n"
        "1️⃣ **Userbot ulash:** '⚙️ Userbot menyusi' orqali telefon raqamingizni kiriting va kodni nuqta bilan yozing.\n"
        "2️⃣ **Guruh ichida:** Guruhda **`;utag`** yoki **`.utag`** deb yozsangiz, bot sozlash va boshqaruv menyusini yuboradi.\n"
        "3️⃣ **Tezkor buyruqlar:** Guruh ichida **`/1`** — otmetkani boshlaydi, **`/2`** — otmetkani to'xtatadi.\n"
        "4️⃣ **Tezlik:** 1.5s, 2s, 3s, 5s intervallaridan birini tanlashingiz mumkin.\n"
        "5️⃣ **Chegara:** Bitta otmetka seansida maksimal 400 ta a'zo belgilanadi (Telegram cheklovlariga muvofiq).\n"
        "6️⃣ **Obuna:** Haftalik (50 Stars) va Oylik (200 Stars) paketlar Telegram Stars yoki karta orqali faollashadi.",
        parse_mode="markdown"
    )


# --- STARTUP VA SHUTDOWN ---

async def on_startup():
    logging.info("Baza sxemasi ishga tushirilmoqda...")
    database.init_db()

    # Web App serverini va reklama kontekstini ishga tushirish
    webapp.set_broadcast_context(bot, running_userbots)
    try:
        await webapp.start_webapp_server()
    except Exception as e:
        logging.warning(f"Web App start ogohlantirish: {e}")

    # Avtomatik Cloudflare Tunnel (faqat WEBAPP_URL o'rnatilmagan bo'lsa va lokal Windows bo'lsa)
    if config.WEBAPP_URL:
        logging.info(f"🚀 Telegram Web App uchun belgilangan HTTPS havola: {config.WEBAPP_URL}")
    else:
        try:
            tunnel_url = tunnel.start_tunnel_sync(config.WEBAPP_PORT)
            if tunnel_url:
                config.WEBAPP_URL = tunnel_url
                logging.info(f"🚀 Telegram Web App uchun toza HTTPS havola o'rnatildi: {tunnel_url}")
        except Exception as e:
            logging.warning(f"Tunnel start ogohlantirish: {e}")

    # Barcha mavjud userbot sessiyalarini qayta yuklash
    sessions = database.get_all_sessions()
    logging.info(f"Topilgan sessiyalar soni: {len(sessions)}")
    for user_id, session_string in sessions:
        if not session_string or not str(session_string).strip():
            continue
        try:
            await start_userbot_worker(user_id, session_string)
        except Exception as e:
            logging.error(f"Sessiyani yuklashda xato (User {user_id}): {e}")


async def on_shutdown():
    logging.info("Barcha faol userbotlar to'xtatilmoqda...")
    tunnel.stop_tunnel()
    for user_id, client in list(running_userbots.items()):
        try:
            if client.is_connected:
                await client.stop()
        except Exception:
            pass
    running_userbots.clear()
    await bot.session.close()


async def main():
    await on_startup()
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")
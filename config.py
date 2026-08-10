import os

# Serverda (Render.com) Environment Variables orqali o'qiladi.
# Agar topilmasa, ikkinchi parametrda ko'rsatilgan qiymatlardan foydalaniladi.

API_ID = int(os.getenv("API_ID", "33465516"))
API_HASH = os.getenv("API_HASH", "8c3c061c71bdbb70da28dc677b13e678")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8901205517:AAGkmnMqUs5OVBffwES1yJXzJgRFKVcmeMo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1784313012"))

import sqlite3
import logging

DB_NAME = "userbots.db"

def init_db():
    """Ma'lumotlar bazasini va 'users' jadvalini yaratadi (agar mavjud bo'lmasa)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            phone TEXT NOT NULL,
            session_string TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    logging.info("Ma'lumotlar bazasi muvaffaqiyatli ishga tushirildi.")


def save_session(user_id: int, phone: str, session_string: str):
    """Foydalanuvchining userbot sessiya ma'lumotlarini saqlaydi yoki yangilaydi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, phone, session_string)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            phone = excluded.phone,
            session_string = excluded.session_string
    """, (user_id, phone, session_string))
    conn.commit()
    conn.close()


def delete_session(user_id: int):
    """Foydalanuvchi userbotini o'chirib tashlaganda bazadan o'chiradi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_all_sessions():
    """Bot qayta ishga tushganida barcha faol sessiyalarni yuklab olish uchun."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, session_string FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_users_count() -> int:
    """Admin panel uchun: Jami ulangan foydalanuvchilar sonini qaytaradi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_users_list():
    """Admin panel uchun: Ulangan barcha foydalanuvchilar ro'yxatini (ID va telefon) qaytaradi."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, phone FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows
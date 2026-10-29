import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import config

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

DB_NAME = "userbots.db"
IS_POSTGRES = bool(config.DATABASE_URL and psycopg2 is not None)


class PGCursorWrapper:
    """PostgreSQL kursorini SQLite sintaksisiga (va parametrlariga) moslashtiruvchi wrapper."""
    def __init__(self, cur):
        self._cur = cur
        self._lastrowid = None

    def execute(self, sql: str, params: Any = None):
        sql = sql.replace("?", "%s")
        if "INSERT OR IGNORE INTO admins" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO admins", "INSERT INTO admins")
            if "ON CONFLICT" not in sql:
                sql += " ON CONFLICT (user_id) DO NOTHING"

        # Avtomatik lastrowid olish uchun RETURNING id qo'shish
        is_payment_insert = "INSERT INTO payment_requests" in sql and "RETURNING" not in sql
        if is_payment_insert:
            sql += " RETURNING id"

        if params is not None:
            self._cur.execute(sql, params)
        else:
            self._cur.execute(sql)

        if is_payment_insert:
            try:
                row = self._cur.fetchone()
                if row and "id" in row:
                    self._lastrowid = row["id"]
            except Exception:
                pass
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        return self._lastrowid

    def __getattr__(self, name):
        return getattr(self._cur, name)


class PGConnectionWrapper:
    """PostgreSQL ulanishini SQLite interfeysiga moslashtiruvchi wrapper."""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return PGCursorWrapper(self._conn.cursor())

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_connection():
    """Ma'lumotlar bazasi ulanishini qaytaradi (PostgreSQL yoki SQLite)."""
    if IS_POSTGRES:
        conn = psycopg2.connect(config.DATABASE_URL, cursor_factory=RealDictCursor)
        return PGConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn


def _migrate_from_sqlite(pg_conn):
    """Lokal SQLite faylidan foydalanuvchilar va sessiyalarni PostgreSQL ga ko'chiradi."""
    try:
        if not os.path.exists(DB_NAME):
            return
        s_conn = sqlite3.connect(DB_NAME)
        s_conn.row_factory = sqlite3.Row
        s_cur = s_conn.cursor()

        # Users
        s_cur.execute("SELECT * FROM users")
        s_users = s_cur.fetchall()
        pg_cur = pg_conn.cursor()
        for u in s_users:
            ud = dict(u)
            pg_cur.execute("""
                INSERT INTO users (user_id, phone, session_string, speed, subscription_end, payment_status, created_at, username, first_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (
                ud.get("user_id"),
                ud.get("phone", ""),
                ud.get("session_string", ""),
                ud.get("speed", 2.0),
                ud.get("subscription_end"),
                ud.get("payment_status", "none"),
                ud.get("created_at"),
                ud.get("username"),
                ud.get("first_name")
            ))

        # Admins
        s_cur.execute("SELECT * FROM admins")
        for a in s_cur.fetchall():
            ad = dict(a)
            pg_cur.execute("""
                INSERT INTO admins (user_id, added_by, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (ad.get("user_id"), ad.get("added_by", 0), ad.get("created_at")))

        # Payment requests
        s_cur.execute("SELECT * FROM payment_requests")
        for p in s_cur.fetchall():
            pd = dict(p)
            pg_cur.execute("""
                INSERT INTO payment_requests (user_id, plan, stars, status, proof_file_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (pd.get("user_id"), pd.get("plan"), pd.get("stars"), pd.get("status"), pd.get("proof_file_id"), pd.get("created_at")))

        pg_conn.commit()
        s_conn.close()
        logging.info(f"✅ SQLite ({DB_NAME}) dagi {len(s_users)} ta foydalanuvchi PostgreSQL ga muvaffaqiyatli ko'chirildi!")
    except Exception as e:
        logging.warning(f"SQLite dan migratsiya ogohlantirish: {e}")


def init_db():
    """
    Ma'lumotlar bazasini va jadvallarni yaratadi / yangilaydi (migratsiya).
    Sxema:
      users: user_id, phone, session_string, speed, subscription_end, payment_status, created_at
      payment_requests: id, user_id, plan, stars, status, proof_file_id, created_at
    """
    conn = get_connection()
    cursor = conn.cursor()

    if IS_POSTGRES:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                phone TEXT NOT NULL DEFAULT '',
                session_string TEXT NOT NULL DEFAULT '',
                speed REAL DEFAULT 2.0,
                subscription_end TEXT,
                payment_status TEXT DEFAULT 'none',
                created_at TEXT,
                username TEXT,
                first_name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_requests (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                plan TEXT NOT NULL,
                stars INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                proof_file_id TEXT,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT DEFAULT 0,
                created_at TEXT
            )
        """)
        conn.commit()
        # Bo'sh bo'lsa SQLite dan avtomatik ko'chirish
        try:
            cursor.execute("SELECT COUNT(*) AS cnt FROM users")
            row = cursor.fetchone()
            if row and row["cnt"] == 0:
                _migrate_from_sqlite(conn)
        except Exception as e:
            logging.warning(f"Migratsiya tekshiruvida ogohlantirish: {e}")
        conn.close()
        logging.info("🐘 PostgreSQL ma'lumotlar bazasi muvaffaqiyatli tekshirildi va ishga tushirildi.")
        return

    # SQLite sxemasi
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            phone TEXT NOT NULL DEFAULT '',
            session_string TEXT NOT NULL DEFAULT '',
            speed REAL DEFAULT 2.0,
            subscription_end TEXT,
            payment_status TEXT DEFAULT 'none',
            created_at TEXT,
            username TEXT,
            first_name TEXT
        )
    """)

    # Mavjud jadvalga yangi ustunlarni xavfsiz qo'shish (migratsiya)
    cursor.execute("PRAGMA table_info(users)")
    columns = [row["name"] for row in cursor.fetchall()]

    if "speed" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN speed REAL DEFAULT 2.0")
    if "subscription_end" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN subscription_end TEXT")
    if "payment_status" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN payment_status TEXT DEFAULT 'none'")
    if "created_at" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
    if "username" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if "first_name" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")

    # 2. payment_requests jadvali (Admin lichkasi orqali to'lov so'rovlari)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            stars INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            proof_file_id TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # 3. admins jadvali (Yangi tayinlangan adminlar)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()
    logging.info("Ma'lumotlar bazasi sxemasi muvaffaqiyatli tekshirildi va yangilandi.")


def update_user_info(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None):
    """Foydalanuvchining username va ismini bazada saqlaydi yoki yangilaydi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, phone, session_string, username, first_name)
        VALUES (?, '', '', ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = CASE WHEN excluded.username IS NOT NULL AND excluded.username != '' THEN excluded.username ELSE users.username END,
            first_name = CASE WHEN excluded.first_name IS NOT NULL AND excluded.first_name != '' THEN excluded.first_name ELSE users.first_name END
    """, (user_id, username, first_name))
    conn.commit()
    conn.close()


def save_session(user_id: int, phone: str, session_string: str, username: Optional[str] = None, first_name: Optional[str] = None):
    """Foydalanuvchining userbot sessiya ma'lumotlarini saqlaydi yoki yangilaydi."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO users (user_id, phone, session_string, speed, created_at, username, first_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            phone = excluded.phone,
            session_string = excluded.session_string,
            username = CASE WHEN excluded.username IS NOT NULL THEN excluded.username ELSE users.username END,
            first_name = CASE WHEN excluded.first_name IS NOT NULL THEN excluded.first_name ELSE users.first_name END
    """, (user_id, phone, session_string, config.DEFAULT_SPEED, now_str, username, first_name))
    conn.commit()
    conn.close()


def delete_session(user_id: int):
    """Foydalanuvchi userbot sessiyasini tozalaydi (obuna va ma'lumotlarni saqlagan holda)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET session_string = '', phone = '' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_saved_session(user_id: int) -> Optional[str]:
    """Foydalanuvchining bazada saqlangan faol sessiya matnini qaytaradi (agar mavjud bo'lsa)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT session_string FROM users WHERE user_id = ? AND session_string IS NOT NULL AND TRIM(session_string) != ''", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row["session_string"] if row else None


def get_all_sessions() -> List[Tuple[int, str]]:
    """Bot qayta ishga tushganida barcha faol sessiyalarni yuklab olish uchun."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, session_string FROM users WHERE session_string IS NOT NULL AND TRIM(session_string) != ''")
    rows = cursor.fetchall()
    result = [(row["user_id"], row["session_string"]) for row in rows]
    conn.close()
    return result


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Foydalanuvchi ma'lumotlarini to'liq oladi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# --- TEZLIK (SPEED) SOZLAMALARI ---

def get_user_speed(user_id: int) -> float:
    """Foydalanuvchining tag yuborish tezligini (soniya) oladi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT speed FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row["speed"] is not None:
        return float(row["speed"])
    return config.DEFAULT_SPEED


def set_user_speed(user_id: int, speed: float) -> bool:
    """Foydalanuvchining tag yuborish tezligini yangilaydi (1.5, 2.0, 3.0, 5.0)."""
    if speed not in config.ALLOWED_SPEEDS:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, phone, session_string, speed)
        VALUES (?, '', '', ?)
        ON CONFLICT(user_id) DO UPDATE SET speed = excluded.speed
    """, (user_id, speed))
    conn.commit()
    conn.close()
    return True


# --- OBUNA (SUBSCRIPTION) VA TO'LOV TIZIMI ---

def is_subscribed(user_id: int) -> bool:
    """
    Foydalanuvchining obunasi faol ekanligini tekshiradi.
    Bot admini har doim cheksiz obunaga ega.
    """
    if is_admin(user_id):
        return True

    user = get_user(user_id)
    if not user or not user.get("subscription_end"):
        return False

    try:
        sub_end = datetime.strptime(user["subscription_end"], "%Y-%m-%d %H:%M:%S")
        return sub_end > datetime.now()
    except Exception:
        return False


def get_subscription_info(user_id: int) -> Dict[str, Any]:
    """Obuna holati haqida to'liq axborot qaytaradi."""
    if is_admin(user_id):
        return {
            "is_active": True,
            "status": "admin",
            "end_date": "Cheksiz",
            "days_left": None,
            "display_text": "Faol (Cheksiz)"
        }

    user = get_user(user_id)
    if not user or not user.get("subscription_end"):
        return {
            "is_active": False,
            "status": "none",
            "end_date": "Obuna yo'q",
            "days_left": 0,
            "display_text": "Obuna yo'q"
        }

    try:
        sub_end = datetime.strptime(user["subscription_end"], "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        if sub_end > now:
            delta = sub_end - now
            days_left = delta.days if delta.days > 0 else 0
            return {
                "is_active": True,
                "status": user.get("payment_status", "active"),
                "end_date": sub_end.strftime("%Y-%m-%d %H:%M"),
                "days_left": days_left,
                "display_text": f"Faol ({days_left} kun qoldi)"
            }
        else:
            return {
                "is_active": False,
                "status": "expired",
                "end_date": f"Tugagan ({sub_end.strftime('%Y-%m-%d')})",
                "days_left": 0,
                "display_text": f"Muddati tugagan"
            }
    except Exception:
        return {
            "is_active": False,
            "status": "invalid",
            "end_date": "Xatolik",
            "days_left": 0,
            "display_text": "Noma'lum"
        }


def add_subscription(user_id: int, days: int, payment_type: str = "active") -> str:
    """
    Foydalanuvchiga obuna muddati qo'shadi.
    Agar joriy obunasi faol bo'lsa, mavjud muddat ustiga qo'shiladi.
    Aks holda hozirgi vaqtdan hisoblanadi.
    Yangi tugash sanasini qaytaradi.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    now = datetime.now()
    base_time = now

    if row and row["subscription_end"]:
        try:
            current_end = datetime.strptime(row["subscription_end"], "%Y-%m-%d %H:%M:%S")
            if current_end > now:
                base_time = current_end
        except Exception:
            base_time = now

    new_end = base_time + timedelta(days=days)
    new_end_str = new_end.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO users (user_id, phone, session_string, subscription_end, payment_status)
        VALUES (?, '', '', ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            subscription_end = excluded.subscription_end,
            payment_status = excluded.payment_status
    """, (user_id, new_end_str, payment_type))
    conn.commit()
    conn.close()
    return new_end_str


def remove_subscription(user_id: int):
    """Foydalanuvchining obunasini bekor qiladi / tozalaydi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users
        SET subscription_end = NULL, payment_status = 'expired'
        WHERE user_id = ?
    """, (user_id,))
    conn.commit()
    conn.close()


# --- TO'LOV SO'ROVLARI (ADMIN APPROVAL) ---

def create_payment_request(user_id: int, plan: str, stars: int, proof_file_id: Optional[str] = None) -> int:
    """Yangi to'lov so'rovini bazaga kiritadi."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO payment_requests (user_id, plan, stars, status, proof_file_id, created_at)
        VALUES (?, ?, ?, 'pending', ?, ?)
    """, (user_id, plan, stars, proof_file_id, now_str))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return req_id


def record_stars_payment(user_id: int, plan: str, stars: int, charge_id: Optional[str] = None) -> int:
    """Telegram Stars orqali amalga oshirilgan muvaffaqiyatli to'lovni bazaga yozadi."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO payment_requests (user_id, plan, stars, status, proof_file_id, created_at)
        VALUES (?, ?, ?, 'stars_paid', ?, ?)
    """, (user_id, plan, int(stars), charge_id or "stars_invoice", now_str))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return req_id


def get_payment_request(request_id: int) -> Optional[Dict[str, Any]]:
    """To'lov so'rovi ma'lumotlarini oladi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM payment_requests WHERE id = ?", (request_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_payment_request_status(request_id: int, status: str) -> bool:
    """To'lov so'rovi holatini yangilaydi ('approved' yoki 'rejected')."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE payment_requests SET status = ? WHERE id = ?", (status, request_id))
    conn.commit()
    conn.close()
    return True


# --- ADMIN VA WEB APP UCHUN FUNKSIYALAR ---

def get_stats() -> Dict[str, Any]:
    """Tizim bo'yicha umumiy statistikani qaytaradi."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM users")
    total_users = cursor.fetchone()["total"]

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        SELECT COUNT(*) AS active_subs FROM users
        WHERE subscription_end IS NOT NULL AND subscription_end > ?
    """, (now_str,))
    active_subs = cursor.fetchone()["active_subs"]

    cursor.execute("SELECT COUNT(*) AS pending_requests FROM payment_requests WHERE status = 'pending'")
    pending_reqs = cursor.fetchone()["pending_requests"]

    # Stars tushumlari (payment_requests jadvalidagi stars_paid yig'indisi)
    cursor.execute("SELECT COALESCE(SUM(stars), 0) AS total_stars FROM payment_requests WHERE status = 'stars_paid'")
    paid_stars_sum = cursor.fetchone()["total_stars"] or 0

    # Agar avval payment_status = 'stars' bo'lib yozilgan userlar bo'lsa
    cursor.execute("SELECT COUNT(*) AS stars_users FROM users WHERE payment_status = 'stars'")
    stars_users_cnt = cursor.fetchone()["stars_users"] or 0
    db_stars = max(int(paid_stars_sum), int(stars_users_cnt) * int(getattr(config, "WEEKLY_STARS", 50)))

    # Obuna turlari bo'yicha statistika
    cursor.execute("""
        SELECT payment_status, COUNT(*) AS cnt FROM users
        WHERE subscription_end IS NOT NULL AND subscription_end > ?
        GROUP BY payment_status
    """, (now_str,))
    sub_breakdown = {row["payment_status"] or "other": row["cnt"] for row in cursor.fetchall()}

    # Oxirgi 7 kunlik obunalar va foydalanuvchilar dinamikasi (Grafik uchun)
    chart_labels = []
    chart_subs = []
    chart_unsub = []
    uz_days = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]

    cursor.execute("SELECT created_at, subscription_end FROM users")
    all_u_rows = cursor.fetchall()

    for i in range(6, -1, -1):
        day_dt = now - timedelta(days=i)
        day_end_str = day_dt.strftime("%Y-%m-%d 23:59:59")
        label = f"{uz_days[day_dt.weekday()]} ({day_dt.strftime('%d.%m')})"
        chart_labels.append(label)

        act_on_day = 0
        unsub_on_day = 0
        for r in all_u_rows:
            c_at = r["created_at"]
            s_end = r["subscription_end"]
            # Shu kungacha ro'yxatdan o'tgan userlar
            if c_at and c_at <= day_end_str:
                if s_end and s_end > day_end_str:
                    act_on_day += 1
                else:
                    unsub_on_day += 1
        chart_subs.append(act_on_day)
        chart_unsub.append(unsub_on_day)

    # Oxirgi kun (bugun) aniq hozirgi ko'rsatkichga teng bo'lishi uchun
    if chart_subs:
        chart_subs[-1] = active_subs
        chart_unsub[-1] = max(0, total_users - active_subs)

    conn.close()

    return {
        "total_users": total_users,
        "active_subs": active_subs,
        "expired_subs": max(0, total_users - active_subs),
        "pending_requests": pending_reqs,
        "db_stars": db_stars,
        "sub_breakdown": sub_breakdown,
        "chart": {
            "labels": chart_labels,
            "subscribed": chart_subs,
            "unsubscribed": chart_unsub
        }
    }


def is_super_admin(user_id: int) -> bool:
    """Foydalanuvchi Bosh Admin (ADMIN_ID_1 yoki ADMIN_ID_2) ekanligini tekshiradi."""
    try:
        u_id = int(user_id)
    except (ValueError, TypeError):
        return False
    super_admins = [
        int(getattr(config, "ADMIN_ID_1", 1784313012)),
        int(getattr(config, "ADMIN_ID_2", 1052561222))
    ]
    return u_id in super_admins


def is_admin(user_id: int) -> bool:
    """Foydalanuvchi Bosh Admin yoki tayinlangan Admin ekanligini tekshiradi."""
    if is_super_admin(user_id):
        return True
    try:
        u_id = int(user_id)
    except (ValueError, TypeError):
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (u_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)


def add_admin(user_id: int, added_by: int = 0) -> bool:
    """Foydalanuvchiga admin huquqini beradi."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT OR IGNORE INTO admins (user_id, added_by, created_at)
        VALUES (?, ?, ?)
    """, (int(user_id), int(added_by), now_str))
    conn.commit()
    conn.close()
    return True


def remove_admin(user_id: int) -> bool:
    """Foydalanuvchidan admin huquqini oladi (Superadminlarni o'chirib bo'lmaydi)."""
    if is_super_admin(user_id):
        return False  # Bosh adminlarni o'chirish taqiqlangan!
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = ?", (int(user_id),))
    conn.commit()
    conn.close()
    return True


def get_all_admin_ids() -> List[int]:
    """Barcha adminlar (Superadminlar + tayinlanganlar) ro'yxatini qaytaradi."""
    super_admins = [
        int(getattr(config, "ADMIN_ID_1", 1784313012)),
        int(getattr(config, "ADMIN_ID_2", 1052561222))
    ]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins")
    rows = cursor.fetchall()
    conn.close()
    extra = [row["user_id"] for row in rows]
    return list(set(super_admins + extra))


def get_all_users_full() -> List[Dict[str, Any]]:
    """Barcha foydalanuvchilar ro'yxatini to'liq holda qaytaradi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, phone, speed, subscription_end, payment_status, created_at, username, first_name FROM users")
    rows = cursor.fetchall()
    conn.close()

    now = datetime.now()
    users = []
    for r in rows:
        u = dict(r)
        sub_end = u.get("subscription_end")
        is_act = False
        days_left = 0
        if sub_end:
            try:
                dt = datetime.strptime(sub_end, "%Y-%m-%d %H:%M:%S")
                if dt > now:
                    is_act = True
                    days_left = (dt - now).days
            except Exception:
                pass

        is_super = is_super_admin(u["user_id"])
        is_adm = is_admin(u["user_id"])
        if is_super or is_adm:
            is_act = True
            if not days_left:
                days_left = "∞"

        u["is_active"] = is_act
        u["days_left"] = days_left
        u["is_super_admin"] = is_super
        u["is_admin"] = is_adm
        users.append(u)
    return users


def get_users_count() -> int:
    """Jami ulangan foydalanuvchilar soni."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM users")
    count = cursor.fetchone()["cnt"]
    conn.close()
    return count


def get_users_list() -> List[Tuple[int, str]]:
    """Foydalanuvchilarning ID va telefonlari."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, phone FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [(row["user_id"], row["phone"]) for row in rows]


# Modul yuklanganda bazani va yangi ustunlarni avtomatik initsializatsiya qilish
try:
    init_db()
except Exception as e:
    logging.warning(f"Database init ogohlantirish: {e}")
"""
DARKZONA Donate Bot — PREMIUM (BLACKdev)
=========================================
Ishga tushirish:   pip install -r requirements.txt     keyin     python main.py

Fayllar: faqat main.py va requirements.txt kerak. Baza (Donate.db), logs/ va backups/
papkalari bot ishga tushganda o'zi yaratiladi.
Hamma sozlama (matnlar, narxlar, RCON, emoji, to'lov usullari...) bot ichidagi admin paneldan o'zgartiriladi.

DIQQAT: token va parol yozilgan bu faylni GitHub'ga yoki boshqa odamga bermang!
"""
# ============================ SOZLAMALAR (faqat shu yerni to'ldiring) ============================
BOT_TOKEN = "9074327606:AAG3qE41PZqOdXe9tXEIrXho2W-pck5iubI"   # @BotFather bergan token
SUPER_ADMIN_ID = 8681116778              # Super Admin Telegram ID (botga /id yozsangiz ko'rsatadi)

RCON_HOST = "127.0.0.1"                 # Minecraft server IP (bot shu serverda bo'lsa 127.0.0.1)
RCON_PORT = 25575                       # server.properties -> rcon.port
RCON_PASSWORD = "CHANGE_ME"             # server.properties -> rcon.password

SERVER_HOST = "darkzona.gomc.uz"        # o'yinchilar kiradigan IP/domen (keyin admin paneldan o'zgartiriladi)
SERVER_PORT = 25565
SERVER_VERSION = "Paper 1.17.1"
SUPPORT_CONTACT = "@darkzona_support"
DB_PATH = "Donate.db"
# ================================================================================================
# Eslatma: server/RCON/support qiymatlari bazaga BIRINCHI ishga tushishda yoziladi. Keyin ularni
# admin panel orqali o'zgartiring. (Xohlasangiz token/parol/ID ni muhit o'zgaruvchilari orqali ham
# berish mumkin: BOT_TOKEN, SUPER_ADMIN_ID, RCON_PASSWORD, RCON_HOST, RCON_PORT.)

import html
import json
import logging
import os
import queue
import re
import shutil
import socket
import sqlite3
import struct
import threading
import time
import uuid
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = (os.environ.get('BOT_TOKEN') or BOT_TOKEN).strip()
RCON_PASSWORD = os.environ.get('RCON_PASSWORD') or RCON_PASSWORD
RCON_HOST = os.environ.get('RCON_HOST') or RCON_HOST
try:
    SUPER_ADMIN_ID = int(os.environ.get('SUPER_ADMIN_ID') or SUPER_ADMIN_ID)
    RCON_PORT = int(os.environ.get('RCON_PORT') or RCON_PORT)
except ValueError:
    pass
SUPER = SUPER_ADMIN_ID if isinstance(SUPER_ADMIN_ID, int) and SUPER_ADMIN_ID > 0 else 0

# ============================ LOGGING (maxfiy ma'lumotlar maskalanadi) ============================
SECRETS = set()
_TOKEN_RE = re.compile(r'bot\d{5,}:[A-Za-z0-9_-]{20,}')


def register_secret(s):
    if s and len(str(s)) >= 4 and str(s) not in ('CHANGE_ME',):
        SECRETS.add(str(s))


class MaskFormatter(logging.Formatter):
    def format(self, record):
        s = super().format(record)
        for x in list(SECRETS):
            s = s.replace(x, '***')
        return _TOKEN_RE.sub('bot***', s)


def setup_logging():
    os.makedirs('logs', exist_ok=True)
    fmt = MaskFormatter('%(asctime)s %(levelname)s [%(name)s] %(message)s')
    fh = RotatingFileHandler('logs/bot.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    sh = logging.StreamHandler()
    for h in (fh, sh):
        h.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers[:] = [fh, sh]
    root.setLevel(logging.INFO)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


register_secret(BOT_TOKEN)
register_secret(RCON_PASSWORD)
setup_logging()
log = logging.getLogger('bot')

# ============================ DOIMIY MA'LUMOTLAR ============================
LINE = '━━━━━━━━━━━━━━━━━━'
SCHEMA_VERSION = 2

STATUS_UZ = {
    'PENDING': 'To‘lov kutilmoqda', 'PAYMENT_REVIEW': 'To‘lov tekshirilmoqda', 'APPROVED': 'Tasdiqlandi',
    'PROCESSING': 'Serverda bajarilmoqda', 'COMPLETED': 'Bajarildi', 'FAILED': 'Xatolik',
    'REJECTED': 'Rad etildi', 'CANCELLED': 'Bekor qilindi',
}
OPEN_STATUSES = ('PENDING', 'PAYMENT_REVIEW', 'APPROVED', 'PROCESSING', 'FAILED')

# emoji kaliti: (oddiy emoji, bo'lim, nomi)
EMOJI_SECTIONS = {'start': 'Start', 'rank': 'Rank', 'token': 'Token', 'title': 'Titul',
                  'status': 'Buyurtma statuslari', 'admin': 'Admin panel', 'server': 'Server statuslari'}
EMOJI_DEFAULTS = {
    'start': ('🌑', 'start', 'Start emoji'),
    'cat_rank': ('💎', 'rank', 'Rank bo‘limi'),
    'cat_token': ('🪙', 'token', 'Token bo‘limi'),
    'cat_title': ('⚔️', 'title', 'Titul bo‘limi'),
    'st_PENDING': ('🟡', 'status', 'PENDING'),
    'st_PAYMENT_REVIEW': ('🔎', 'status', 'PAYMENT_REVIEW'),
    'st_APPROVED': ('🔵', 'status', 'APPROVED'),
    'st_PROCESSING': ('⚙️', 'status', 'PROCESSING'),
    'st_COMPLETED': ('🟢', 'status', 'COMPLETED'),
    'st_FAILED': ('🟠', 'status', 'FAILED'),
    'st_REJECTED': ('🔴', 'status', 'REJECTED'),
    'st_CANCELLED': ('⚪', 'status', 'CANCELLED'),
    'adm_panel': ('🛠', 'admin', 'Admin panel sarlavhasi'),
    'adm_orders': ('📥', 'admin', 'Buyurtmalar'),
    'adm_products': ('📦', 'admin', 'Mahsulotlar'),
    'adm_settings': ('⚙️', 'admin', 'Sozlamalar'),
    'srv_online': ('🟢', 'server', 'ONLINE'),
    'srv_offline': ('🔴', 'server', 'OFFLINE'),
    'srv_unknown': ('🟡', 'server', 'UNKNOWN'),
}

SEED_CATS = [('rank', 'Ranklar', 'Premium ranklar — barcha ranklar 30 kunlik.', 1),
             ('token', 'Tokenlar', 'Token paketlari.', 2),
             ('title', 'Titullar', 'Chat va tab uchun maxsus titullar.', 3)]
_R = 'lp user {player} parent addtemp %s {days}d accumulate'
SEED = [
    ('rank', 'IMPERATOR', 70000, 30, 'Eng yuqori premium rank', '👑', _R % 'imperator'),
    ('rank', 'GENERAL', 66000, 30, 'Premium rank', '🔴', _R % 'general'),
    ('rank', 'AFSONA', 54000, 30, 'Afsonaviy rank', '🟣', _R % 'afsona'),
    ('rank', 'ELITA', 46000, 30, 'Elita rank', '🔵', _R % 'elita'),
    ('rank', 'TITAN', 23000, 30, 'Titan rank', '🟠', _R % 'titan'),
    ('rank', 'QAHRAMON', 15000, 30, 'Qahramon rank', '🟢', _R % 'qahramon'),
    ('rank', 'ASKAR', 3000, 30, 'Boshlang‘ich rank', '⚪', _R % 'askar'),
    ('token', '1K TOKEN', 5000, 0, '1 000 token', '🪙', 'tokens give {player} 1000'),
    ('token', '10K TOKEN', 13000, 0, '10 000 token', '🪙', 'tokens give {player} 10000'),
    ('token', '25K TOKEN', 16000, 0, '25 000 token', '🪙', 'tokens give {player} 25000'),
    ('token', '40K TOKEN', 23000, 0, '40 000 token', '🪙', 'tokens give {player} 40000'),
    ('token', '60K TOKEN', 30000, 0, '60 000 token', '🪙', 'tokens give {player} 60000'),
    ('token', '80K TOKEN', 42000, 0, '80 000 token', '🪙', 'tokens give {player} 80000'),
    ('token', '100K TOKEN', 53000, 0, '100 000 token', '🪙', 'tokens give {player} 100000'),
    ('title', '[PVPER]', 10000, 0, 'PVPER titul', '🏹', 'lp user {player} permission set title.pvper true'),
    ('title', '[EZZ]', 15000, 0, 'EZZ titul', '⚡', 'lp user {player} permission set title.ezz true'),
    ('title', '[YENGILMAS]', 20000, 0, 'YENGILMAS titul', '🛡️', 'lp user {player} permission set title.yengilmas true'),
    ('title', '[AFSONAVIY]', 30000, 0, 'AFSONAVIY titul', '✨', 'lp user {player} permission set title.afsonaviy true'),
    ('title', '[KILLER]', 40000, 0, 'KILLER titul', '☠️', 'lp user {player} permission set title.killer true'),
    ('title', '[TOPER]', 50000, 0, 'TOPER titul', '🏆', 'lp user {player} permission set title.toper true'),
]
TEXT_DEFAULTS = {
    'start_text': '🌑 <b>DARKZONA</b> ga xush kelibsiz!\nPremium Minecraft donate shop — rank, token va titullar shu yerda.',
    'welcome_text': '🌑 <b>DARKZONA</b> • Premium Donate Shop\nKerakli bo‘limni tanlang 👇',
    'payment_text': 'To‘lovni quyidagi usullardan biri orqali amalga oshiring:',
    'order_accepted_text': '🧾 Chek qabul qilindi!\nBuyurtma <b>#{order_id}</b> admin tekshiruviga yuborildi. Natija haqida xabar beramiz.',
    'order_completed_text': '🟢 Buyurtma <b>#{order_id}</b> bajarildi!\n{product} → <b>{player}</b>\nO‘yindan zavq oling! 🎮',
    'order_rejected_text': '🔴 Buyurtma <b>#{order_id}</b> rad etildi.\nSavollar bo‘lsa admin bilan bog‘laning.',
    'server_about_text': 'DARKZONA — premium Minecraft server.',
}
SERVER_DEFAULTS = {
    'server_name': 'DARKZONA', 'server_host': SERVER_HOST, 'server_port': str(SERVER_PORT),
    'server_version': SERVER_VERSION, 'server_description': 'Premium Minecraft server',
    'telegram_link': '', 'discord_link': '', 'website': '', 'support': SUPPORT_CONTACT,
}
RCON_DEFAULTS = {
    'enabled': 'true', 'host': str(RCON_HOST), 'port': str(RCON_PORT), 'password': '',
    'cooldown': '1.0', 'retries': '3', 'last_ok': '', 'last_error': '', 'last_check': '',
}
SETTINGS_DEFAULTS = {'order_cooldown': '30', 'max_pending': '3', 'maintenance': 'false',
                     'custom_emoji': 'true', 'button_styles': 'true'}

PERMS = {
    'orders_view': '📥 Buyurtmalarni ko‘rish',
    'orders_manage': '✅ To‘lovni tekshirish / buyurtmani tasdiqlash',
    'products': '📦 Mahsulotlar va narxlar',
    'payments': '💳 To‘lov usullari',
    'texts': '📝 Bot matnlari',
    'emoji': '🎨 Emoji va dizayn',
    'server': '🖥 Server sozlamalari',
    'users': '👥 Foydalanuvchilar',
    'stats': '📊 Statistika',
    'broadcast': '📢 Xabar yuborish',
}
DEFAULT_PERMS = ('orders_view', 'orders_manage')

# ============================ BAZA ============================


@contextmanager
def db_conn():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,banned INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP,last_seen TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY,role TEXT DEFAULT 'admin',perms TEXT DEFAULT '',added_by INTEGER,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS product_categories(code TEXT PRIMARY KEY,name TEXT,description TEXT DEFAULT '',sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,name TEXT,price INTEGER,duration INTEGER DEFAULT 0,description TEXT DEFAULT '',emoji TEXT DEFAULT '🎁',emoji_id TEXT DEFAULT '',command TEXT DEFAULT '',active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,product_id INTEGER,product_name TEXT,price INTEGER,player TEXT,status TEXT DEFAULT 'PENDING',receipt_file_id TEXT,receipt_kind TEXT DEFAULT 'photo',command_snapshot TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,updated TEXT DEFAULT CURRENT_TIMESTAMP,execution_key TEXT UNIQUE,error TEXT,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS payment_methods(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,description TEXT DEFAULT '',details TEXT DEFAULT '',active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER,user_id INTEGER,file_id TEXT,kind TEXT DEFAULT 'photo',status TEXT DEFAULT 'SUBMITTED',created TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(order_id) REFERENCES orders(id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS emoji_settings(key TEXT PRIMARY KEY,emoji TEXT,custom_id TEXT DEFAULT '',section TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS rcon_settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS server_settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,actor INTEGER,action TEXT,details TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS order_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER,event TEXT,details TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category,active);
CREATE INDEX IF NOT EXISTS idx_users_created ON users(created);
'''


def _add_col(c, table, col, ddl):
    cols = [r['name'] for r in c.execute('PRAGMA table_info(%s)' % table)]
    if col not in cols:
        c.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table, col, ddl))


def db_init():
    with db_conn() as c:
        c.execute('PRAGMA journal_mode=WAL')
        ver = c.execute('PRAGMA user_version').fetchone()[0]
        c.executescript(SCHEMA)
        # --- migratsiyalar (eski bazalar uchun) ---
        _add_col(c, 'orders', 'receipt_kind', "TEXT DEFAULT 'photo'")
        _add_col(c, 'products', 'emoji_id', "TEXT DEFAULT ''")
        _add_col(c, 'users', 'banned', 'INTEGER DEFAULT 0')
        _add_col(c, 'users', 'last_seen', 'TEXT')
        _add_col(c, 'admins', 'perms', "TEXT DEFAULT ''")
        if ver < 2:
            for r in c.execute("SELECT key,value FROM settings").fetchall():
                k = r['key']
                if k in SERVER_DEFAULTS:
                    c.execute('INSERT OR IGNORE INTO server_settings(key,value) VALUES(?,?)', (k, r['value']))
                    c.execute('DELETE FROM settings WHERE key=?', (k,))
                elif k.startswith('rcon_'):
                    c.execute('INSERT OR IGNORE INTO rcon_settings(key,value) VALUES(?,?)', (k[5:], r['value']))
                    c.execute('DELETE FROM settings WHERE key=?', (k,))
            c.execute("UPDATE admins SET perms=? WHERE perms IS NULL OR perms=''", (','.join(DEFAULT_PERMS),))
        # --- boshlang'ich ma'lumotlar ---
        for code, name, desc, sort in SEED_CATS:
            c.execute('INSERT OR IGNORE INTO product_categories(code,name,description,sort) VALUES(?,?,?,?)', (code, name, desc, sort))
        if not c.execute('SELECT 1 FROM products LIMIT 1').fetchone():
            c.executemany('INSERT INTO products(category,name,price,duration,description,emoji,command) VALUES(?,?,?,?,?,?,?)', SEED)
        if not c.execute('SELECT 1 FROM payment_methods LIMIT 1').fetchone():
            c.execute('INSERT INTO payment_methods(name,description,details) VALUES(?,?,?)',
                      ('💳 Karta', 'Karta orqali o‘tkazma', 'Admin panel → To‘lov usullari bo‘limida rekvizitlarni kiriting.'))
        for k, v in {**TEXT_DEFAULTS, **SETTINGS_DEFAULTS}.items():
            c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (k, v))
        for k, v in SERVER_DEFAULTS.items():
            c.execute('INSERT OR IGNORE INTO server_settings(key,value) VALUES(?,?)', (k, v))
        for k, v in RCON_DEFAULTS.items():
            c.execute('INSERT OR IGNORE INTO rcon_settings(key,value) VALUES(?,?)', (k, v))
        for k, (e, sec, _label) in EMOJI_DEFAULTS.items():
            c.execute('INSERT OR IGNORE INTO emoji_settings(key,emoji,custom_id,section) VALUES(?,?,?,?)', (k, e, '', sec))
        c.execute('PRAGMA user_version=%d' % SCHEMA_VERSION)
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


# ---- kalit/qiymat jadvallari ----
_KV = ('settings', 'rcon_settings', 'server_settings')


def kv_get(table, key, default=''):
    assert table in _KV
    with db_conn() as c:
        r = c.execute('SELECT value FROM %s WHERE key=?' % table, (key,)).fetchone()
        return r['value'] if r and r['value'] is not None else default


def kv_set(table, key, value):
    assert table in _KV
    with db_conn() as c:
        c.execute('INSERT INTO %s(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value' % table, (key, str(value)))


def setting(k, d=''):
    return kv_get('settings', k, d)


def set_setting(k, v):
    kv_set('settings', k, v)


def rget(k, d=''):
    return kv_get('rcon_settings', k, d)


def rset(k, v):
    kv_set('rcon_settings', k, v)
    if k == 'password':
        register_secret(v)


def sget(k, d=''):
    return kv_get('server_settings', k, d)


def sset(k, v):
    kv_set('server_settings', k, v)


# ---- emoji ----
_EM = {}
_EM_LOCK = threading.Lock()
UI = {'custom': True, 'styles': True}


def emoji_reload():
    with db_conn() as c:
        rows = c.execute('SELECT key,emoji,custom_id FROM emoji_settings').fetchall()
    with _EM_LOCK:
        _EM.clear()
        _EM.update({r['key']: (r['emoji'] or '', r['custom_id'] or '') for r in rows})
    UI['custom'] = setting('custom_emoji', 'true') == 'true'
    UI['styles'] = setting('button_styles', 'true') == 'true'


def db_emoji_set(key, emoji=None, custom_id=None):
    with db_conn() as c:
        if emoji is not None:
            c.execute('UPDATE emoji_settings SET emoji=? WHERE key=?', (emoji, key))
        if custom_id is not None:
            c.execute('UPDATE emoji_settings SET custom_id=? WHERE key=?', (custom_id, key))
    emoji_reload()


def db_emoji_reset(key):
    e = EMOJI_DEFAULTS[key][0]
    with db_conn() as c:
        c.execute("UPDATE emoji_settings SET emoji=?,custom_id='' WHERE key=?", (e, key))
    emoji_reload()


def db_emoji_rows(section):
    with db_conn() as c:
        return c.execute('SELECT * FROM emoji_settings WHERE section=? ORDER BY rowid', (section,)).fetchall()


def _emo_row(key):
    with _EM_LOCK:
        row = _EM.get(key)
    if row:
        return row
    return (EMOJI_DEFAULTS.get(key, ('•',))[0], '')


def emo_plain(key):
    return _emo_row(key)[0] or EMOJI_DEFAULTS.get(key, ('•',))[0]


def emo_id(key):
    cid = _emo_row(key)[1]
    return cid if (cid and UI['custom']) else ''


def emo(key):
    """HTML ko'rinishidagi emoji (custom emoji bo'lsa <tg-emoji>, aks holda oddiy)."""
    e, cid = _emo_row(key)
    e = html.escape(e or '•')
    if cid and UI['custom']:
        return '<tg-emoji emoji-id="%s">%s</tg-emoji>' % (cid, e)
    return e


# ---- mahsulotlar ----
def db_categories():
    with db_conn() as c:
        return c.execute('SELECT * FROM product_categories ORDER BY sort').fetchall()


def db_category(code):
    with db_conn() as c:
        return c.execute('SELECT * FROM product_categories WHERE code=?', (code,)).fetchone()


def db_set_cat_desc(code, desc):
    with db_conn() as c:
        c.execute('UPDATE product_categories SET description=? WHERE code=?', (desc, code))


def db_product(pid):
    with db_conn() as c:
        return c.execute('SELECT * FROM products WHERE id=? AND active=1', (pid,)).fetchone()


def db_products(cat=None):
    with db_conn() as c:
        if cat:
            return c.execute('SELECT * FROM products WHERE active=1 AND category=? ORDER BY id', (cat,)).fetchall()
        return c.execute('SELECT * FROM products WHERE active=1 ORDER BY category,id').fetchall()


def db_save_product(pid, field, value):
    if field not in ('name', 'price', 'duration', 'description', 'emoji', 'emoji_id', 'command'):
        raise ValueError('field')
    with db_conn() as c:
        c.execute('UPDATE products SET %s=? WHERE id=?' % field, (value, pid))


def db_add_product(cat, name, price, duration, desc, emoji, command):
    with db_conn() as c:
        cur = c.execute('INSERT INTO products(category,name,price,duration,description,emoji,command) VALUES(?,?,?,?,?,?,?)',
                        (cat, name, price, duration, desc, emoji, command))
        return cur.lastrowid


def db_delete_product(pid):
    with db_conn() as c:
        c.execute('UPDATE products SET active=0 WHERE id=?', (pid,))


# ---- foydalanuvchilar ----
def db_user(u):
    with db_conn() as c:
        c.execute('INSERT INTO users(id,username,first_name,last_seen) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_seen=CURRENT_TIMESTAMP',
                  (u.id, u.username, u.first_name))


def db_is_banned(uid):
    with db_conn() as c:
        r = c.execute('SELECT banned FROM users WHERE id=?', (uid,)).fetchone()
        return bool(r and r['banned'])


def db_set_ban(uid, flag):
    with db_conn() as c:
        c.execute('UPDATE users SET banned=? WHERE id=?', (1 if flag else 0, uid))


def db_users_count():
    with db_conn() as c:
        return c.execute('SELECT COUNT(*) FROM users').fetchone()[0]


def db_users_page(offset, limit):
    with db_conn() as c:
        return c.execute('SELECT * FROM users ORDER BY created DESC,id DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()


def db_find_user(q):
    q = (q or '').strip().lstrip('@')
    with db_conn() as c:
        if q.isdigit():
            return c.execute('SELECT * FROM users WHERE id=?', (int(q),)).fetchone()
        return c.execute('SELECT * FROM users WHERE lower(username)=lower(?)', (q,)).fetchone()


def db_user_info(uid):
    with db_conn() as c:
        u = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not u:
            return None
        s = c.execute("SELECT COUNT(*) n,SUM(status='COMPLETED') done,COALESCE(SUM(CASE WHEN status='COMPLETED' THEN price END),0) spent FROM orders WHERE user_id=?", (uid,)).fetchone()
        return {'user': u, 'orders': s['n'] or 0, 'done': s['done'] or 0, 'spent': s['spent'] or 0}


def db_all_user_ids():
    with db_conn() as c:
        return [r['id'] for r in c.execute('SELECT id FROM users WHERE banned=0')]


# ---- adminlar ----
def db_admin_add(uid, by, perms=DEFAULT_PERMS):
    with db_conn() as c:
        c.execute('INSERT OR IGNORE INTO admins(id,role,perms,added_by) VALUES(?,?,?,?)', (uid, 'admin', ','.join(perms), by))


def db_admin_remove(uid):
    with db_conn() as c:
        c.execute('DELETE FROM admins WHERE id=?', (uid,))


def db_is_admin(uid):
    with db_conn() as c:
        return bool(c.execute('SELECT 1 FROM admins WHERE id=?', (uid,)).fetchone())


def db_admin_perms(uid):
    with db_conn() as c:
        r = c.execute('SELECT perms FROM admins WHERE id=?', (uid,)).fetchone()
        return set(p for p in (r['perms'] or '').split(',') if p) if r else set()


def db_admin_set_perms(uid, perms):
    with db_conn() as c:
        c.execute('UPDATE admins SET perms=? WHERE id=?', (','.join(sorted(perms)), uid))


def db_admins():
    with db_conn() as c:
        return c.execute('SELECT * FROM admins ORDER BY created').fetchall()


def db_admins_with(perm):
    ids = []
    for a in db_admins():
        if perm in (a['perms'] or '').split(','):
            ids.append(a['id'])
    return ids


# ---- to'lov usullari ----
def db_pm_list():
    with db_conn() as c:
        return c.execute('SELECT * FROM payment_methods WHERE active=1 ORDER BY id').fetchall()


def db_pm_get(pid):
    with db_conn() as c:
        return c.execute('SELECT * FROM payment_methods WHERE id=?', (pid,)).fetchone()


def db_pm_add(name, desc, details):
    with db_conn() as c:
        return c.execute('INSERT INTO payment_methods(name,description,details) VALUES(?,?,?)', (name, desc, details)).lastrowid


def db_pm_update(pid, field, value):
    if field not in ('name', 'description', 'details'):
        raise ValueError('field')
    with db_conn() as c:
        c.execute('UPDATE payment_methods SET %s=? WHERE id=?' % field, (value, pid))


def db_pm_delete(pid):
    with db_conn() as c:
        c.execute('DELETE FROM payment_methods WHERE id=?', (pid,))


# ---- buyurtmalar ----
def db_create_order(uid, p, nick):
    with db_conn() as c:
        cur = c.execute('INSERT INTO orders(user_id,product_id,product_name,price,player,command_snapshot,execution_key) VALUES(?,?,?,?,?,?,?)',
                        (uid, p['id'], p['name'], p['price'], nick, p['command'].replace('{days}', str(p['duration'] or 0)), str(uuid.uuid4())))
        oid = cur.lastrowid
        c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, 'PENDING', 'created'))
        return oid


def db_get_order(oid):
    with db_conn() as c:
        return c.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()


def db_list_orders(uid=None, limit=30, statuses=None):
    q, args, where = 'SELECT * FROM orders', [], []
    if uid is not None:
        where.append('user_id=?')
        args.append(uid)
    if statuses:
        where.append('status IN (%s)' % ','.join('?' * len(statuses)))
        args += list(statuses)
    if where:
        q += ' WHERE ' + ' AND '.join(where)
    q += ' ORDER BY id DESC LIMIT ?'
    args.append(limit)
    with db_conn() as c:
        return c.execute(q, args).fetchall()


def db_latest_open_order(uid):
    with db_conn() as c:
        return c.execute("SELECT * FROM orders WHERE user_id=? AND status IN ('PENDING','PAYMENT_REVIEW') ORDER BY id DESC LIMIT 1", (uid,)).fetchone()


def db_pending_count(uid):
    with db_conn() as c:
        return c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status IN ('PENDING','PAYMENT_REVIEW')", (uid,)).fetchone()[0]


def db_seconds_since_last_order(uid):
    with db_conn() as c:
        r = c.execute("SELECT CAST(strftime('%s','now') AS INTEGER)-CAST(strftime('%s',created) AS INTEGER) s FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        return r['s'] if r else 10 ** 9


def db_recent_duplicate(uid, pid, nick, window=180):
    with db_conn() as c:
        return c.execute("SELECT * FROM orders WHERE user_id=? AND product_id=? AND player=? AND status='PENDING' AND CAST(strftime('%s','now') AS INTEGER)-CAST(strftime('%s',created) AS INTEGER)<? ORDER BY id DESC LIMIT 1",
                         (uid, pid, nick, window)).fetchone()


def db_update_order(oid, status, error=None):
    with db_conn() as c:
        c.execute('UPDATE orders SET status=?,error=?,updated=CURRENT_TIMESTAMP WHERE id=?', (status, error, oid))
        c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, status, (error or '')[:300]))


def db_attach_receipt(oid, uid, file_id, kind='photo'):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='PAYMENT_REVIEW',receipt_file_id=?,receipt_kind=?,updated=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status IN ('PENDING','PAYMENT_REVIEW')",
                        (file_id, kind, oid, uid))
        if cur.rowcount != 1:
            return False
        c.execute("UPDATE payments SET status='REPLACED' WHERE order_id=? AND status='SUBMITTED'", (oid,))
        c.execute('INSERT INTO payments(order_id,user_id,file_id,kind) VALUES(?,?,?,?)', (oid, uid, file_id, kind))
        c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, 'PAYMENT_REVIEW', 'receipt'))
        return True


def db_cancel_by_user(oid, uid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='CANCELLED',updated=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status='PENDING'", (oid, uid))
        return cur.rowcount == 1


def db_approve_once(oid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='APPROVED',error=NULL,updated=CURRENT_TIMESTAMP WHERE id=? AND status IN ('PENDING','PAYMENT_REVIEW')", (oid,))
        if cur.rowcount == 1:
            c.execute("UPDATE payments SET status='APPROVED' WHERE order_id=? AND status='SUBMITTED'", (oid,))
            c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, 'APPROVED', ''))
        return cur.rowcount == 1


def db_retry_failed(oid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='APPROVED',error=NULL,updated=CURRENT_TIMESTAMP WHERE id=? AND status='FAILED'", (oid,))
        if cur.rowcount == 1:
            c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, 'APPROVED', 'retry'))
        return cur.rowcount == 1


def db_reject_order(oid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='REJECTED',updated=CURRENT_TIMESTAMP WHERE id=? AND status IN ('PENDING','PAYMENT_REVIEW','FAILED')", (oid,))
        if cur.rowcount == 1:
            c.execute("UPDATE payments SET status='REJECTED' WHERE order_id=? AND status='SUBMITTED'", (oid,))
            c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, 'REJECTED', ''))
        return cur.rowcount == 1


def db_claim_processing(oid):
    """APPROVED -> PROCESSING atomik. Bitta buyurtma ikki marta bajarilmasligi (idempotency) uchun."""
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='PROCESSING',updated=CURRENT_TIMESTAMP WHERE id=? AND status='APPROVED'", (oid,))
        if cur.rowcount == 1:
            c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, 'PROCESSING', ''))
        return cur.rowcount == 1


def db_approved_ids():
    with db_conn() as c:
        return [r['id'] for r in c.execute("SELECT id FROM orders WHERE status='APPROVED' ORDER BY id")]


def db_recover_orders():
    """Restartdan keyin: APPROVED -> qayta navbat; PROCESSING -> FAILED (qo'lda tekshirish uchun)."""
    with db_conn() as c:
        approved = [r['id'] for r in c.execute("SELECT id FROM orders WHERE status='APPROVED' ORDER BY id")]
        stuck = [r['id'] for r in c.execute("SELECT id FROM orders WHERE status='PROCESSING'")]
        for oid in stuck:
            c.execute("UPDATE orders SET status='FAILED',error='Bot qayta ishga tushdi: buyruq bajarilgan-bajarilmaganini serverda tekshiring',updated=CURRENT_TIMESTAMP WHERE id=?", (oid,))
            c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, 'FAILED', 'restart'))
    return approved, stuck


def db_audit(actor, action, detail=''):
    with db_conn() as c:
        c.execute('INSERT INTO audit_logs(actor,action,details) VALUES(?,?,?)', (actor, action, str(detail)[:500]))


def db_audit_list(n=15):
    with db_conn() as c:
        return c.execute('SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?', (n,)).fetchall()


def db_stats():
    q = {
        'users': 'SELECT COUNT(*) FROM users',
        'today_users': "SELECT COUNT(*) FROM users WHERE date(created,'localtime')=date('now','localtime')",
        'orders': 'SELECT COUNT(*) FROM orders',
        'today_orders': "SELECT COUNT(*) FROM orders WHERE date(created,'localtime')=date('now','localtime')",
        'completed': "SELECT COUNT(*) FROM orders WHERE status='COMPLETED'",
        'pending': "SELECT COUNT(*) FROM orders WHERE status IN ('PENDING','PAYMENT_REVIEW','APPROVED','PROCESSING')",
        'failed': "SELECT COUNT(*) FROM orders WHERE status='FAILED'",
        'rejected': "SELECT COUNT(*) FROM orders WHERE status='REJECTED'",
        'revenue': "SELECT COALESCE(SUM(price),0) FROM orders WHERE status='COMPLETED'",
        'today_revenue': "SELECT COALESCE(SUM(price),0) FROM orders WHERE status='COMPLETED' AND date(updated,'localtime')=date('now','localtime')",
    }
    with db_conn() as c:
        res = {k: c.execute(sql).fetchone()[0] for k, sql in q.items()}
        for cat in ('rank', 'token', 'title'):
            r = c.execute("SELECT o.product_name n,COUNT(*) k FROM orders o JOIN products p ON p.id=o.product_id WHERE o.status='COMPLETED' AND p.category=? GROUP BY o.product_id ORDER BY k DESC LIMIT 1", (cat,)).fetchone()
            res['top_' + cat] = '%s (%d ta)' % (r['n'], r['k']) if r else '—'
    return res


def db_backup(keep=10):
    os.makedirs('backups', exist_ok=True)
    dest = 'backups/Donate-%s.db' % time.strftime('%Y%m%d-%H%M%S')
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)  # WAL bilan ham to'g'ri ishlaydi
    finally:
        dst.close()
        src.close()
    try:
        os.chmod(dest, 0o600)
        files = sorted(f for f in os.listdir('backups') if f.startswith('Donate-') and f.endswith('.db'))
        for f in files[:-keep]:
            os.remove(os.path.join('backups', f))
    except OSError:
        pass
    return dest


# ============================ TUGMALAR (rang + custom emoji ikonka) ============================


class Btn(InlineKeyboardButton):
    """Inline tugma. Bot API 9.4: style (primary/success/danger) va icon_custom_emoji_id qo'llab-quvvatlanadi.
    Agar Telegram qabul qilmasa, xabar avtomatik oddiy ko'rinishda qayta yuboriladi."""

    def __init__(self, text, callback_data=None, url=None, style=None, icon=None):
        super().__init__(text, url=url, callback_data=callback_data)
        self.style = style
        self.icon = icon
        self.fb = ''

    def to_dict(self):
        d = super().to_dict()
        d.pop('style', None)
        d.pop('icon_custom_emoji_id', None)
        if self.style and UI['styles']:
            d['style'] = self.style
        if self.icon and UI['custom']:
            d['icon_custom_emoji_id'] = str(self.icon)
        return d


def B(text, data, style=None):
    return Btn(text, callback_data=data, style=style)


def EB(key, text, data, style=None):
    """Emoji kaliti bilan tugma: custom emoji bo'lsa ikonka, bo'lmasa oddiy emoji matn oldida."""
    cid, pl = emo_id(key), emo_plain(key)
    if cid:
        b = Btn(text, callback_data=data, style=style, icon=cid)
        b.fb = pl
        return b
    return Btn('%s %s' % (pl, text), callback_data=data, style=style)


def KB(*rows):
    k = InlineKeyboardMarkup()
    for r in rows:
        if r:
            k.row(*r)
    return k


def _plain_markup(kb):
    if kb is None:
        return None
    for row in getattr(kb, 'keyboard', []) or []:
        for b in row:
            if isinstance(b, Btn):
                if b.icon and b.fb:
                    b.text = '%s %s' % (b.fb, b.text)
                b.icon = None
                b.style = None
    return kb


_TAG_RE = re.compile(r'<[^>]+>')
_EMOJI_TAG_RE = re.compile(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', re.S)


def strip_tags(t):
    return html.unescape(_TAG_RE.sub('', t))


# ============================ RCON KLIENT (tashqi kutubxonasiz) ============================
NICK_RE = re.compile(r'^[A-Za-z0-9_]{3,16}$')
BAD_REPLIES = ('unknown or incomplete command', 'unknown command', 'no player was found',
               'no user found', 'a user with that name does not exist', 'could not find')
TEST_DENY = ('stop', 'restart', 'op ', 'deop', 'ban-ip', 'save-off', 'reload', 'whitelist off')


class RconError(Exception):
    def __init__(self, msg, sent=False, fatal=False):
        super().__init__(msg)
        self.sent = sent      # buyruq serverga yuborilgan bo'lishi mumkinmi (qayta urinish xavfli)
        self.fatal = fatal    # sozlama xatosi (qayta urinishning foydasi yo'q)


def _exact(s, n):
    buf = b''
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise RconError('Server ulanishni uzdi')
        buf += chunk
    return buf


def _rsend(s, rid, typ, body):
    data = struct.pack('<ii', rid, typ) + body.encode('utf-8') + b'\x00\x00'
    s.sendall(struct.pack('<i', len(data)) + data)


def _rrecv(s):
    (n,) = struct.unpack('<i', _exact(s, 4))
    if n < 10 or n > 8192:
        raise RconError('Noto‘g‘ri RCON paket')
    data = _exact(s, n)
    rid, typ = struct.unpack('<ii', data[:8])
    return rid, typ, data[8:-2].decode('utf-8', 'replace')


def run_command(host, port, password, cmd, timeout=5):
    """cmd=None bo'lsa faqat ulanish + autentifikatsiya tekshiriladi."""
    sent = False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            _rsend(s, 1, 3, password)
            for _ in range(3):
                rid, typ, _b = _rrecv(s)
                if typ == 2:
                    break
            else:
                raise RconError('Auth javobi kelmadi')
            if rid == -1:
                raise RconError('RCON parol noto‘g‘ri', fatal=True)
            if cmd is None:
                return ''
            sent = True
            _rsend(s, 2, 2, cmd)
            _rid, _typ, body = _rrecv(s)
            return body
    except RconError as e:
        if sent and not e.sent:
            e.sent = True
        raise
    except (socket.timeout, TimeoutError):
        raise RconError('RCON timeout' + (' (buyruq bajarilgan bo‘lishi mumkin!)' if sent else ''), sent=sent)
    except OSError as e:
        raise RconError('RCON ulanish xatosi: %s' % e, sent=sent)
    except struct.error:
        raise RconError('RCON javobi noto‘g‘ri', sent=sent)


def now_str():
    return time.strftime('%Y-%m-%d %H:%M:%S')


class RCON:
    def __init__(self):
        self.tlock = threading.Lock()
        self.last = 0.0

    def cfg(self):
        if rget('enabled', 'false').strip().lower() != 'true':
            raise RconError('RCON o‘chirilgan (Admin panel → RCON)', fatal=True)
        pw = rget('password', '') or RCON_PASSWORD
        if not pw or pw == 'CHANGE_ME':
            raise RconError('RCON parol sozlanmagan', fatal=True)
        register_secret(pw)
        try:
            return rget('host', '127.0.0.1'), int(rget('port', '25575') or 25575), pw
        except ValueError:
            raise RconError('RCON port noto‘g‘ri', fatal=True)

    def _run(self, cmd):
        host, port, pw = self.cfg()
        try:
            out = run_command(host, port, pw, cmd)
        except RconError as e:
            rset('last_error', '%s  [%s]' % (str(e)[:200], now_str()))
            rset('last_check', now_str())
            raise
        rset('last_ok', now_str())
        rset('last_check', now_str())
        return out

    def check(self):
        self._run(None)
        return True

    def command(self, cmd):
        return self._run(cmd.lstrip('/'))

    def test(self, cmd):
        low = cmd.strip().lower().lstrip('/')
        if any(low == d.strip() or low.startswith(d) for d in TEST_DENY):
            raise RconError('Bu buyruq testda taqiqlangan', fatal=True)
        return self.command(cmd)

    def throttle(self):
        try:
            gap = float(rget('cooldown', '1.0') or 1)
        except ValueError:
            gap = 1.0
        with self.tlock:
            wait = self.last + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()

    def product(self, template, nick):
        """Faqat buyurtma navbati (worker) chaqiradi. Ulanish xatosida qayta urinadi, lekin buyruq
        yuborilgandan keyingi noaniq xatoda QAYTA URINMAYDI (takroriy berilmasligi uchun)."""
        if not NICK_RE.fullmatch(nick or ''):
            raise RconError('Noto‘g‘ri nickname', fatal=True)
        if not template or len(template) > 500 or '\n' in template or '\r' in template:
            raise RconError('Mahsulot RCON buyrug‘i noto‘g‘ri yoki bo‘sh', fatal=True)
        cmd = template.replace('{player}', nick)
        try:
            tries = max(1, min(int(rget('retries', '3') or 3), 6))
        except ValueError:
            tries = 3
        last = None
        for attempt in range(1, tries + 1):
            self.throttle()
            try:
                reply = self.command(cmd)
            except RconError as e:
                last = e
                if e.sent or e.fatal or attempt == tries:
                    raise
                log.warning('RCON urinish %d/%d muvaffaqiyatsiz: %s', attempt, tries, e)
                time.sleep(2 * attempt)
                continue
            low = (reply or '').lower()
            if any(b in low for b in BAD_REPLIES):
                raise RconError('Server javobi: %s' % reply[:150], sent=True)
            return reply
        raise last or RconError('RCON xatosi')


rcon = RCON()

# ============================ SERVER HOLATI (Server List Ping) ============================


def _varint(n):
    out = b''
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | 0x80 if n else b])
        if not n:
            return out


def _read_varint(buf, pos=0):
    r = 0
    for i in range(5):
        v = buf[pos + i]
        r |= (v & 0x7F) << (7 * i)
        if not v & 0x80:
            return r, pos + i + 1
    raise ValueError('varint')


def _sock_varint(s):
    r = 0
    for i in range(5):
        b = s.recv(1)
        if not b:
            raise ValueError('closed')
        r |= (b[0] & 0x7F) << (7 * i)
        if not b[0] & 0x80:
            return r
    raise ValueError('varint')


def _sexact(s, n):
    buf = b''
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ValueError('closed')
        buf += c
    return buf


def slp_ping(host, port, timeout=3):
    hb = host.encode('utf-8')
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        hs = b'\x00' + _varint(756) + _varint(len(hb)) + hb + struct.pack('>H', port) + _varint(1)
        s.sendall(_varint(len(hs)) + hs + b'\x01\x00')
        t0 = time.monotonic()
        length = _sock_varint(s)
        if length <= 0 or length > 1_000_000:
            raise ValueError('length')
        payload = _sexact(s, length)
        latency = round((time.monotonic() - t0) * 1000)
    _pid, pos = _read_varint(payload)
    slen, pos = _read_varint(payload, pos)
    return json.loads(payload[pos:pos + slen].decode('utf-8', 'replace')), latency


_ST = {'t': 0.0, 'key': None, 'v': None}


def get_status(force=False):
    """ONLINE / OFFLINE / UNKNOWN. Aniqlab bo'lmasa UNKNOWN (noto'g'ri ONLINE ko'rsatilmaydi)."""
    host, port_s = sget('server_host', SERVER_HOST), sget('server_port', str(SERVER_PORT))
    key = (host, port_s)
    now = time.monotonic()
    if not force and _ST['v'] and _ST['key'] == key and now - _ST['t'] < 8:
        return _ST['v']
    base = {'ping': None, 'online': None, 'max': None, 'version': sget('server_version', 'Unknown')}
    try:
        data, latency = slp_ping(host, int(port_s))
        pl = data.get('players') or {}
        res = dict(base, state='ONLINE', ping=latency, online=pl.get('online'), max=pl.get('max'))
        ver = (data.get('version') or {}).get('name')
        if ver:
            res['version'] = ver
    except (ConnectionRefusedError, socket.timeout, TimeoutError, ConnectionResetError):
        res = dict(base, state='OFFLINE')
    except (socket.gaierror, OSError, ValueError, KeyError, IndexError, TypeError, struct.error):
        res = dict(base, state='UNKNOWN')
    _ST.update(t=now, key=key, v=res)
    return res


# ============================ BOT YADROSI ============================
if not BOT_TOKEN or BOT_TOKEN.startswith('YOUR_'):
    raise SystemExit('main.py tepasidagi BOT_TOKEN ni to‘ldiring')
if not SUPER:
    log.warning('SUPER_ADMIN_ID sozlanmagan: Super Admin funksiyalari ishlamaydi')

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML', threaded=True, num_threads=8)

SUPER_ONLY = ('rcon', 'admins', 'security')
buying = {}      # uid -> product_id (nickname kutilmoqda)
drafts = {}      # uid -> {'pid','nick','price'} (tasdiqlash kutilmoqda)
receipts = {}    # uid -> order_id (chek kutilmoqda)
admin_flow = {}  # uid -> {'k': amal, ...}


class RateLimiter:
    def __init__(self, interval=1.0):
        self.interval = interval
        self.last = {}

    def allow(self, key):
        now = time.monotonic()
        if now - self.last.get(key, 0) < self.interval:
            return False
        self.last[key] = now
        if len(self.last) > 5000:
            cutoff = now - 60
            self.last = {k: v for k, v in self.last.items() if v > cutoff}
        return True


limiter = RateLimiter(0.6)     # callback spam himoyasi
mlimiter = RateLimiter(0.35)   # xabar spam himoyasi


def esc(x):
    return html.escape('' if x is None else str(x))


def money(n):
    return '{:,}'.format(int(n or 0)).replace(',', ' ')


def head(title, icon=''):
    return '%s\n%s<b>%s</b>\n%s' % (LINE, (icon + ' ') if icon else '', title, LINE)


def is_super(uid):
    return SUPER != 0 and uid == SUPER


def is_admin(uid):
    return is_super(uid) or db_is_admin(uid)


def has_perm(uid, perm):
    if is_super(uid):
        return True
    if perm in SUPER_ONLY:
        return False
    return perm in db_admin_perms(uid)


def admin_ids(perm=None):
    ids = {SUPER} if SUPER else set()
    if perm:
        ids |= set(db_admins_with(perm))
    else:
        ids |= {a['id'] for a in db_admins()}
    return ids


def txt(key, **kw):
    t = setting(key, TEXT_DEFAULTS.get(key, ''))
    for k, v in kw.items():
        t = t.replace('{' + k + '}', str(v))
    return t


# ---------- Telegram'ga xavfsiz yuborish (custom emoji / tugma rangi / HTML xatolarida fallback) ----------
def _variants(text, kb):
    text = text[:4000]
    yield text, kb, 'HTML'
    yield _EMOJI_TAG_RE.sub(r'\1', text), _plain_markup(kb), 'HTML'
    yield strip_tags(text), kb, ''


def _retry_after(e):
    try:
        return int((getattr(e, 'result_json', None) or {}).get('parameters', {}).get('retry_after', 1))
    except Exception:
        return 1


def _api(call, text, kb=None):
    last = None
    for t, k, pm in _variants(text, kb):
        for _ in range(2):
            try:
                return call(t, k, pm) or True
            except ApiTelegramException as e:
                last = e
                code, d = getattr(e, 'error_code', 0), str(e).lower()
                if code == 429:
                    time.sleep(min(_retry_after(e), 5))
                    continue
                if 'not modified' in d:
                    return True
                if code == 403 or 'blocked' in d or 'deactivated' in d or 'chat not found' in d:
                    return None
                if 'no text in the message' in d or "can't be edited" in d or 'message to edit not found' in d:
                    return None
                break
            except Exception:
                log.exception('Telegram chaqiruvi xatosi')
                return None
    log.warning('Telegram API xatosi: %s', last)
    return None


def send(chat, text, kb=None):
    return _api(lambda t, k, pm: bot.send_message(chat, t, reply_markup=k, parse_mode=pm), text, kb)


def send_media(chat, kind, file_id, caption, kb=None):
    fn = bot.send_document if kind == 'document' else bot.send_photo
    return _api(lambda t, k, pm: fn(chat, file_id, caption=t[:1000], reply_markup=k, parse_mode=pm), caption, kb)


def show(c, text, kb=None):
    """Mavjud xabarni tahrirlaydi (chat to'lib ketmasligi uchun), bo'lmasa yangi xabar yuboradi."""
    chat, mid = c.message.chat.id, c.message.message_id
    r = _api(lambda t, k, pm: bot.edit_message_text(t, chat, mid, reply_markup=k, parse_mode=pm), text, kb)
    if r is None:
        send(chat, text, kb)


def notify_admins(text, kb=None, perm='orders_manage'):
    for a in admin_ids(perm):
        send(a, text, kb)


def clear_flows(uid):
    admin_flow.pop(uid, None)
    buying.pop(uid, None)
    drafts.pop(uid, None)
    receipts.pop(uid, None)


def safe_db(fn, *a):
    """Vaqtinchalik baza xatosida bir necha marta qayta urinadi."""
    for i in range(5):
        try:
            return fn(*a)
        except sqlite3.Error:
            log.exception('Baza xatosi (urinish %d)', i + 1)
            time.sleep(1 + i)
    return fn(*a)


# ============================ BUYURTMA NAVBATI (worker) ============================
_q = queue.Queue()
_queued = set()
_qlock = threading.Lock()


def enqueue(oid):
    with _qlock:
        if oid in _queued:
            return
        _queued.add(oid)
    _q.put(oid)


def process_order(oid):
    o = db_get_order(oid)
    if not o or not db_claim_processing(oid):
        return  # allaqachon bajarilgan/boshqa worker olgan: takroriy bajarilmaydi
    try:
        rcon.product(o['command_snapshot'], o['player'])
    except Exception as e:
        err = (str(e) or type(e).__name__)[:300]
        log.warning('Order #%s bajarilmadi: %s', oid, err)
        safe_db(db_update_order, oid, 'FAILED', err)
        send(o['user_id'], '🟠 Buyurtma <b>#%s</b> vaqtincha bajarilmadi. Admin qayta ko‘rib chiqadi, buyurtmangiz yo‘qolmaydi.' % oid)
        kb = KB([B('🔁 Qayta urinish', 'retry:%s' % oid, 'primary'), B('🔴 Rad etish', 'reject:%s' % oid, 'danger')])
        notify_admins('⚠️ <b>Order #%s bajarilmadi</b>\n🎮 %s • %s\nSabab: <code>%s</code>\n\n'
                      '❗ Timeout bo‘lsa, qayta urinishdan oldin serverda buyruq bajarilmaganini tekshiring.'
                      % (oid, esc(o['player']), esc(o['product_name']), esc(err)), kb)
        return
    safe_db(db_update_order, oid, 'COMPLETED')
    send(o['user_id'], txt('order_completed_text', order_id=oid, product=esc(o['product_name']), player=esc(o['player'])))


def worker_loop():
    while True:
        oid = _q.get()
        try:
            process_order(oid)
        except Exception:
            log.exception('worker xatosi order #%s', oid)
        finally:
            with _qlock:
                _queued.discard(oid)
            _q.task_done()


def scheduler_loop():
    """Har 30 soniyada tiqilib qolgan APPROVED buyurtmalarni qayta navbatga qo'yadi; har 24 soatda backup."""
    last_backup = time.time()
    while True:
        time.sleep(30)
        try:
            for oid in db_approved_ids():
                enqueue(oid)
            if time.time() - last_backup > 86400:
                last_backup = time.time()
                db_backup()
                log.info('Avtomatik backup yaratildi')
        except Exception:
            log.exception('scheduler xatosi')


def start_workers():
    approved, stuck = db_recover_orders()
    for oid in approved:
        enqueue(oid)
    if stuck:
        notify_admins('⚠️ Bot qayta ishga tushdi. Bajarilish paytida uzilgan buyurtmalar: %s\n'
                      'Serverda tekshirib, Buyurtmalar bo‘limidan qayta urinib ko‘ring.' % ', '.join('#%s' % i for i in stuck))
    threading.Thread(target=worker_loop, daemon=True, name='order-worker').start()
    threading.Thread(target=scheduler_loop, daemon=True, name='scheduler').start()


# ============================ FOYDALANUVCHI EKRANLARI ============================
def home_kb(uid):
    rows = [[EB('cat_rank', 'Ranklar', 'shop:rank'), EB('cat_token', 'Tokenlar', 'shop:token')],
            [EB('cat_title', 'Titullar', 'shop:title'), B('🛒 Mening buyurtmalarim', 'orders')],
            [B('👤 Profilim', 'profile'), B('🌐 Server haqida', 'server')],
            [B('📞 Admin bilan bog‘lanish', 'support')]]
    if is_admin(uid):
        rows.append([EB('adm_panel', 'Admin panel', 'admin', 'primary')])
    return KB(*rows)


def back_kb(to='home', label='⬅️ Menyu'):
    return KB([B(label, to)])


def product_btn(p):
    text = '%s • %s UZS' % (p['name'], money(p['price']))
    if p['emoji_id'] and UI['custom']:
        b = Btn(text, callback_data='p:%s' % p['id'], icon=p['emoji_id'])
        b.fb = p['emoji']
        return b
    return Btn('%s %s' % (p['emoji'], text), callback_data='p:%s' % p['id'])


def product_emoji_html(p):
    if p['emoji_id'] and UI['custom']:
        return '<tg-emoji emoji-id="%s">%s</tg-emoji>' % (p['emoji_id'], esc(p['emoji']))
    return esc(p['emoji'])


def card_text(p):
    dur = '%s kun' % p['duration'] if p['duration'] else 'Muddatsiz'
    return '%s\n%s <b>%s</b>\n%s\n💰 Narxi: <b>%s UZS</b>\n⏳ Muddati: <b>%s</b>\n\n%s' % (
        LINE, product_emoji_html(p), esc(p['name']), LINE, money(p['price']), dur, p['description'] or '')


def maintenance_blocked(uid):
    return setting('maintenance', 'false') == 'true' and not is_admin(uid)


def guard_buy(uid, chat):
    if maintenance_blocked(uid):
        send(chat, '🛠 Hozir texnik ishlar olib borilmoqda. Birozdan so‘ng urinib ko‘ring.')
        return True
    try:
        mx = int(setting('max_pending', '3') or 3)
    except ValueError:
        mx = 3
    if not is_admin(uid) and db_pending_count(uid) >= mx:
        send(chat, '⚠️ Sizda to‘lanmagan %d ta buyurtma bor. “Mening buyurtmalarim” bo‘limida chek yuboring yoki bekor qiling.' % mx,
             KB([B('🛒 Mening buyurtmalarim', 'orders')]))
        return True
    return False


def draft_text(p, nick, note=''):
    dur = '%s kun' % p['duration'] if p['duration'] else 'Muddatsiz'
    return ('%s\n📋 <b>BUYURTMA MA’LUMOTLARI</b>\n%s\n%s <b>%s</b>\n💰 Narxi: <b>%s UZS</b>\n⏳ Muddati: %s\n🎮 Nickname: <b>%s</b>\n\n%s'
            '⚠️ Nickname to‘g‘riligini tekshiring — mahsulot shu nickname ga beriladi.\n\n<b>Buyurtmani tasdiqlaysizmi?</b>'
            % (LINE, LINE, product_emoji_html(p), esc(p['name']), money(p['price']), dur, esc(nick), note))


def payment_screen(o):
    parts = ['%s\n🧾 <b>BUYURTMA #%s</b>\n%s\n%s <b>%s</b>\n💰 <b>%s UZS</b>\n🎮 %s\n' % (
        LINE, o['id'], LINE, '🛍', esc(o['product_name']), money(o['price']), esc(o['player'])),
        txt('payment_text')]
    for m in db_pm_list():
        s = '\n━━━━━━━━\n<b>%s</b>' % esc(m['name'])
        if m['description']:
            s += '\n%s' % esc(m['description'])
        if m['details']:
            s += '\n<code>%s</code>' % esc(m['details'])
        parts.append(s)
    parts.append('\n━━━━━━━━\n📸 To‘lovdan so‘ng <b>chek (screenshot)</b> ni yuboring.')
    return '\n'.join(parts)


def payment_kb(oid):
    return KB([B('🧾 Chek yuborish', 'rc:%s' % oid, 'primary')],
              [B('❌ Buyurtmani bekor qilish', 'uc:%s' % oid, 'danger')],
              [B('⬅️ Menyu', 'home')])


def link_rows():
    row = []
    for key, label in (('telegram_link', '✈️ Telegram'), ('discord_link', '💬 Discord'), ('website', '🌐 Website')):
        v = sget(key, '').strip()
        if v.startswith(('http://', 'https://')):
            row.append(Btn(label, url=v))
    sup = sget('support', '').strip()
    if sup.startswith('@') and len(sup) > 1:
        row.append(Btn('📞 Admin', url='https://t.me/' + sup[1:]))
    elif sup.startswith(('http://', 'https://')):
        row.append(Btn('📞 Admin', url=sup))
    return [row[i:i + 2] for i in range(0, len(row), 2)]


def server_text():
    s = get_status()
    icon = emo({'ONLINE': 'srv_online', 'OFFLINE': 'srv_offline'}.get(s['state'], 'srv_unknown'))
    online = '%s/%s' % (s['online'], s['max'] if s['max'] is not None else '—') if s['state'] == 'ONLINE' and s['online'] is not None else '—'
    return ('%s\n🌐 <b>%s</b>\n%s\n%s\n\n'
            '📍 IP: <code>%s</code>\n🔌 Port: <code>%s</code>\n📡 Status: %s <b>%s</b>\n👥 O‘yinchilar: <b>%s</b>\n'
            '🧩 Versiya: %s\n⚡ Ping: %s\n\n%s') % (
        LINE, esc(sget('server_name', 'DARKZONA')), LINE, esc(sget('server_description', '')),
        esc(sget('server_host')), esc(sget('server_port')), icon, s['state'], online, esc(s['version']),
        ('%s ms' % s['ping']) if s['ping'] is not None else '—', txt('server_about_text'))


def user_orders_screen(uid):
    rows = db_list_orders(uid, 12)
    if rows:
        lines = ['%s #%s %s — %s UZS\n      %s %s' % ('•', r['id'], esc(r['product_name']), money(r['price']),
                                                       emo('st_' + r['status']), STATUS_UZ.get(r['status'], r['status'])) for r in rows]
        text = head('MENING BUYURTMALARIM', '🛒') + '\n' + '\n'.join(lines)
    else:
        text = head('MENING BUYURTMALARIM', '🛒') + '\nHali buyurtma yo‘q.'
    krows = []
    for r in rows:
        if r['status'] == 'PENDING':
            krows.append([B('🧾 Chek #%s' % r['id'], 'rc:%s' % r['id'], 'primary'), B('❌ Bekor #%s' % r['id'], 'uc:%s' % r['id'], 'danger')])
    krows.append([B('⬅️ Menyu', 'home')])
    return text, KB(*krows)


def user_callback(c, uid, d, chat):
    """Oddiy foydalanuvchi tugmalari. Qayta ishlangan bo'lsa True."""
    if d == 'home':
        clear_flows(uid)
        show(c, txt('welcome_text'), home_kb(uid))
        return True

    if d.startswith('shop:'):
        cat = db_category(d.split(':')[1])
        if not cat:
            return True
        ps = db_products(cat['code'])
        rows = [[product_btn(p)] for p in ps]
        rows.append([B('⬅️ Bosh menyu', 'home')])
        body = '%s\n%s' % (cat['description'] or '', '' if ps else '\nHozircha mahsulot yo‘q.')
        show(c, '%s\n%s\n\n👇 Mahsulotni tanlang:' % (head(esc(cat['name']).upper(), emo('cat_' + cat['code'])), body), KB(*rows))
        return True

    if d.startswith('p:'):
        p = db_product(int(d[2:]))
        if not p:
            show(c, 'Mahsulot topilmadi.', back_kb())
            return True
        show(c, card_text(p), KB([B('🛒 Sotib olish', 'buy:%s' % p['id'], 'success')], [B('⬅️ Orqaga', 'shop:%s' % p['category'])]))
        return True

    if d.startswith('buy:'):
        if guard_buy(uid, chat):
            return True
        p = db_product(int(d[4:]))
        if not p:
            send(chat, 'Mahsulot topilmadi.')
            return True
        clear_flows(uid)
        buying[uid] = p['id']
        send(chat, '🎮 <b>%s</b> uchun <b>Minecraft nickname</b> yuboring.\n(3–16 belgi: lotin harf, raqam yoki _)\n\nBekor qilish: /cancel' % esc(p['name']))
        return True

    if d == 'cancel_draft':
        buying.pop(uid, None)
        drafts.pop(uid, None)
        show(c, txt('welcome_text'), home_kb(uid))
        return True

    if d == 'cf':
        confirm_order(c, uid, chat)
        return True

    if d == 'orders':
        text, kb = user_orders_screen(uid)
        show(c, text, kb)
        return True

    if d.startswith('rc:'):
        o = db_get_order(int(d[3:]))
        if not o or o['user_id'] != uid or o['status'] not in ('PENDING', 'PAYMENT_REVIEW'):
            send(chat, 'Bu buyurtmaga chek yuborib bo‘lmaydi.')
            return True
        receipts[uid] = o['id']
        send(chat, '🧾 Buyurtma <b>#%s</b> uchun to‘lov chekini (rasm yoki PDF) yuboring.' % o['id'])
        return True

    if d.startswith('uc:'):
        oid = int(d[3:])
        if db_cancel_by_user(oid, uid):
            if receipts.get(uid) == oid:
                receipts.pop(uid, None)
            show(c, '⚪ Buyurtma #%s bekor qilindi.' % oid, back_kb('orders', '⬅️ Buyurtmalar'))
        else:
            send(chat, 'Bu buyurtmani bekor qilib bo‘lmaydi (allaqachon tekshiruvda yoki yakunlangan).')
        return True

    if d == 'profile':
        info = db_user_info(uid)
        u = c.from_user
        text = '%s\n👤 <b>PROFIL</b>\n%s\n🆔 ID: <code>%s</code>\n📛 Ism: %s\n🔗 Username: %s\n📦 Buyurtmalar: %s (bajarilgan: %s)\n💰 Jami xarid: %s UZS' % (
            LINE, LINE, uid, esc(u.first_name), ('@' + esc(u.username)) if u.username else '—', info['orders'], info['done'], money(info['spent']))
        show(c, text, back_kb())
        return True

    if d == 'server':
        show(c, server_text(), KB(*(link_rows() + [[B('🔄 Yangilash', 'server_refresh'), B('⬅️ Menyu', 'home')]])))
        return True

    if d == 'server_refresh':
        get_status(force=True)
        show(c, server_text(), KB(*(link_rows() + [[B('🔄 Yangilash', 'server_refresh'), B('⬅️ Menyu', 'home')]])))
        return True

    if d == 'support':
        show(c, '%s\n📞 <b>ALOQA</b>\n%s\n%s' % (LINE, LINE, esc(sget('support', 'Support sozlanmagan'))),
             KB(*(link_rows() + [[B('⬅️ Menyu', 'home')]])))
        return True
    return False


def confirm_order(c, uid, chat):
    dr = drafts.get(uid)
    if not dr:
        show(c, '⌛ Buyurtma muddati tugadi. Qaytadan boshlang.', home_kb(uid))
        return
    p = db_product(dr['pid'])
    if not p:
        drafts.pop(uid, None)
        show(c, 'Mahsulot endi mavjud emas.', home_kb(uid))
        return
    if p['price'] != dr['price']:  # narx tekshiruvi: admin narxni o'zgartirgan bo'lishi mumkin
        dr['price'] = p['price']
        show(c, draft_text(p, dr['nick'], '🔔 <b>Narx yangilandi!</b>\n\n'),
             KB([B('✅ Tasdiqlash', 'cf', 'success')], [B('❌ Bekor', 'cancel_draft', 'danger')]))
        return
    dup = db_recent_duplicate(uid, p['id'], dr['nick'])
    if dup:
        oid = dup['id']  # tugma ikki marta bosilsa, ikkinchi buyurtma yaratilmaydi
    else:
        if guard_buy(uid, chat):
            return
        try:
            cd = int(setting('order_cooldown', '30') or 30)
        except ValueError:
            cd = 30
        wait = cd - db_seconds_since_last_order(uid)
        if wait > 0 and not is_admin(uid):
            send(chat, '⏳ Yangi buyurtma uchun %d soniya kuting.' % wait)
            return
        oid = db_create_order(uid, p, dr['nick'])
    drafts.pop(uid, None)
    buying.pop(uid, None)
    receipts[uid] = oid
    show(c, payment_screen(db_get_order(oid)), payment_kb(oid))


def accept_receipt(m, file_id, kind):
    uid = m.from_user.id
    o = None
    oid = receipts.get(uid)
    if oid:
        o = db_get_order(oid)
        if not o or o['user_id'] != uid or o['status'] not in ('PENDING', 'PAYMENT_REVIEW'):
            o = None
    if not o:
        o = db_latest_open_order(uid)  # bot qayta ishga tushgan bo'lsa ham ishlaydi
    if not o:
        return send(m.chat.id, 'Avval mahsulot tanlab buyurtma bering: /start')
    if not db_attach_receipt(o['id'], uid, file_id, kind):
        return send(m.chat.id, 'Bu buyurtmaga chek qabul qilib bo‘lmaydi.')
    receipts.pop(uid, None)
    oid = o['id']
    caption = '🧾 <b>Chek • order #%s</b>\n%s — %s UZS\n🎮 %s\n👤 %s (<code>%s</code>)' % (
        oid, esc(o['product_name']), money(o['price']), esc(o['player']), esc(m.from_user.first_name), uid)
    kb = KB([B('🟢 Tasdiqlash', 'approve:%s' % oid, 'success'), B('🔴 Rad etish', 'reject:%s' % oid, 'danger')])
    for aid in admin_ids('orders_manage'):
        send_media(aid, kind, file_id, caption, kb)
    send(m.chat.id, txt('order_accepted_text', order_id=oid), back_kb())


# ============================ ADMIN PANEL ============================
SERVER_FIELDS = [('server_name', 'Server nomi'), ('server_host', 'Server IP / domen'), ('server_port', 'Server port'),
                 ('server_version', 'Minecraft versiyasi'), ('server_description', 'Server tavsifi'),
                 ('telegram_link', 'Telegram link (https://t.me/...)'), ('discord_link', 'Discord link'),
                 ('website', 'Website'), ('support', 'Qo‘llab-quvvatlash kontakti (@username yoki link)')]
RCON_FIELDS = [('host', 'RCON host'), ('port', 'RCON port'), ('password', 'RCON parol'),
               ('cooldown', 'Buyruqlar orasidagi pauza (soniya)'), ('retries', 'Ulanish qayta urinishlari soni')]
TEXT_FIELDS = [('start_text', 'Start xabari (/start)'), ('welcome_text', 'Welcome xabari (bosh menyu)'),
               ('desc:rank', 'Rank bo‘limi tavsifi'), ('desc:token', 'Token bo‘limi tavsifi'), ('desc:title', 'Titul bo‘limi tavsifi'),
               ('payment_text', 'To‘lov ko‘rsatmasi'), ('order_accepted_text', 'Buyurtma qabul qilindi xabari'),
               ('order_completed_text', 'Buyurtma bajarildi xabari'), ('order_rejected_text', 'Buyurtma rad etildi xabari'),
               ('server_about_text', 'Server haqida matn')]
PRODUCT_FIELDS = [('name', '📝 Nomi'), ('price', '💰 Narxi'), ('duration', '⏳ Muddati (kun)'), ('description', '📄 Tavsif'),
                  ('emoji', '✨ Emoji'), ('emoji_id', '💎 Premium emoji ID'), ('command', '⚙️ RCON command')]
SEC_FIELDS = [('order_cooldown', 'settings', 'Yangi buyurtmalar orasidagi pauza (soniya)'),
              ('max_pending', 'settings', 'Bir foydalanuvchining max to‘lanmagan buyurtmasi'),
              ('cooldown', 'rcon_settings', 'RCON buyruqlari orasidagi pauza (soniya)'),
              ('retries', 'rcon_settings', 'RCON ulanish qayta urinishlari')]
ORDER_FILTERS = {'open': ('Ochiq', OPEN_STATUSES), 'done': ('Bajarilgan', ('COMPLETED',)),
                 'rej': ('Rad/Bekor', ('REJECTED', 'CANCELLED')), 'all': ('Hammasi', None)}
bcast_draft = {}
_bcast_busy = threading.Lock()


def short(v, n=28):
    v = str(v)
    return v if len(v) <= n else v[:n - 1] + '…'


def admin_kb(uid):
    items = [('products', EB('adm_products', 'Mahsulotlar', 'a:products')), ('products', B('💰 Narxlar', 'a:prices')),
             ('products', B('🪙 Token paketlari', 'a:cat:token')), ('products', B('⚔️ Titullar', 'a:cat:title')),
             ('rcon', B('⚙️ RCON sozlamalari', 'a:rcon')), ('server', B('🖥 Server sozlamalari', 'a:server')),
             ('texts', B('📝 Bot matnlari', 'a:texts')), ('emoji', B('🎨 Emoji va dizayn', 'a:emoji')),
             ('payments', B('💳 To‘lov usullari', 'a:pay')), ('orders_view', EB('adm_orders', 'Buyurtmalar', 'a:orders:open')),
             ('users', B('👥 Foydalanuvchilar', 'a:users:0')), ('stats', B('📊 Statistika', 'a:stats')),
             ('admins', B('👮 Adminlar', 'a:admins')), ('security', B('🔒 Xavfsizlik', 'a:security')),
             ('broadcast', B('📢 Xabar yuborish', 'a:bcast'))]
    btns = [b for perm, b in items if has_perm(uid, perm)]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([B('⬅️ Menyu', 'home')])
    return KB(*rows)


def admin_title():
    return head('DARKZONA ADMIN PANEL', emo('adm_panel'))


def deny(chat):
    send(chat, '⛔ Bu bo‘limga ruxsatingiz yo‘q.')
    return True


def finish_buttons(c):
    try:
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception:
        pass


def order_card(o):
    kb_rows = []
    if o['status'] in ('PENDING', 'PAYMENT_REVIEW'):
        kb_rows.append([B('🟢 Tasdiqlash', 'approve:%s' % o['id'], 'success'), B('🔴 Rad etish', 'reject:%s' % o['id'], 'danger')])
    elif o['status'] == 'FAILED':
        kb_rows.append([B('🔁 Qayta urinish', 'retry:%s' % o['id'], 'primary'), B('🔴 Rad etish', 'reject:%s' % o['id'], 'danger')])
    if o['receipt_file_id']:
        kb_rows.append([B('🧾 Chekni ko‘rish', 'rcpt:%s' % o['id'])])
    text = '#%s <b>%s</b> — %s UZS\n🎮 %s • 👤 <code>%s</code>\n%s %s\n🕒 %s' % (
        o['id'], esc(o['product_name']), money(o['price']), esc(o['player']), o['user_id'],
        emo('st_' + o['status']), STATUS_UZ.get(o['status'], o['status']), esc(o['created']))
    if o['error']:
        text += '\n⚠️ <code>%s</code>' % esc(o['error'])
    return text, KB(*kb_rows)


def cat_screen(code):
    cat = db_category(code)
    rows = [[B('%s %s • %s' % (p['emoji'], short(p['name'], 18), money(p['price'])), 'edit:%s' % p['id'])] for p in db_products(code)]
    rows.append([B('➕ Yangi qo‘shish', 'addp:%s' % code, 'success')])
    rows.append([B('⬅️ Orqaga', 'a:products')])
    return head(esc(cat['name']).upper() + ' — BOSHQARUV', '📦') + '\nTahrirlash uchun mahsulotni tanlang:', KB(*rows)


def product_edit_screen(p):
    text = ('%s\n%s <b>%s</b>\n%s\n💰 Narx: <b>%s UZS</b>\n⏳ Muddat: %s kun\n💎 Premium emoji ID: <code>%s</code>\n⚙️ Command:\n<code>%s</code>\n\n📄 %s\n\n'
            '<i>Command ichida: {player} — nickname, {days} — muddat (kun)</i>') % (
        LINE, esc(p['emoji']), esc(p['name']), LINE, money(p['price']), p['duration'], esc(p['emoji_id'] or '—'), esc(p['command']), esc(p['description']))
    rows = [[B(PRODUCT_FIELDS[i][1], 'field:%s:%s' % (p['id'], PRODUCT_FIELDS[i][0])), B(PRODUCT_FIELDS[i + 1][1], 'field:%s:%s' % (p['id'], PRODUCT_FIELDS[i + 1][0]))]
            for i in range(0, 6, 2)]
    rows.append([B(PRODUCT_FIELDS[6][1], 'field:%s:command' % p['id'])])
    rows.append([B('🗑 O‘chirish', 'del:%s' % p['id'], 'danger'), B('⬅️ Orqaga', 'a:cat:%s' % p['category'])])
    return text, KB(*rows)


def stats_text():
    s = db_stats()
    return (head('STATISTIKA', '📊') +
            '\n👥 Foydalanuvchilar: <b>%(users)s</b> (bugun: %(today_users)s)\n📦 Jami buyurtmalar: <b>%(orders)s</b> (bugun: %(today_orders)s)\n'
            '🟢 Bajarilgan: %(completed)s\n🟡 Kutilayotgan: %(pending)s\n🟠 Xatolik: %(failed)s\n🔴 Rad etilgan: %(rejected)s\n' % s +
            '💰 Jami tushum: <b>%s UZS</b>\n📅 Bugungi tushum: <b>%s UZS</b>\n\n🏆 Eng ko‘p sotilgan:\n💎 Rank: %s\n🪙 Token: %s\n⚔️ Titul: %s' % (
                money(s['revenue']), money(s['today_revenue']), esc(s['top_rank']), esc(s['top_token']), esc(s['top_title'])))


def rcon_screen():
    en = rget('enabled', 'false') == 'true'
    pw = rget('password', '') or (RCON_PASSWORD if RCON_PASSWORD != 'CHANGE_ME' else '')
    status = '🟢 Oxirgi ulanish muvaffaqiyatli' if rget('last_ok') and (not rget('last_error') or rget('last_ok') >= rget('last_error')[-19:]) else ('🔴 Xatolik bor' if rget('last_error') else '⚪ Hali tekshirilmagan')
    text = ('%s\n⚙️ Holat: %s\n🌐 Host: <code>%s</code>\n🔌 Port: <code>%s</code>\n🔑 Parol: %s\n⏱ Pauza: %s s • 🔁 Urinishlar: %s\n\n'
            '📡 Status: %s\n🕒 Oxirgi muvaffaqiyatli: %s\n🕒 Oxirgi tekshiruv: %s\n❗ Oxirgi xatolik: <code>%s</code>') % (
        head('RCON SOZLAMALARI', '⚙️'), '🟢 YOQILGAN' if en else '🔴 O‘CHIRILGAN', esc(rget('host')), esc(rget('port')),
        '••••••••' if pw else '(sozlanmagan)', esc(rget('cooldown')), esc(rget('retries')), status,
        esc(rget('last_ok') or '—'), esc(rget('last_check') or '—'), esc(rget('last_error') or '—'))
    rows = [[B('🔴 O‘chirish' if en else '🟢 Yoqish', 'rx:toggle', 'danger' if en else 'success')]]
    for i, (k, label) in enumerate(RCON_FIELDS):
        shown = '••••••••' if k == 'password' else short(rget(k))
        rows.append([B('%s: %s' % (short(label, 22), shown), 'rxs:%d' % i)])
    rows.append([B('🔌 Ulanishni tekshirish', 'rx:check', 'primary'), B('🧪 Command test', 'rx:test')])
    rows.append([B('⬅️ Panel', 'admin')])
    return text, KB(*rows)


def server_settings_screen():
    rows = [[B('%s: %s' % (short(label.split(' (')[0], 22), short(sget(k) or '—', 22)), 'ss:%d' % i)] for i, (k, label) in enumerate(SERVER_FIELDS)]
    rows.append([B('⬅️ Panel', 'admin')])
    return head('SERVER SOZLAMALARI', '🖥') + '\nO‘zgartirmoqchi bo‘lgan maydonni tanlang:', KB(*rows)


def texts_screen():
    rows = [[B(label, 'tx:%d' % i)] for i, (k, label) in enumerate(TEXT_FIELDS)]
    rows.append([B('⬅️ Panel', 'admin')])
    return head('BOT MATNLARI', '📝') + '\nTahrirlamoqchi bo‘lgan matnni tanlang:', KB(*rows)


def text_value(key):
    if key.startswith('desc:'):
        cat = db_category(key[5:])
        return cat['description'] if cat else ''
    return setting(key, TEXT_DEFAULTS.get(key, ''))


def emoji_main_screen():
    rows = [[B(name, 'em:%s' % sec)] for sec, name in EMOJI_SECTIONS.items()]
    rows.append([B('%s Custom (premium) emoji: %s' % ('🟢', 'YOQILGAN' if UI['custom'] else 'O‘CHIRILGAN'), 'ui:custom')])
    rows.append([B('%s Rangli tugmalar: %s' % ('🎨', 'YOQILGAN' if UI['styles'] else 'O‘CHIRILGAN'), 'ui:styles')])
    rows.append([B('⬅️ Panel', 'admin')])
    return head('EMOJI VA DIZAYN', '🎨') + '\nBo‘limni tanlang. Premium (custom) emoji ID ni qo‘shish mumkin; ishlamasa bot oddiy emojiga qaytadi.', KB(*rows)


def users_screen(page):
    per = 8
    total = db_users_count()
    rows = []
    for u in db_users_page(page * per, per):
        name = ('@' + u['username']) if u['username'] else (u['first_name'] or str(u['id']))
        rows.append([B('%s%s • %s' % ('⛔ ' if u['banned'] else '', short(name, 22), u['id']), 'u:%s' % u['id'])])
    nav = []
    if page > 0:
        nav.append(B('◀️', 'a:users:%d' % (page - 1)))
    if (page + 1) * per < total:
        nav.append(B('▶️', 'a:users:%d' % (page + 1)))
    if nav:
        rows.append(nav)
    rows.append([B('🔎 Qidirish (ID / @username)', 'usr:search')])
    rows.append([B('⬅️ Panel', 'admin')])
    return head('FOYDALANUVCHILAR', '👥') + '\nJami: <b>%d</b> • Sahifa: %d' % (total, page + 1), KB(*rows)


def user_screen(uid, can_ban):
    info = db_user_info(uid)
    if not info:
        return 'Foydalanuvchi topilmadi.', back_kb('a:users:0', '⬅️ Ro‘yxat')
    u = info['user']
    text = ('%s\n🆔 <code>%s</code>\n📛 %s\n🔗 %s\n🕒 Qo‘shilgan: %s\n👀 Oxirgi faollik: %s\n📦 Buyurtmalar: %s (bajarilgan: %s)\n💰 Jami xarid: %s UZS\n🚫 Holat: %s') % (
        head('FOYDALANUVCHI', '👤'), u['id'], esc(u['first_name']), ('@' + esc(u['username'])) if u['username'] else '—',
        esc(u['created']), esc(u['last_seen'] or '—'), info['orders'], info['done'], money(info['spent']), 'BLOKLANGAN' if u['banned'] else 'faol')
    rows = [[B('📦 Buyurtmalari', 'uo:%s' % uid)]]
    if can_ban and not is_admin(u['id']):
        rows.append([B('✅ Blokdan chiqarish', 'uu:%s' % uid, 'success') if u['banned'] else B('⛔ Bloklash', 'ub:%s' % uid, 'danger')])
    rows.append([B('⬅️ Ro‘yxat', 'a:users:0')])
    return text, KB(*rows)


def pay_screen():
    rows = [[B(short(m['name'], 30), 'pm:%s' % m['id'])] for m in db_pm_list()]
    rows.append([B('➕ To‘lov usuli qo‘shish', 'pma', 'success')])
    rows.append([B('⬅️ Panel', 'admin')])
    return head('TO‘LOV USULLARI', '💳') + '\nFoydalanuvchiga buyurtma paytida ko‘rsatiladi:', KB(*rows)


def pm_screen(m):
    text = '%s\n<b>%s</b>\n%s\n\n<code>%s</code>' % (head('TO‘LOV USULI', '💳'), esc(m['name']), esc(m['description']), esc(m['details']))
    rows = [[B('📝 Nomi', 'pmf:%s:name' % m['id']), B('📄 Tavsif', 'pmf:%s:description' % m['id'])],
            [B('💳 Rekvizitlar', 'pmf:%s:details' % m['id'])]]
    rows.append([B('🗑 O‘chirish', 'pmd:%s' % m['id'], 'danger'), B('⬅️ Orqaga', 'a:pay')])
    return text, KB(*rows)


def admins_screen():
    rows = [[B('👤 %s • %d ruxsat' % (a['id'], len([p for p in (a['perms'] or '').split(',') if p])), 'ad:%s' % a['id'])] for a in db_admins()]
    rows.append([B('➕ Admin qo‘shish', 'ada', 'success')])
    rows.append([B('⬅️ Panel', 'admin')])
    return head('ADMINLAR', '👮') + '\nSuper Admin: <code>%s</code>\nQo‘shimcha adminlar va ularning ruxsatlari:' % SUPER, KB(*rows)


def admin_perm_screen(aid):
    perms = db_admin_perms(aid)
    rows = [[B('%s %s' % ('🟢' if k in perms else '⚪', label), 'ap:%s:%s' % (aid, k))] for k, label in PERMS.items()]
    rows.append([B('🗑 Adminni olib tashlash', 'adr:%s' % aid, 'danger')])
    rows.append([B('⬅️ Orqaga', 'a:admins')])
    return head('ADMIN RUXSATLARI', '👮') + '\nAdmin ID: <code>%s</code>\nRuxsatni yoqish/o‘chirish uchun bosing.\n<i>RCON, adminlar va xavfsizlik faqat Super Adminga tegishli.</i>' % aid, KB(*rows)


def security_screen():
    lines = []
    rows = []
    for i, (k, t, label) in enumerate(SEC_FIELDS):
        v = kv_get(t, k)
        lines.append('• %s: <b>%s</b>' % (label, esc(v)))
        rows.append([B('%s: %s' % (short(label, 26), v), 'sc:%d' % i)])
    maint = setting('maintenance', 'false') == 'true'
    rows.append([B('🛠 Texnik rejim: %s' % ('YOQILGAN' if maint else 'o‘chiq'), 'sec:maint', 'danger' if maint else None)])
    rows.append([B('📜 Audit log', 'sec:audit'), B('💾 Backup', 'sec:backup', 'primary')])
    rows.append([B('⬅️ Panel', 'admin')])
    return head('XAVFSIZLIK', '🔒') + '\n' + '\n'.join(lines) + '\n\n🛡 Rate limit, callback validatsiya, nickname tekshiruvi, idempotent buyurtma bajarilishi doimiy yoqilgan.', KB(*rows)


def run_broadcast(admin_id, text):
    if not _bcast_busy.acquire(blocking=False):
        return send(admin_id, '⏳ Boshqa xabar yuborish davom etmoqda.')
    ok = fail = 0
    try:
        for uid in db_all_user_ids():
            r = send(uid, text)
            if r:
                ok += 1
            else:
                fail += 1
            time.sleep(0.06)  # Telegram limiti (~30 xabar/soniya) dan past
    finally:
        _bcast_busy.release()
    db_audit(admin_id, 'broadcast', 'ok=%d fail=%d' % (ok, fail))
    send(admin_id, '📢 Xabar yuborish tugadi.\n🟢 Yuborildi: %d\n🔴 Yetkazilmadi: %d' % (ok, fail))


def test_emoji(chat, key):
    e, cid = _emo_row(key)
    if not cid:
        return send(chat, '🧪 Custom emoji ID yo‘q. Oddiy emoji: %s' % esc(e))
    try:
        kb = KB([Btn('Test tugma', callback_data='noop', icon=cid)])
        bot.send_message(chat, '🧪 Test: <tg-emoji emoji-id="%s">%s</tg-emoji>\nAgar yuqorida premium emoji o‘rnida oddiy %s ko‘rinsa — bot uchun custom emoji ishlamayapti (fallback ishlatiladi).' % (cid, esc(e), esc(e)), reply_markup=kb)
    except ApiTelegramException as ex:
        send(chat, '❌ Custom emoji qabul qilinmadi: <code>%s</code>\nBot avtomatik oddiy emoji (%s) ishlatadi.' % (esc(str(ex)[:200]), esc(e)))


def parse_int(s):
    return int(re.sub(r'[\s,._]', '', s))


NEWP_STEPS = [('name', 'Mahsulot nomini yuboring (masalan: VIP):'),
              ('price', 'Narxini yuboring (UZS, faqat raqam):'),
              ('duration', 'Muddatini yuboring (kun; 0 = muddatsiz):'),
              ('emoji', 'Emoji yuboring (masalan: ⭐):'),
              ('description', 'Tavsifini yuboring:'),
              ('command', 'RCON command yuboring. {player} — nickname, {days} — muddat.\nMasalan: <code>lp user {player} parent addtemp vip {days}d accumulate</code>')]


def admin_callback(c, uid, d, chat):
    """Admin tugmalari. Qayta ishlangan bo'lsa True."""
    if d == 'noop':
        return True
    if d == 'admin':
        if is_admin(uid):
            show(c, admin_title(), admin_kb(uid))
        return True
    if not is_admin(uid):
        return False

    # ---------- mahsulotlar ----------
    if d == 'a:products':
        if not has_perm(uid, 'products'):
            return deny(chat)
        rows = [[B('%s %s' % (emo_plain('cat_' + k['code']), k['name']), 'a:cat:%s' % k['code'])] for k in db_categories()]
        rows.append([B('⬅️ Panel', 'admin')])
        show(c, head('DONATE MAHSULOTLARI', '📦') + '\nBo‘limni tanlang:', KB(*rows))
        return True
    if d.startswith('a:cat:'):
        if not has_perm(uid, 'products'):
            return deny(chat)
        text, kb = cat_screen(d[6:])
        show(c, text, kb)
        return True
    if d == 'a:prices':
        if not has_perm(uid, 'products'):
            return deny(chat)
        rows = [[B('%s %s — %s' % (p['emoji'], short(p['name'], 18), money(p['price'])), 'field:%s:price' % p['id'])] for p in db_products()]
        rows.append([B('⬅️ Panel', 'admin')])
        show(c, head('NARXLARNI BOSHQARISH', '💰') + '\nNarxini o‘zgartirmoqchi bo‘lgan mahsulotni tanlang:', KB(*rows))
        return True
    if d.startswith('edit:'):
        if not has_perm(uid, 'products'):
            return deny(chat)
        p = db_product(int(d[5:]))
        if not p:
            send(chat, 'Mahsulot topilmadi.')
            return True
        text, kb = product_edit_screen(p)
        show(c, text, kb)
        return True
    if d.startswith('field:'):
        if not has_perm(uid, 'products'):
            return deny(chat)
        _, pid, field = d.split(':')
        if field not in dict(PRODUCT_FIELDS):
            return True
        admin_flow[uid] = {'k': 'field', 'pid': int(pid), 'field': field}
        hint = {'emoji_id': 'Premium emoji ID (faqat raqamlar) yuboring. O‘chirish uchun: -',
                'command': 'Yangi command yuboring. {player} — nickname, {days} — muddat.',
                'price': 'Yangi narxni yuboring (UZS, raqam).', 'duration': 'Yangi muddatni yuboring (kun, 0 = muddatsiz).'}.get(field, 'Yangi qiymatni yuboring.')
        send(chat, '🟡 %s\n/cancel — bekor qilish' % hint)
        return True
    if d.startswith('del:'):
        if not has_perm(uid, 'products'):
            return deny(chat)
        p = db_product(int(d[4:]))
        if p:
            show(c, '🗑 <b>%s</b> o‘chirilsinmi?' % esc(p['name']), KB([B('✅ Ha, o‘chirish', 'delok:%s' % p['id'], 'danger'), B('⬅️ Yo‘q', 'edit:%s' % p['id'])]))
        return True
    if d.startswith('delok:'):
        if not has_perm(uid, 'products'):
            return deny(chat)
        pid = int(d[6:])
        p = db_product(pid)
        db_delete_product(pid)
        db_audit(uid, 'product_delete', pid)
        show(c, '🗑 Mahsulot o‘chirildi (eski buyurtmalar saqlanadi).', back_kb('a:cat:%s' % (p['category'] if p else 'rank'), '⬅️ Orqaga'))
        return True
    if d.startswith('addp:'):
        if not has_perm(uid, 'products'):
            return deny(chat)
        admin_flow[uid] = {'k': 'newp', 'cat': d[5:], 'step': 0, 'data': {}}
        send(chat, '➕ <b>Yangi mahsulot</b> (1/6)\n%s\n/cancel — bekor qilish' % NEWP_STEPS[0][1])
        return True

    # ---------- buyurtmalar ----------
    if d.startswith('a:orders:'):
        if not has_perm(uid, 'orders_view'):
            return deny(chat)
        f = d[9:]
        label, sts = ORDER_FILTERS.get(f, ORDER_FILTERS['open'])
        rows = [[B(('• ' if k == f else '') + v[0], 'a:orders:%s' % k) for k, v in ORDER_FILTERS.items()], [B('⬅️ Panel', 'admin')]]
        orders = db_list_orders(limit=10, statuses=sts)
        show(c, head('BUYURTMALAR — %s' % label.upper(), emo('adm_orders')) + '\nOxirgi %d ta:' % len(orders), KB(*rows))
        for o in orders:
            text, kb = order_card(o)
            send(chat, text, kb)
        return True
    if d.startswith(('approve:', 'retry:', 'reject:')):
        if not has_perm(uid, 'orders_manage'):
            return deny(chat)
        action, oid = d.split(':')
        oid = int(oid)
        o = db_get_order(oid)
        if not o:
            return True
        if action == 'approve':
            ok = db_approve_once(oid)
        elif action == 'retry':
            ok = db_retry_failed(oid)
        else:
            ok = db_reject_order(oid)
        finish_buttons(c)
        if not ok:
            send(chat, '⚠️ Buyurtma #%s holati o‘zgargan (allaqachon qayta ishlangan).' % oid)
            return True
        db_audit(uid, 'order_' + action, oid)
        if action == 'reject':
            send(o['user_id'], txt('order_rejected_text', order_id=oid, product=esc(o['product_name']), player=esc(o['player'])))
            send(chat, '🔴 #%s rad etildi.' % oid)
        else:
            if action == 'approve':
                send(o['user_id'], '🔵 Buyurtma <b>#%s</b> tasdiqlandi. Serverda bajarilmoqda…' % oid)
            enqueue(oid)
            send(chat, '🟢 #%s navbatga qo‘yildi.' % oid)
        return True
    if d.startswith('rcpt:'):
        if not has_perm(uid, 'orders_view'):
            return deny(chat)
        o = db_get_order(int(d[5:]))
        if not o or not o['receipt_file_id']:
            send(chat, 'Chek topilmadi.')
        else:
            send_media(chat, o['receipt_kind'], o['receipt_file_id'], '🧾 Chek #%s' % o['id'])
        return True

    # ---------- statistika ----------
    if d == 'a:stats':
        if not has_perm(uid, 'stats'):
            return deny(chat)
        show(c, stats_text(), back_kb('admin', '⬅️ Panel'))
        return True

    # ---------- server sozlamalari ----------
    if d == 'a:server':
        if not has_perm(uid, 'server'):
            return deny(chat)
        text, kb = server_settings_screen()
        show(c, text, kb)
        return True
    if d.startswith('ss:'):
        if not has_perm(uid, 'server'):
            return deny(chat)
        i = int(d[3:])
        admin_flow[uid] = {'k': 'ss', 'i': i}
        send(chat, '🟡 <b>%s</b>\nHozirgi: <code>%s</code>\nYangi qiymatni yuboring (o‘chirish uchun: -)\n/cancel — bekor' % (esc(SERVER_FIELDS[i][1]), esc(sget(SERVER_FIELDS[i][0]) or '—')))
        return True

    # ---------- RCON (faqat Super Admin) ----------
    if d == 'a:rcon' or d.startswith('rx'):
        if not has_perm(uid, 'rcon'):
            return deny(chat)
        if d == 'rx:toggle':
            rset('enabled', 'false' if rget('enabled') == 'true' else 'true')
            db_audit(uid, 'rcon_toggle', rget('enabled'))
        elif d.startswith('rxs:'):
            i = int(d[4:])
            admin_flow[uid] = {'k': 'rxs', 'i': i}
            extra = ' Xabaringiz xavfsizlik uchun chatdan o‘chiriladi.' if RCON_FIELDS[i][0] == 'password' else ''
            send(chat, '🟡 <b>%s</b>\nYangi qiymatni yuboring.%s\n/cancel — bekor' % (esc(RCON_FIELDS[i][1]), extra))
            return True
        elif d == 'rx:check':
            try:
                rcon.check()
                send(chat, '🟢 RCON ulanish va autentifikatsiya muvaffaqiyatli.')
            except Exception as e:
                send(chat, '🔴 RCON xatosi: <code>%s</code>' % esc(str(e)))
        elif d == 'rx:test':
            admin_flow[uid] = {'k': 'rx_test'}
            send(chat, '🧪 Serverda bajariladigan test buyrug‘ini yuboring (masalan: <code>list</code>).\nStop/op/reload kabi xavfli buyruqlar taqiqlangan.\n/cancel — bekor')
            return True
        text, kb = rcon_screen()
        show(c, text, kb)
        return True

    # ---------- bot matnlari ----------
    if d == 'a:texts':
        if not has_perm(uid, 'texts'):
            return deny(chat)
        text, kb = texts_screen()
        show(c, text, kb)
        return True
    if d.startswith(('tx:', 'txr:')):
        if not has_perm(uid, 'texts'):
            return deny(chat)
        i = int(d.split(':')[1])
        key, label = TEXT_FIELDS[i]
        if d.startswith('txr:'):
            if key.startswith('desc:'):
                db_set_cat_desc(key[5:], dict((s[0], s[2]) for s in SEED_CATS)[key[5:]])
            else:
                set_setting(key, TEXT_DEFAULTS[key])
            db_audit(uid, 'text_reset', key)
        cur = text_value(key)
        show(c, '%s\n<b>%s</b>\n\nHozirgi matn:\n<code>%s</code>\n\n<i>HTML: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;. O‘zgaruvchilar: {order_id} {product} {player}</i>' % (
            head('MATN', '📝'), esc(label), esc(cur[:1500])),
            KB([B('✏️ O‘zgartirish', 'txe:%d' % i, 'primary')], [B('♻️ Standart holatga', 'txr:%d' % i)], [B('⬅️ Orqaga', 'a:texts')]))
        return True
    if d.startswith('txe:'):
        if not has_perm(uid, 'texts'):
            return deny(chat)
        admin_flow[uid] = {'k': 'tx', 'i': int(d[4:])}
        send(chat, '🟡 Yangi matnni yuboring (HTML teglar ishlaydi).\n/cancel — bekor')
        return True

    # ---------- emoji editor ----------
    if d == 'a:emoji':
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        text, kb = emoji_main_screen()
        show(c, text, kb)
        return True
    if d.startswith('ui:'):
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        key = {'custom': 'custom_emoji', 'styles': 'button_styles'}.get(d[3:])
        if key:
            set_setting(key, 'false' if setting(key, 'true') == 'true' else 'true')
            emoji_reload()
            db_audit(uid, 'ui_toggle', key)
        text, kb = emoji_main_screen()
        show(c, text, kb)
        return True
    if d.startswith('em:'):
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        sec = d[3:]
        rows = []
        for r in db_emoji_rows(sec):
            lbl = EMOJI_DEFAULTS.get(r['key'], ('', '', r['key']))[2]
            rows.append([B('%s %s%s' % (r['emoji'], lbl, ' 💎' if r['custom_id'] else ''), 'ek:%s' % r['key'])])
        rows.append([B('⬅️ Orqaga', 'a:emoji')])
        show(c, head(EMOJI_SECTIONS.get(sec, sec).upper(), '🎨') + '\n💎 — custom emoji ulangan. Tahrirlash uchun tanlang:', KB(*rows))
        return True
    if d.startswith(('ek:', 'er:')):
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        key = d[3:]
        if key not in EMOJI_DEFAULTS:
            return True
        if d.startswith('er:'):
            db_emoji_reset(key)
            db_audit(uid, 'emoji_reset', key)
        e, cid = _emo_row(key)
        show(c, '%s\n<b>%s</b>\nOddiy emoji: %s\nCustom emoji ID: <code>%s</code>' % (head('EMOJI', '🎨'), esc(EMOJI_DEFAULTS[key][2]), esc(e), esc(cid or '—')),
             KB([B('✏️ Oddiy emoji', 'ee:%s' % key), B('💎 Custom ID', 'ec:%s' % key)],
                [B('🧪 Test', 'et:%s' % key, 'primary'), B('♻️ Standart', 'er:%s' % key)],
                [B('⬅️ Orqaga', 'em:%s' % EMOJI_DEFAULTS[key][1])]))
        return True
    if d.startswith(('ee:', 'ec:')):
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        key = d[3:]
        if key not in EMOJI_DEFAULTS:
            return True
        if d.startswith('ee:'):
            admin_flow[uid] = {'k': 'em', 'key': key}
            send(chat, '🟡 Yangi oddiy emojini yuboring.\n/cancel — bekor')
        else:
            admin_flow[uid] = {'k': 'ec', 'key': key}
            send(chat, '🟡 Telegram Premium custom emoji ID ni yuboring (faqat raqamlar). O‘chirish uchun: -\n'
                       'ID ni olish: premium emoji yuborilgan xabarni @getidsbot ga forward qiling.\n/cancel — bekor')
        return True
    if d.startswith('et:'):
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        test_emoji(chat, d[3:])
        return True

    # ---------- to'lov usullari ----------
    if d == 'a:pay':
        if not has_perm(uid, 'payments'):
            return deny(chat)
        text, kb = pay_screen()
        show(c, text, kb)
        return True
    if d == 'pma':
        if not has_perm(uid, 'payments'):
            return deny(chat)
        admin_flow[uid] = {'k': 'pma', 'step': 0, 'data': {}}
        send(chat, '➕ To‘lov usuli nomini yuboring (masalan: 💳 Uzcard):\n/cancel — bekor')
        return True
    if d.startswith(('pm:', 'pmf:', 'pmd:', 'pmdok:')):
        if not has_perm(uid, 'payments'):
            return deny(chat)
        parts = d.split(':')
        m = db_pm_get(int(parts[1]))
        if not m:
            send(chat, 'To‘lov usuli topilmadi.')
            return True
        if parts[0] == 'pm':
            text, kb = pm_screen(m)
            show(c, text, kb)
        elif parts[0] == 'pmf':
            admin_flow[uid] = {'k': 'pmf', 'id': m['id'], 'field': parts[2]}
            send(chat, '🟡 Yangi qiymatni yuboring.\n/cancel — bekor')
        elif parts[0] == 'pmd':
            show(c, '🗑 <b>%s</b> o‘chirilsinmi?' % esc(m['name']), KB([B('✅ Ha', 'pmdok:%s' % m['id'], 'danger'), B('⬅️ Yo‘q', 'pm:%s' % m['id'])]))
        else:
            db_pm_delete(m['id'])
            db_audit(uid, 'payment_method_delete', m['id'])
            text, kb = pay_screen()
            show(c, text, kb)
        return True

    # ---------- foydalanuvchilar ----------
    if d.startswith('a:users:'):
        if not has_perm(uid, 'users'):
            return deny(chat)
        text, kb = users_screen(max(0, int(d[8:])))
        show(c, text, kb)
        return True
    if d == 'usr:search':
        if not has_perm(uid, 'users'):
            return deny(chat)
        admin_flow[uid] = {'k': 'user_search'}
        send(chat, '🔎 Foydalanuvchi ID raqami yoki @username ni yuboring:\n/cancel — bekor')
        return True
    if d.startswith(('u:', 'ub:', 'uu:', 'uo:')):
        if not has_perm(uid, 'users'):
            return deny(chat)
        kind, tid = d.split(':')
        tid = int(tid)
        if kind in ('ub', 'uu'):
            if is_admin(tid):
                send(chat, 'Adminni bloklab bo‘lmaydi.')
                return True
            db_set_ban(tid, kind == 'ub')
            db_audit(uid, 'user_ban' if kind == 'ub' else 'user_unban', tid)
        if kind == 'uo':
            rows = db_list_orders(tid, 10)
            text = head('BUYURTMALAR', '📦') + '\n' + ('\n'.join('#%s %s — %s %s' % (o['id'], esc(o['product_name']), emo('st_' + o['status']), STATUS_UZ.get(o['status'], '')) for o in rows) or 'Yo‘q')
            show(c, text, back_kb('u:%s' % tid, '⬅️ Orqaga'))
        else:
            text, kb = user_screen(tid, True)
            show(c, text, kb)
        return True

    # ---------- adminlar (faqat Super Admin) ----------
    if d in ('a:admins', 'ada') or d.startswith(('ad:', 'ap:', 'adr:', 'adrok:')):
        if not has_perm(uid, 'admins'):
            return deny(chat)
        if d == 'a:admins':
            text, kb = admins_screen()
            show(c, text, kb)
        elif d == 'ada':
            admin_flow[uid] = {'k': 'admin_add'}
            send(chat, '👮 Yangi admin Telegram ID raqamini yuboring (u avval botga /start bosgan bo‘lishi kerak):\n/cancel — bekor')
        else:
            parts = d.split(':')
            aid = int(parts[1])
            if aid == SUPER or not db_is_admin(aid):
                send(chat, 'Bu admin ustida amal bajarib bo‘lmaydi.')
                return True
            if parts[0] == 'ap' and parts[2] in PERMS:
                perms = db_admin_perms(aid)
                perms.symmetric_difference_update({parts[2]})
                db_admin_set_perms(aid, perms)
                db_audit(uid, 'admin_perm', '%s:%s' % (aid, parts[2]))
            if parts[0] == 'adr':
                show(c, '🗑 Admin <code>%s</code> olib tashlansinmi?' % aid, KB([B('✅ Ha', 'adrok:%s' % aid, 'danger'), B('⬅️ Yo‘q', 'ad:%s' % aid)]))
                return True
            if parts[0] == 'adrok':
                db_admin_remove(aid)
                db_audit(uid, 'admin_remove', aid)
                text, kb = admins_screen()
                show(c, text, kb)
                return True
            text, kb = admin_perm_screen(aid)
            show(c, text, kb)
        return True

    # ---------- xavfsizlik (faqat Super Admin) ----------
    if d == 'a:security' or d.startswith(('sc:', 'sec:')):
        if not has_perm(uid, 'security'):
            return deny(chat)
        if d.startswith('sc:'):
            i = int(d[3:])
            admin_flow[uid] = {'k': 'sc', 'i': i}
            send(chat, '🟡 <b>%s</b>\nYangi qiymatni yuboring (raqam).\n/cancel — bekor' % esc(SEC_FIELDS[i][2]))
            return True
        if d == 'sec:maint':
            set_setting('maintenance', 'false' if setting('maintenance') == 'true' else 'true')
            db_audit(uid, 'maintenance', setting('maintenance'))
        elif d == 'sec:audit':
            rows = db_audit_list(15)
            send(chat, head('AUDIT LOG', '📜') + '\n' + ('\n'.join('%s • %s • %s %s' % (esc(r['created'][5:16]), r['actor'], esc(r['action']), esc(short(r['details'] or '', 40))) for r in rows) or 'Bo‘sh'))
            return True
        elif d == 'sec:backup':
            path = db_backup()
            db_audit(uid, 'backup', path)
            try:
                with open(path, 'rb') as f:
                    bot.send_document(chat, f, caption='💾 Backup: %s' % path)
            except Exception:
                send(chat, '💾 Backup yaratildi: %s' % esc(path))
            return True
        text, kb = security_screen()
        show(c, text, kb)
        return True

    # ---------- xabar yuborish ----------
    if d == 'a:bcast':
        if not has_perm(uid, 'broadcast'):
            return deny(chat)
        admin_flow[uid] = {'k': 'bcast'}
        send(chat, '📢 Hamma foydalanuvchilarga yuboriladigan xabar matnini yuboring (HTML ishlaydi).\n/cancel — bekor')
        return True
    if d in ('bc:go', 'bc:no'):
        if not has_perm(uid, 'broadcast'):
            return deny(chat)
        text = bcast_draft.pop(uid, None)
        finish_buttons(c)
        if d == 'bc:go' and text:
            db_audit(uid, 'broadcast_start', len(text))
            threading.Thread(target=run_broadcast, args=(uid, text), daemon=True).start()
            send(chat, '📤 Yuborish boshlandi…')
        else:
            send(chat, 'Bekor qilindi.')
        return True
    return False


# ============================ XABAR VA BUYRUQ HANDLERLARI ============================
def banned_notice(m_or_c_chat, uid):
    if db_is_banned(uid) and not is_admin(uid):
        send(m_or_c_chat, '⛔ Siz botdan foydalanishdan cheklangansiz.')
        return True
    return False


@bot.message_handler(commands=['start'], chat_types=['private'])
def start(m):
    uid = m.from_user.id
    db_user(m.from_user)
    if banned_notice(m.chat.id, uid):
        return
    clear_flows(uid)
    send(m.chat.id, txt('start_text'), home_kb(uid))


@bot.message_handler(commands=['version'])
def version_cmd(m):
    bot.reply_to(m, 'DARKZONA Donate Bot <b>PREMIUM</b> — BLACKdev')


@bot.message_handler(commands=['id'])
def id_cmd(m):
    bot.reply_to(m, 'Sizning Telegram ID: <code>%s</code>' % m.from_user.id)


@bot.message_handler(commands=['admin', 'panel'], chat_types=['private'])
def admin_cmd(m):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, '⛔ Ruxsat yo‘q')
    send(m.chat.id, admin_title(), admin_kb(m.from_user.id))


@bot.message_handler(commands=['cancel'], chat_types=['private'])
def cancel(m):
    clear_flows(m.from_user.id)
    bcast_draft.pop(m.from_user.id, None)
    send(m.chat.id, '🔴 Amal bekor qilindi.', back_kb())


@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    uid = c.from_user.id
    if not limiter.allow(('cb', uid)):
        try:
            return bot.answer_callback_query(c.id, '⏳ Sekinroq bosing')
        except Exception:
            return
    try:
        bot.answer_callback_query(c.id)
    except Exception:
        pass
    chat = c.message.chat.id if c.message else uid
    try:
        d = c.data or ''
        if len(d) > 64 or not re.fullmatch(r'[A-Za-z0-9_:\-]+', d):
            return  # callback validatsiyasi
        db_user(c.from_user)
        if db_is_banned(uid) and not is_admin(uid):
            return
        if user_callback(c, uid, d, chat):
            return
        admin_callback(c, uid, d, chat)
    except Exception:
        log.exception('callback xatosi: %s', c.data)
        send(chat, '⚠️ Xatolik yuz berdi. Qaytadan urinib ko‘ring: /start')


@bot.message_handler(content_types=['photo'], chat_types=['private'])
def photo(m):
    if not mlimiter.allow(('m', m.from_user.id)):
        return
    db_user(m.from_user)
    if banned_notice(m.chat.id, m.from_user.id):
        return
    accept_receipt(m, m.photo[-1].file_id, 'photo')


@bot.message_handler(content_types=['document'], chat_types=['private'])
def document(m):
    if not mlimiter.allow(('m', m.from_user.id)):
        return
    mime = m.document.mime_type or ''
    if not (mime.startswith('image/') or mime == 'application/pdf'):
        return send(m.chat.id, 'Chekni rasm (screenshot) yoki PDF ko‘rinishida yuboring.')
    db_user(m.from_user)
    if banned_notice(m.chat.id, m.from_user.id):
        return
    accept_receipt(m, m.document.file_id, 'document')


@bot.message_handler(func=lambda m: True, content_types=['text'], chat_types=['private'])
def text_handler(m):
    uid = m.from_user.id
    t = (m.text or '').strip()
    if not mlimiter.allow(('m', uid)):
        return
    db_user(m.from_user)
    if banned_notice(m.chat.id, uid):
        return
    if uid in admin_flow:
        st = admin_flow.pop(uid)
        try:
            return handle_flow(m, uid, st, t)
        except Exception:
            log.exception('flow xatosi: %s', st.get('k'))
            return send(m.chat.id, '⚠️ Xatolik yuz berdi. Qaytadan urinib ko‘ring.')

    if uid in buying:
        pid = buying[uid]
        if not NICK_RE.fullmatch(t):
            return send(m.chat.id, '🔴 Nickname 3–16 belgidan iborat bo‘lsin (faqat lotin harf, raqam, _). Qaytadan yuboring yoki /cancel.')
        buying.pop(uid, None)
        p = db_product(pid)
        if not p:
            return send(m.chat.id, 'Mahsulot topilmadi.')
        drafts[uid] = {'pid': pid, 'nick': t, 'price': p['price']}
        return send(m.chat.id, draft_text(p, t), KB([B('✅ Tasdiqlash', 'cf', 'success')],
                                                    [B('✏️ Nickname o‘zgartirish', 'buy:%s' % pid), B('❌ Bekor', 'cancel_draft', 'danger')]))
    if t.startswith('/'):
        return send(m.chat.id, '🟠 Buyruq topilmadi. /start')
    send(m.chat.id, 'Menyu: /start')


def handle_flow(m, uid, st, t):
    chat, k = m.chat.id, st['k']

    def again(msg='🔴 Qiymat noto‘g‘ri. Qaytadan yuboring yoki /cancel.'):
        admin_flow[uid] = st
        send(chat, msg)

    if len(t) > 3500:
        return again('🔴 Matn juda uzun.')

    if k == 'field':
        if not has_perm(uid, 'products'):
            return deny(chat)
        field, pid = st['field'], st['pid']
        t = t.strip()
        try:
            if field in ('price', 'duration'):
                v = parse_int(t)
                assert v >= 0
            elif field == 'emoji_id':
                v = '' if t == '-' else t
                assert v == '' or (v.isdigit() and 5 <= len(v) <= 25)
            elif field == 'command':
                v = t
                assert v and len(v) <= 500 and '\n' not in v
            elif field == 'name':
                v = t
                assert 1 <= len(v) <= 40
            elif field == 'emoji':
                v = t
                assert 1 <= len(v) <= 8
            else:
                v = t
        except (ValueError, AssertionError):
            return again()
        db_save_product(pid, field, v)
        db_audit(uid, 'product_edit', '%s:%s' % (pid, field))
        warn = '\n⚠️ Buyruqda {player} yo‘q — nickname almashtirilmaydi!' if field == 'command' and '{player}' not in v else ''
        p = db_product(pid)
        return send(chat, '🟢 Saqlandi.' + warn, back_kb('edit:%s' % pid, '⬅️ Mahsulotga qaytish') if p else back_kb('admin', '⬅️ Panel'))

    if k == 'newp':
        if not has_perm(uid, 'products'):
            return deny(chat)
        field = NEWP_STEPS[st['step']][0]
        t = t.strip()
        try:
            if field in ('price', 'duration'):
                v = parse_int(t)
                assert v >= 0
            elif field == 'name':
                v = t
                assert 1 <= len(v) <= 40
            elif field == 'emoji':
                v = t
                assert 1 <= len(v) <= 8
            elif field == 'command':
                v = t
                assert v and len(v) <= 500 and '\n' not in v
            else:
                v = t
        except (ValueError, AssertionError):
            return again()
        st['data'][field] = v
        st['step'] += 1
        if st['step'] < len(NEWP_STEPS):
            admin_flow[uid] = st
            return send(chat, '➕ <b>Yangi mahsulot</b> (%d/6)\n%s\n/cancel — bekor qilish' % (st['step'] + 1, NEWP_STEPS[st['step']][1]))
        dd = st['data']
        pid = db_add_product(st['cat'], dd['name'], dd['price'], dd['duration'], dd['description'], dd['emoji'], dd['command'])
        db_audit(uid, 'product_add', dd['name'])
        warn = '\n⚠️ Buyruqda {player} yo‘q!' if '{player}' not in dd['command'] else ''
        return send(chat, '🟢 Mahsulot qo‘shildi.' + warn, back_kb('a:cat:%s' % st['cat'], '⬅️ Bo‘limga qaytish'))

    if k == 'ss':
        if not has_perm(uid, 'server'):
            return deny(chat)
        key = SERVER_FIELDS[st['i']][0]
        v = '' if t == '-' else t
        if key == 'server_port':
            try:
                v = str(parse_int(v))
                assert 1 <= int(v) <= 65535
            except (ValueError, AssertionError):
                return again('🔴 Port 1–65535 oralig‘ida bo‘lsin.')
        if key == 'server_host' and (not v or ' ' in v):
            return again('🔴 Host bo‘sh yoki bo‘sh joyli bo‘lmasin.')
        sset(key, v)
        db_audit(uid, 'server_setting', key)
        text, kb = server_settings_screen()
        return send(chat, '🟢 Saqlandi.\n\n' + text, kb)

    if k == 'rxs':
        if not has_perm(uid, 'rcon'):
            return deny(chat)
        key = RCON_FIELDS[st['i']][0]
        try:
            if key == 'port':
                v = str(parse_int(t))
                assert 1 <= int(v) <= 65535
            elif key == 'cooldown':
                v = str(float(t.replace(',', '.')))
                assert 0 <= float(v) <= 60
            elif key == 'retries':
                v = str(parse_int(t))
                assert 1 <= int(v) <= 6
            elif key == 'host':
                v = t
                assert v and ' ' not in v and len(v) <= 100
            else:
                v = t
                assert 4 <= len(v) <= 100
        except (ValueError, AssertionError):
            if key == 'password':
                try:
                    bot.delete_message(chat, m.message_id)
                except Exception:
                    pass
            return again()
        rset(key, v)
        db_audit(uid, 'rcon_setting', key)  # qiymat auditga yozilmaydi
        if key == 'password':
            try:
                bot.delete_message(chat, m.message_id)  # parol chatda qolmasligi uchun
            except Exception:
                pass
        text, kb = rcon_screen()
        return send(chat, '🟢 Saqlandi.\n\n' + text, kb)

    if k == 'rx_test':
        if not has_perm(uid, 'rcon'):
            return deny(chat)
        try:
            out = rcon.test(t)
            db_audit(uid, 'rcon_test', t[:80])
            return send(chat, '🟢 Javob:\n<code>%s</code>' % esc((out or '(bo‘sh javob)')[:1500]))
        except Exception as e:
            return send(chat, '🔴 Xato: <code>%s</code>' % esc(str(e)))

    if k == 'tx':
        if not has_perm(uid, 'texts'):
            return deny(chat)
        key = TEXT_FIELDS[st['i']][0]
        if key.startswith('desc:'):
            db_set_cat_desc(key[5:], t)
        else:
            set_setting(key, t)
        db_audit(uid, 'text_edit', key)
        return send(chat, '🟢 Matn saqlandi.', back_kb('tx:%d' % st['i'], '⬅️ Matnga qaytish'))

    if k == 'em':
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        if not (1 <= len(t) <= 8):
            return again()
        db_emoji_set(st['key'], emoji=t)
        db_audit(uid, 'emoji_set', st['key'])
        return send(chat, '🟢 Saqlandi.', back_kb('ek:%s' % st['key'], '⬅️ Orqaga'))

    if k == 'ec':
        if not has_perm(uid, 'emoji'):
            return deny(chat)
        v = '' if t == '-' else t
        if v and not (v.isdigit() and 5 <= len(v) <= 25):
            return again('🔴 Custom emoji ID faqat raqamlardan iborat bo‘lishi kerak (yoki - yuboring).')
        db_emoji_set(st['key'], custom_id=v)
        db_audit(uid, 'emoji_custom_id', st['key'])
        send(chat, '🟢 Saqlandi. Test qilib ko‘ring 👇', back_kb('ek:%s' % st['key'], '⬅️ Orqaga'))
        return test_emoji(chat, st['key'])

    if k == 'pmf':
        if not has_perm(uid, 'payments'):
            return deny(chat)
        if st['field'] == 'name' and not t:
            return again()
        db_pm_update(st['id'], st['field'], t)
        db_audit(uid, 'payment_method_edit', st['id'])
        return send(chat, '🟢 Saqlandi.', back_kb('pm:%s' % st['id'], '⬅️ Orqaga'))

    if k == 'pma':
        if not has_perm(uid, 'payments'):
            return deny(chat)
        fields = ['name', 'description', 'details']
        prompts = ['To‘lov usuli tavsifini yuboring (yoki -):', 'Rekvizitlarni yuboring (karta raqami, ism va h.k.):']
        st['data'][fields[st['step']]] = '' if (t == '-' and st['step'] == 1) else t
        st['step'] += 1
        if st['step'] < 3:
            admin_flow[uid] = st
            return send(chat, prompts[st['step'] - 1] + '\n/cancel — bekor')
        dd = st['data']
        db_pm_add(dd['name'], dd['description'], dd['details'])
        db_audit(uid, 'payment_method_add', dd['name'])
        text, kb = pay_screen()
        return send(chat, '🟢 Qo‘shildi.\n\n' + text, kb)

    if k == 'user_search':
        if not has_perm(uid, 'users'):
            return deny(chat)
        u = db_find_user(t)
        if not u:
            return send(chat, '🔴 Foydalanuvchi topilmadi.', back_kb('a:users:0', '⬅️ Ro‘yxat'))
        text, kb = user_screen(u['id'], True)
        return send(chat, text, kb)

    if k == 'admin_add':
        if not has_perm(uid, 'admins'):
            return deny(chat)
        try:
            target = parse_int(t)
            assert target > 0
        except (ValueError, AssertionError):
            return again('🔴 Faqat Telegram ID raqamini yuboring.')
        if target == SUPER:
            return send(chat, 'Super Admin allaqachon bor.')
        if db_is_admin(target):
            return send(chat, 'Bu foydalanuvchi allaqachon admin.')
        db_admin_add(target, uid)
        db_audit(uid, 'admin_add', target)
        send(target, '👮 Siz DARKZONA donate botiga admin qilib tayinlandingiz. /admin')
        text, kb = admin_perm_screen(target)
        return send(chat, '🟢 Admin qo‘shildi. Ruxsatlarni sozlang:\n\n' + text, kb)

    if k == 'sc':
        if not has_perm(uid, 'security'):
            return deny(chat)
        key, table, _label = SEC_FIELDS[st['i']]
        try:
            if key == 'cooldown':
                v = str(float(t.replace(',', '.')))
                assert 0 <= float(v) <= 60
            elif key == 'order_cooldown':
                v = str(parse_int(t))
                assert 0 <= int(v) <= 3600
            elif key == 'max_pending':
                v = str(parse_int(t))
                assert 1 <= int(v) <= 20
            else:
                v = str(parse_int(t))
                assert 1 <= int(v) <= 6
        except (ValueError, AssertionError):
            return again()
        kv_set(table, key, v)
        db_audit(uid, 'security_setting', key)
        text, kb = security_screen()
        return send(chat, '🟢 Saqlandi.\n\n' + text, kb)

    if k == 'bcast':
        if not has_perm(uid, 'broadcast'):
            return deny(chat)
        bcast_draft[uid] = t
        return send(chat, '📢 <b>Oldindan ko‘rish</b> (%d ta foydalanuvchiga):\n\n%s' % (len(db_all_user_ids()), t),
                    KB([B('✅ Yuborish', 'bc:go', 'success'), B('❌ Bekor', 'bc:no', 'danger')]))


# ============================ ISHGA TUSHIRISH ============================
def main():
    db_init()
    emoji_reload()
    register_secret(rget('password'))
    try:
        me = bot.get_me()
        log.info('Bot ulandi: @%s', me.username)
    except ApiTelegramException as e:
        raise SystemExit('Telegram token noto‘g‘ri yoki ulanib bo‘lmadi: %s' % str(e)[:100])
    except Exception as e:
        log.warning('getMe xatosi (internet?): %s', e)
    start_workers()
    log.info('DARKZONA Donate Bot PREMIUM ishga tushdi')
    while True:
        try:
            bot.infinity_polling(skip_pending=False, timeout=30, long_polling_timeout=30, logger_level=logging.WARNING)
        except Exception:
            log.exception('Polling to‘xtadi, 5 soniyadan so‘ng qayta ulanadi')
            time.sleep(5)


if __name__ == '__main__':
    main()

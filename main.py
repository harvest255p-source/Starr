"""
DARKZONA Donate Bot V3.1 — BLACKdev
Ishga tushirish:  pip install -r requirements.txt   keyin   python main.py
Hamma sozlama shu faylning tepasida. Baza (Donate.db) o'zi yaratiladi.
DIQQAT: token va parol yozilgan bu faylni GitHub'ga yuklamang!
"""
# =================== SOZLAMALAR (shu yerni to'ldiring) ===================
BOT_TOKEN = "9074327606:AAG3qE41PZqOdXe9tXEIrXho2W-pck5iubI"   # @BotFather bergan token
SUPER_ADMIN_ID = 8681116778              # sizning Telegram ID (botga /id yozsangiz ko'rsatadi)

RCON_ENABLED = True                     # RCON orqali donatni avtomatik berish
RCON_HOST = "127.0.0.1"                 # Minecraft server IP (bot shu serverda bo'lsa 127.0.0.1)
RCON_PORT = 25575                       # server.properties -> rcon.port
RCON_PASSWORD = "CHANGE_ME"             # server.properties -> rcon.password

SERVER_HOST = "darkzona.gomc.uz"        # o'yinchilar kiradigan IP/domen
SERVER_PORT = 25565
SERVER_VERSION = "Paper 1.17.1"
SUPPORT_CONTACT = "@darkzona_support"
DB_PATH = "Donate.db"
# ========================================================================
# Eslatma: server/support/RCON qiymatlari birinchi ishga tushishda bazaga yoziladi.
# Keyin ularni admin panel orqali o'zgartirish mumkin (yoki Donate.db ni o'chirib qayta boshlang).

import html
import os
import json
import logging
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

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('bot')


# ------------------------- BAZA -------------------------
def db_path():
    return DB_PATH


@contextmanager
def db_conn():
    c = sqlite3.connect(db_path(), timeout=20)
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


SEED = [
    ('rank', 'IMPERATOR', 70000, 30, 'Eng yuqori premium rank', '👑', 'lp user {player} parent set imperator'),
    ('rank', 'GENERAL', 66000, 30, 'Premium rank', '🔴', 'lp user {player} parent set general'),
    ('rank', 'AFSONA', 54000, 30, 'Afsonaviy rank', '🟣', 'lp user {player} parent set afsona'),
    ('rank', 'ELITA', 46000, 30, 'Elita rank', '🔵', 'lp user {player} parent set elita'),
    ('rank', 'TITAN', 23000, 30, 'Titan rank', '🟠', 'lp user {player} parent set titan'),
    ('rank', 'QAHRAMON', 15000, 30, 'Qahramon rank', '🟢', 'lp user {player} parent set qahramon'),
    ('rank', 'ASKAR', 3000, 30, 'Boshlang‘ich rank', '⚪', 'lp user {player} parent set askar'),
    ('token', '1K TOKEN', 5000, 0, '1 000 token', '🪙', 'tokens give {player} 1000'),
    ('token', '10K TOKEN', 13000, 0, '10 000 token', '🪙', 'tokens give {player} 10000'),
    ('token', '25K TOKEN', 16000, 0, '25 000 token', '🪙', 'tokens give {player} 25000'),
    ('token', '40K TOKEN', 23000, 0, '40 000 token', '🪙', 'tokens give {player} 40000'),
    ('token', '60K TOKEN', 30000, 0, '60 000 token', '🪙', 'tokens give {player} 60000'),
    ('token', '80K TOKEN', 42000, 0, '80 000 token', '🪙', 'tokens give {player} 80000'),
    ('token', '100K TOKEN', 53000, 0, '100 000 token', '🪙', 'tokens give {player} 100000'),
    ('title', '[PVPER]', 10000, 0, 'PVPER titul', '🏹', 'lp user {player} permission set title.pvper'),
    ('title', '[EZZ]', 15000, 0, 'EZZ titul', '⚡', 'lp user {player} permission set title.ezz'),
    ('title', '[YENGILMAS]', 20000, 0, 'YENGILMAS titul', '🛡️', 'lp user {player} permission set title.yengilmas'),
    ('title', '[AFSONAVIY]', 30000, 0, 'AFSONAVIY titul', '✨', 'lp user {player} permission set title.afsonaviy'),
    ('title', '[KILLER]', 40000, 0, 'KILLER titul', '☠️', 'lp user {player} permission set title.killer'),
    ('title', '[TOPER]', 50000, 0, 'TOPER titul', '🏆', 'lp user {player} permission set title.toper'),
]

OPEN_STATUSES = ('PENDING', 'PAYMENT_REVIEW', 'APPROVED', 'PROCESSING', 'FAILED')


def db_init():
    with db_conn() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY,role TEXT DEFAULT 'admin',added_by INTEGER,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,name TEXT,price INTEGER,duration INTEGER DEFAULT 0,description TEXT DEFAULT '',emoji TEXT DEFAULT '🎁',command TEXT DEFAULT '',active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,product_id INTEGER,product_name TEXT,price INTEGER,player TEXT,status TEXT DEFAULT 'PENDING',receipt_file_id TEXT,receipt_kind TEXT DEFAULT 'photo',command_snapshot TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,updated TEXT DEFAULT CURRENT_TIMESTAMP,execution_key TEXT UNIQUE,error TEXT,FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,actor INTEGER,action TEXT,details TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS order_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER,event TEXT,details TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        ''')
        # eski bazalar uchun migratsiya
        cols = [r['name'] for r in c.execute('PRAGMA table_info(orders)')]
        if 'receipt_kind' not in cols:
            c.execute("ALTER TABLE orders ADD COLUMN receipt_kind TEXT DEFAULT 'photo'")
        if not c.execute('SELECT 1 FROM products LIMIT 1').fetchone():
            c.executemany('INSERT INTO products(category,name,price,duration,description,emoji,command) VALUES(?,?,?,?,?,?,?)', SEED)
        defaults = {
            'server_name': 'DARKZONA',
            'server_host': SERVER_HOST,
            'server_port': SERVER_PORT,
            'server_version': SERVER_VERSION,
            'server_description': 'Premium Minecraft server',
            'support': SUPPORT_CONTACT,
            'payment_text': 'Admin panel orqali to‘lov rekvizitlarini kiriting.',
            'start_text': '🌑 DARKZONA ga xush kelibsiz! Premium donate shop.',
            'rcon_enabled': ('true' if RCON_ENABLED else 'false'),
            'rcon_host': RCON_HOST,
            'rcon_port': RCON_PORT,
            # rcon_password bazaga yozilmaydi: .env dan o'qiladi (admin panel orqali o'zgartirilsa bazada saqlanadi)
        }
        for k, v in defaults.items():
            c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (k, str(v)))


# ---------- settings ----------
def db_setting(k, d=''):
    with db_conn() as c:
        r = c.execute('SELECT value FROM settings WHERE key=?', (k,)).fetchone()
        return r['value'] if r else d


def db_set_setting(k, v):
    with db_conn() as c:
        c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, str(v)))


# ---------- products ----------
def db_product(pid):
    with db_conn() as c:
        return c.execute('SELECT * FROM products WHERE id=? AND active=1', (pid,)).fetchone()


def db_products(cat=None):
    with db_conn() as c:
        if cat:
            return c.execute('SELECT * FROM products WHERE active=1 AND category=? ORDER BY id', (cat,)).fetchall()
        return c.execute('SELECT * FROM products WHERE active=1 ORDER BY id').fetchall()


def db_save_product(pid, field, value):
    if field not in {'name', 'price', 'duration', 'description', 'emoji', 'command'}:
        raise ValueError('field')
    with db_conn() as c:
        c.execute(f'UPDATE products SET {field}=? WHERE id=?', (value, pid))


def db_add_product(cat, name, price, duration, desc, emoji, command):
    with db_conn() as c:
        cur = c.execute('INSERT INTO products(category,name,price,duration,description,emoji,command) VALUES(?,?,?,?,?,?,?)',
                        (cat, name, price, duration, desc, emoji, command))
        return cur.lastrowid


def db_delete_product(pid):
    with db_conn() as c:
        c.execute('UPDATE products SET active=0 WHERE id=?', (pid,))


# ---------- users / admins ----------
def db_user(u):
    with db_conn() as c:
        c.execute('INSERT INTO users(id,username,first_name) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name',
                  (u.id, u.username, u.first_name))


def db_admin_add(uid, by):
    with db_conn() as c:
        c.execute('INSERT OR IGNORE INTO admins(id,role,added_by) VALUES(?,?,?)', (uid, 'admin', by))


def db_admin_remove(uid):
    with db_conn() as c:
        c.execute('DELETE FROM admins WHERE id=?', (uid,))


def db_is_admin(uid):
    with db_conn() as c:
        return bool(c.execute('SELECT 1 FROM admins WHERE id=?', (uid,)).fetchone())


def db_admins():
    with db_conn() as c:
        return [r['id'] for r in c.execute('SELECT id FROM admins')]


def db_audit(actor, action, detail=''):
    with db_conn() as c:
        c.execute('INSERT INTO audit_logs(actor,action,details) VALUES(?,?,?)', (actor, action, str(detail)[:500]))


# ---------- orders ----------
def db_create_order(uid, p, nick):
    with db_conn() as c:
        cur = c.execute('INSERT INTO orders(user_id,product_id,product_name,price,player,command_snapshot,execution_key) VALUES(?,?,?,?,?,?,?)',
                        (uid, p['id'], p['name'], p['price'], nick, p['command'], str(uuid.uuid4())))
        return cur.lastrowid


def db_get_order(oid):
    with db_conn() as c:
        return c.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()


def db_list_orders(uid=None, limit=30, statuses=None):
    q, args = 'SELECT * FROM orders', []
    where = []
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


def db_update_order(oid, status, error=None):
    with db_conn() as c:
        c.execute('UPDATE orders SET status=?,error=?,updated=CURRENT_TIMESTAMP WHERE id=?', (status, error, oid))
        c.execute('INSERT INTO order_logs(order_id,event,details) VALUES(?,?,?)', (oid, status, (error or '')[:300]))


def db_attach_receipt(oid, uid, file_id, kind='photo'):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='PAYMENT_REVIEW',receipt_file_id=?,receipt_kind=?,updated=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status IN ('PENDING','PAYMENT_REVIEW')",
                        (file_id, kind, oid, uid))
        return cur.rowcount == 1


def db_cancel_by_user(oid, uid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='CANCELLED',updated=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status='PENDING'", (oid, uid))
        return cur.rowcount == 1


def db_approve_once(oid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='APPROVED',error=NULL,updated=CURRENT_TIMESTAMP WHERE id=? AND status IN ('PENDING','PAYMENT_REVIEW')", (oid,))
        return cur.rowcount == 1


def db_retry_failed(oid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='APPROVED',error=NULL,updated=CURRENT_TIMESTAMP WHERE id=? AND status='FAILED'", (oid,))
        return cur.rowcount == 1


def db_reject_order(oid):
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='REJECTED',updated=CURRENT_TIMESTAMP WHERE id=? AND status IN ('PENDING','PAYMENT_REVIEW','FAILED')", (oid,))
        return cur.rowcount == 1


def db_claim_processing(oid):
    """APPROVED -> PROCESSING atomik. Bitta buyurtma ikki marta bajarilmasligi uchun."""
    with db_conn() as c:
        cur = c.execute("UPDATE orders SET status='PROCESSING',updated=CURRENT_TIMESTAMP WHERE id=? AND status='APPROVED'", (oid,))
        return cur.rowcount == 1


def db_recover_orders():
    """Bot qayta ishga tushganda: APPROVED larni qaytaradi, PROCESSING larni FAILED qiladi (qo'lda tekshirish uchun)."""
    with db_conn() as c:
        approved = [r['id'] for r in c.execute("SELECT id FROM orders WHERE status='APPROVED' ORDER BY id")]
        stuck = [r['id'] for r in c.execute("SELECT id FROM orders WHERE status='PROCESSING'")]
        for oid in stuck:
            c.execute("UPDATE orders SET status='FAILED',error='Bot qayta ishga tushdi: buyruq bajarilgan-bajarilmaganini tekshiring',updated=CURRENT_TIMESTAMP WHERE id=?", (oid,))
    return approved, stuck


def db_stats():
    q = {
        'users': 'SELECT COUNT(*) FROM users',
        'orders': 'SELECT COUNT(*) FROM orders',
        'completed': "SELECT COUNT(*) FROM orders WHERE status='COMPLETED'",
        'pending': "SELECT COUNT(*) FROM orders WHERE status IN ('PENDING','PAYMENT_REVIEW','APPROVED','PROCESSING')",
        'failed': "SELECT COUNT(*) FROM orders WHERE status='FAILED'",
        'rejected': "SELECT COUNT(*) FROM orders WHERE status='REJECTED'",
        'revenue': "SELECT COALESCE(SUM(price),0) FROM orders WHERE status='COMPLETED'",
        'today_orders': "SELECT COUNT(*) FROM orders WHERE date(created,'localtime')=date('now','localtime')",
        'today_revenue': "SELECT COALESCE(SUM(price),0) FROM orders WHERE status='COMPLETED' AND date(updated,'localtime')=date('now','localtime')",
    }
    with db_conn() as c:
        return {k: c.execute(sql).fetchone()[0] for k, sql in q.items()}


def db_backup():
    os.makedirs('backups', exist_ok=True)
    dest = f'backups/Donate-{int(time.time())}.db'
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)  # WAL bilan ham to'g'ri ishlaydi
    finally:
        dst.close()
        src.close()
    return dest


# ------------------------- XAVFSIZLIK -------------------------
NICK_RE = re.compile(r'^[A-Za-z0-9_]{3,16}$')


def valid_nick(s):
    return bool(NICK_RE.fullmatch((s or '').strip()))


def clean_nick(s):
    s = (s or '').strip()
    if not valid_nick(s):
        raise ValueError('Nickname 3–16 belgidan iborat bo‘lsin (faqat lotin harf, raqam, _).')
    return s


class RateLimiter:
    def __init__(self, interval=1.2):
        self.interval = interval
        self.last = {}

    def allow(self, key):
        now = time.monotonic()
        if now - self.last.get(key, 0) < self.interval:
            return False
        self.last[key] = now
        if len(self.last) > 5000:  # xotira to'lib ketmasligi uchun
            cutoff = now - 60
            self.last = {k: v for k, v in self.last.items() if v > cutoff}
        return True


# ------------------------- RCON -------------------------
NICK = re.compile(r'^[A-Za-z0-9_]{3,16}$')
BAD_REPLIES = ('unknown or incomplete command', 'unknown command', 'no player was found',
               'no user found', 'a user with that name does not exist', 'could not find')


class RconError(Exception):
    pass


def _exact(s, n):
    buf = b''
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise RconError('Server ulanishni uzdi')
        buf += chunk
    return buf


def _send(s, rid, typ, body):
    data = struct.pack('<ii', rid, typ) + body.encode('utf-8') + b'\x00\x00'
    s.sendall(struct.pack('<i', len(data)) + data)


def _recv(s):
    (n,) = struct.unpack('<i', _exact(s, 4))
    if n < 10 or n > 8192:
        raise RconError('Noto‘g‘ri RCON paket')
    data = _exact(s, n)
    rid, typ = struct.unpack('<ii', data[:8])
    return rid, typ, data[8:-2].decode('utf-8', 'replace')


def run_command(host, port, password, cmd, timeout=5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            _send(s, 1, 3, password)
            for _ in range(3):
                rid, typ, _body = _recv(s)
                if typ == 2:
                    break
            else:
                raise RconError('Auth javobi kelmadi')
            if rid == -1:
                raise RconError('RCON parol noto‘g‘ri')
            _send(s, 2, 2, cmd)
            _rid, _typ, body = _recv(s)
            return body
    except (socket.timeout, TimeoutError):
        raise RconError('RCON timeout (buyruq bajarilgan bo‘lishi mumkin!)')
    except OSError as e:
        raise RconError(f'RCON ulanish xatosi: {e}')


class RCON:
    def _cfg(self):
        if db_setting('rcon_enabled', 'false').strip().lower() != 'true':
            raise RconError('RCON o‘chirilgan (admin panel → RCON yoki /rcon_on)')
        pw = db_setting('rcon_password', '') or RCON_PASSWORD
        if not pw or pw == 'CHANGE_ME':
            raise RconError('RCON parol sozlanmagan')
        return db_setting('rcon_host', '127.0.0.1'), int(db_setting('rcon_port', '25575') or 25575), pw

    def command(self, cmd):
        host, port, pw = self._cfg()
        return run_command(host, port, pw, cmd.lstrip('/'))

    def product(self, template, nick):
        if not NICK.fullmatch(nick or ''):
            raise RconError('Noto‘g‘ri nickname')
        if not template or len(template) > 500 or '\n' in template or '\r' in template:
            raise RconError('Mahsulot RCON buyrug‘i noto‘g‘ri yoki bo‘sh')
        reply = self.command(template.replace('{player}', nick))
        low = (reply or '').lower()
        if any(b in low for b in BAD_REPLIES):
            raise RconError(f'Server javobi: {reply[:150]}')
        return reply


# ------------------------- SERVER HOLATI -------------------------
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


def _exact(s, n):
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
        payload = _exact(s, length)
        latency = round((time.monotonic() - t0) * 1000)
    _pid, pos = _read_varint(payload)
    slen, pos = _read_varint(payload, pos)
    data = json.loads(payload[pos:pos + slen].decode('utf-8', 'replace'))
    return data, latency


def get_status():
    try:
        data, latency = slp_ping(db_setting('server_host', 'darkzona.gomc.uz'), int(db_setting('server_port', '25565')))
        pl = data.get('players', {})
        return {'state': 'ONLINE', 'ping': latency, 'online': pl.get('online', 0), 'max': pl.get('max'),
                'version': data.get('version', {}).get('name', db_setting('server_version', 'Unknown'))}
    except Exception:
        return {'state': 'OFFLINE', 'ping': None, 'online': None, 'max': None,
                'version': db_setting('server_version', 'Unknown')}


# ------------------------- DO'KON -------------------------
def shop_kb(cat):
    k = InlineKeyboardMarkup(row_width=1)
    for p in db_products(cat):
        k.add(InlineKeyboardButton(f'{p["emoji"]} {p["name"]} • {p["price"]:,} UZS', callback_data=f'p:{p["id"]}'))
    k.add(InlineKeyboardButton('⬅️ 🟦 Bosh menyu', callback_data='home'))
    return k


def card_text(p):
    e = html.escape
    dur = f'{p["duration"]} kun' if p['duration'] else '—'
    return (f'{e(p["emoji"])} <b>{e(p["name"])}</b>\n'
            f'🟡 Narxi: <b>{p["price"]:,} UZS</b>\n'
            f'⏳ Muddat: {dur}\n\n{e(p["description"] or "")}')


def admin_kb():
    k = InlineKeyboardMarkup(row_width=2)
    k.add(InlineKeyboardButton('📦 🟦 Mahsulotlar', callback_data='a:products'),
          InlineKeyboardButton('📥 🟢 Buyurtmalar', callback_data='a:orders'))
    k.add(InlineKeyboardButton('📊 🟣 Statistika', callback_data='a:stats'),
          InlineKeyboardButton('🖥 🔵 Server', callback_data='a:server'))
    k.add(InlineKeyboardButton('🔐 🟠 RCON', callback_data='a:rcon'),
          InlineKeyboardButton('💳 🟡 To‘lov', callback_data='a:payment'))
    k.add(InlineKeyboardButton('👮 Adminlar', callback_data='a:admins'),
          InlineKeyboardButton('🧾 💾 Backup', callback_data='a:backup'))
    k.add(InlineKeyboardButton('⬅️ Menyu', callback_data='home'))
    return k


def payment_instructions():
    return db_setting('payment_text', 'To‘lov rekvizitlari admin tomonidan sozlanmagan.')


# ------------------------- BUYURTMA NAVBATI (worker) -------------------------
# (admin_ids() pastda bot qismida e'lon qilingan)
log = logging.getLogger('orders')
rcon = RCON()
q = queue.Queue()


def _notify_admins(bot, text, kb=None):
    for a in admin_ids():
        try:
            bot.send_message(a, text, reply_markup=kb)
        except Exception:
            pass


def _process(bot, oid):
    o = db_get_order(oid)
    if not o or not db_claim_processing(oid):
        return
    try:
        rcon.product(o['command_snapshot'], o['player'])
    except Exception as e:
        err = str(e)[:300] or type(e).__name__
        log.warning('Order #%s RCON failed: %s', oid, err)
        db_update_order(oid, 'FAILED', error=err)
        try:
            bot.send_message(o['user_id'], f'🟠 Buyurtma #{oid} vaqtincha bajarilmadi. Admin qayta ko‘rib chiqadi.')
        except Exception:
            pass
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton('🔁 Qayta urinish', callback_data=f'retry:{oid}'),
                                        InlineKeyboardButton('🔴 Rad', callback_data=f'reject:{oid}'))
        _notify_admins(bot, f'⚠️ Order #{oid} bajarilmadi\n🎮 {html.escape(o["player"])} • {html.escape(o["product_name"])}\n'
                            f'Sabab: <code>{html.escape(err)}</code>\n\n'
                            '❗ Timeout bo‘lsa, avval serverda buyruq bajarilmaganini tekshiring (ikki marta berib yubormaslik uchun).', kb)
        return
    db_update_order(oid, 'COMPLETED')
    try:
        bot.send_message(o['user_id'], f'🟢 Buyurtma #{oid} bajarildi: <b>{html.escape(o["product_name"])}</b>')
    except Exception:
        log.info('Order #%s: foydalanuvchiga xabar yuborib bo‘lmadi', oid)


def start_worker(bot):
    approved, stuck = db_recover_orders()
    for oid in approved:
        q.put(oid)
    if stuck:
        _notify_admins(bot, '⚠️ Bot qayta ishga tushdi. Quyidagi buyurtmalar bajarilish paytida uzilgan: '
                            + ', '.join(f'#{i}' for i in stuck) + '\nServerda tekshirib, admin panel → Buyurtmalar dan qayta urinib ko‘ring.')

    def run():
        while True:
            oid = q.get()
            try:
                _process(bot, oid)
            except Exception:
                log.exception('worker error order #%s', oid)
            finally:
                q.task_done()
            time.sleep(0.5)

    threading.Thread(target=run, daemon=True, name='rcon-order-worker').start()


def enqueue(oid):
    q.put(oid)


# ------------------------- BOT -------------------------
def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


TOKEN = BOT_TOKEN.strip()
SUPER = _int(SUPER_ADMIN_ID)
if not TOKEN or TOKEN.startswith('YOUR_'):
    raise SystemExit('main.py tepasidagi BOT_TOKEN ni to‘ldiring')
if not SUPER:
    log.warning('SUPER_ADMIN_ID sozlanmagan: super admin funksiyalari ishlamaydi')

bot = telebot.TeleBot(TOKEN, parse_mode='HTML', threaded=True, num_threads=8)
db_init()
limiter = RateLimiter(0.7)
buying = {}     # uid -> product_id (nickname kutilmoqda)
receipts = {}   # uid -> order_id (chek kutilmoqda)
admin_flow = {}  # uid -> amal

STATUS_UZ = {
    'PENDING': '🟡 To‘lov kutilmoqda', 'PAYMENT_REVIEW': '🔎 Tekshiruvda', 'APPROVED': '🔵 Tasdiqlandi',
    'PROCESSING': '⚙️ Bajarilmoqda', 'COMPLETED': '🟢 Bajarildi', 'FAILED': '🟠 Xatolik (admin ko‘radi)',
    'REJECTED': '🔴 Rad etildi', 'CANCELLED': '⚪ Bekor qilindi',
}


def esc(x):
    return html.escape('' if x is None else str(x))


def is_super(uid):
    return SUPER != 0 and uid == SUPER


def is_admin(uid):
    return is_super(uid) or db_is_admin(uid)


def admin_ids():
    return {a for a in [SUPER] + db_admins() if a}


def send(chat, text, kb=None):
    try:
        return bot.send_message(chat, text, reply_markup=kb)
    except Exception:
        log.exception('send_message xatosi')


def show(c, text, kb=None):
    """Mavjud xabarni tahrirlaydi (chat to'lib ketmasligi uchun), bo'lmasa yangi yuboradi."""
    try:
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
    except Exception as e:
        if 'not modified' in str(e):
            return
        send(c.message.chat.id, text, kb)


def clear_flows(uid):
    admin_flow.pop(uid, None)
    buying.pop(uid, None)
    receipts.pop(uid, None)


def home(uid):
    k = InlineKeyboardMarkup(row_width=2)
    k.add(InlineKeyboardButton('💎 🔵 Ranklar', callback_data='shop:rank'), InlineKeyboardButton('🪙 🟡 Tokenlar', callback_data='shop:token'))
    k.add(InlineKeyboardButton('⚔️ 🟣 Titullar', callback_data='shop:title'), InlineKeyboardButton('🛒 🟢 Buyurtmalar', callback_data='orders'))
    k.add(InlineKeyboardButton('👤 Profil', callback_data='profile'), InlineKeyboardButton('🌐 Server', callback_data='server'))
    k.add(InlineKeyboardButton('📞 Admin', callback_data='support'))
    if is_admin(uid):
        k.add(InlineKeyboardButton('🛠 🔴 Admin panel', callback_data='admin'))
    return k


def back(to='home', label='⬅️ Menyu'):
    return InlineKeyboardMarkup().add(InlineKeyboardButton(label, callback_data=to))


# ===================== BUYRUQLAR =====================
@bot.message_handler(commands=['start'], chat_types=['private'])
def start(m):
    clear_flows(m.from_user.id)
    db_user(m.from_user)
    send(m.chat.id, db_setting('start_text'), home(m.from_user.id))


@bot.message_handler(commands=['version'])
def version_cmd(m):
    bot.reply_to(m, 'DARKZONA Donate Bot <b>V3.1</b> — BLACKdev')


@bot.message_handler(commands=['admin'], chat_types=['private'])
def admin_cmd(m):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, '⛔ Ruxsat yo‘q')
    send(m.chat.id, '🛠 <b>DARKZONA ADMIN PANEL</b>', admin_kb())


@bot.message_handler(commands=['cancel'])
def cancel(m):
    clear_flows(m.from_user.id)
    send(m.chat.id, '🔴 Amal bekor qilindi.', back())


@bot.message_handler(commands=['id'])
def id_cmd(m):
    bot.reply_to(m, f'Sizning Telegram ID: <code>{m.from_user.id}</code>')


@bot.message_handler(commands=['set_start'], chat_types=['private'])
def set_start(m):
    if not is_super(m.from_user.id):
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        return send(m.chat.id, 'Format: /set_start matn')
    db_set_setting('start_text', parts[1])
    send(m.chat.id, '🟢 Start matni saqlandi.')


@bot.message_handler(commands=['set_server'], chat_types=['private'])
def set_server(m):
    if not is_super(m.from_user.id):
        return
    parts = m.text.split(maxsplit=3)
    if len(parts) < 4:
        return send(m.chat.id, 'Format: /set_server host port version')
    try:
        port = int(parts[2])
        assert 1 <= port <= 65535
    except (ValueError, AssertionError):
        return send(m.chat.id, 'Port noto‘g‘ri')
    db_set_setting('server_host', parts[1])
    db_set_setting('server_port', port)
    db_set_setting('server_version', parts[3])
    send(m.chat.id, '🟢 Server saqlandi.')


@bot.message_handler(commands=['rcon_on'], chat_types=['private'])
def rcon_on(m):
    if is_super(m.from_user.id):
        db_set_setting('rcon_enabled', 'true')
        send(m.chat.id, '🟢 RCON yoqildi')


@bot.message_handler(commands=['rcon_off'], chat_types=['private'])
def rcon_off(m):
    if is_super(m.from_user.id):
        db_set_setting('rcon_enabled', 'false')
        send(m.chat.id, '🔴 RCON o‘chirildi')


# ===================== CALLBACKLAR =====================
@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    uid = c.from_user.id
    if not limiter.allow(('cb', uid)):
        return bot.answer_callback_query(c.id, '⏳ Sekinroq bosing')
    try:
        bot.answer_callback_query(c.id)
    except Exception:
        pass
    try:
        db_user(c.from_user)  # foreign key xatosi bo'lmasligi uchun
        handle_callback(c, uid, c.data or '')
    except Exception:
        log.exception('callback xatosi: %s', c.data)
        send(c.message.chat.id, '⚠️ Xatolik yuz berdi. Qaytadan urinib ko‘ring: /start')


def finish_buttons(c):
    """Admin xabaridan tugmalarni olib tashlaydi (qayta bosilmasligi uchun)."""
    try:
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    except Exception:
        pass


def handle_callback(c, uid, d):
    chat = c.message.chat.id

    if d == 'home':
        clear_flows(uid)
        return show(c, '🌑 <b>DARKZONA</b>', home(uid))

    if d.startswith('shop:'):
        cat = d.split(':')[1]
        names = {'rank': '💎 RANK SHOP', 'token': '🪙 TOKEN SHOP', 'title': '⚔️ TITUL SHOP'}
        return show(c, names.get(cat, 'Shop'), shop_kb(cat))

    if d.startswith('p:'):
        p = db_product(int(d.split(':')[1]))
        if not p:
            return show(c, 'Mahsulot topilmadi.', back())
        k = InlineKeyboardMarkup().add(InlineKeyboardButton('🟢 🛒 Sotib olish', callback_data=f'buy:{p["id"]}'))
        k.add(InlineKeyboardButton('⬅️ Orqaga', callback_data=f'shop:{p["category"]}'))
        return show(c, card_text(p), k)

    if d.startswith('buy:'):
        p = db_product(int(d.split(':')[1]))
        if not p:
            return send(chat, 'Mahsulot topilmadi.')
        buying[uid] = p['id']
        return send(chat, '🎮 Minecraft nickname yuboring (3–16 belgi: harf, raqam yoki _).\nBekor qilish: /cancel')

    if d == 'orders':
        rows = db_list_orders(uid, 15)
        text = '🛒 <b>Buyurtmalaringiz</b>\n' + ('\n'.join(f'#{r["id"]} {esc(r["product_name"])} • {STATUS_UZ.get(r["status"], r["status"])}' for r in rows) if rows else 'Buyurtma yo‘q')
        k = InlineKeyboardMarkup()
        for r in rows:
            if r['status'] == 'PENDING':
                k.add(InlineKeyboardButton(f'🧾 Chek #{r["id"]}', callback_data=f'rc:{r["id"]}'),
                      InlineKeyboardButton(f'❌ Bekor #{r["id"]}', callback_data=f'uc:{r["id"]}'))
        k.add(InlineKeyboardButton('⬅️ Menyu', callback_data='home'))
        return show(c, text, k)

    if d.startswith('rc:'):
        o = db_get_order(int(d.split(':')[1]))
        if not o or o['user_id'] != uid or o['status'] not in ('PENDING', 'PAYMENT_REVIEW'):
            return send(chat, 'Bu buyurtmaga chek yuborib bo‘lmaydi.')
        receipts[uid] = o['id']
        return send(chat, f'🧾 #{o["id"]} uchun to‘lov chekini (rasm/screenshot) yuboring.')

    if d.startswith('uc:'):
        oid = int(d.split(':')[1])
        if db_cancel_by_user(oid, uid):
            if receipts.get(uid) == oid:
                receipts.pop(uid, None)
            return send(chat, f'⚪ Buyurtma #{oid} bekor qilindi.', back('orders', '⬅️ Buyurtmalar'))
        return send(chat, 'Bu buyurtmani bekor qilib bo‘lmaydi.')

    if d == 'profile':
        with db_conn() as con:
            n = con.execute('SELECT COUNT(*) FROM orders WHERE user_id=?', (uid,)).fetchone()[0]
        return show(c, f'👤 Telegram ID: <code>{uid}</code>\n📦 Buyurtmalar: {n}', back())

    if d == 'server':
        s = get_status()
        online = f'{s["online"]}/{s["max"] if s["max"] is not None else "—"}' if s['state'] == 'ONLINE' else '—'
        text = (f'🌐 <b>{esc(db_setting("server_name", "DARKZONA"))}</b>\n'
                f'IP: <code>{esc(db_setting("server_host"))}</code>:{esc(db_setting("server_port"))}\n'
                f'Status: {"🟢 ONLINE" if s["state"] == "ONLINE" else "🔴 OFFLINE"}\n'
                f'Players: {online}\nVersion: {esc(s["version"])}\n'
                f'Ping: {s["ping"] if s["ping"] is not None else "—"} ms')
        return show(c, text, back())

    if d == 'support':
        return show(c, esc(db_setting('support', 'Support sozlanmagan')), back())

    # ---------- ADMIN ----------
    if d == 'admin':
        if is_admin(uid):
            return show(c, '🛠 <b>DARKZONA ADMIN PANEL</b>', admin_kb())
        return

    if d == 'rcontest':
        if not is_super(uid):
            return send(chat, '🔒 Faqat Super Admin')
        try:
            result = rcon.command('list') or '(bo‘sh javob)'
        except Exception as e:
            result = f'Xato: {e}'
        return send(chat, '🔵 RCON test: ' + esc(str(result)[:900]))

    if d.startswith('a:'):
        if not is_admin(uid):
            return
        key = d[2:]
        if key == 'products':
            return admin_products(c)
        if key == 'orders':
            return admin_orders(chat)
        if key == 'stats':
            st = db_stats()
            text = ('📊 <b>STATISTIKA</b>\n'
                    f'👥 Foydalanuvchilar: {st["users"]}\n📦 Jami buyurtma: {st["orders"]}\n'
                    f'🟢 Bajarilgan: {st["completed"]}\n🟡 Jarayonda: {st["pending"]}\n'
                    f'🟠 Xatolik: {st["failed"]}\n🔴 Rad etilgan: {st["rejected"]}\n'
                    f'💰 Jami daromad: {st["revenue"]:,} UZS\n'
                    f'📅 Bugun: {st["today_orders"]} ta buyurtma • {st["today_revenue"]:,} UZS')
            return show(c, text, back('admin', '⬅️ Panel'))
        if key in ('server', 'rcon'):
            if not is_super(uid):
                return send(chat, '🔒 Faqat Super Admin')
            return settings_menu(c, key)
        if key == 'payment':
            admin_flow[uid] = 'payment'
            return send(chat, '🟡 To‘lov yo‘riqnomasining yangi matnini yuboring. (/cancel — bekor)')
        if key == 'backup':
            if not is_super(uid):
                return send(chat, '🔒 Faqat Super Admin')
            path = db_backup()
            try:
                with open(path, 'rb') as f:
                    bot.send_document(chat, f, caption='💾 Backup yaratildi')
            except Exception:
                send(chat, '💾 Backup yaratildi: ' + esc(path))
            return
        if key == 'admins':
            if not is_super(uid):
                return send(chat, '🔒 Faqat Super Admin')
            ids = db_admins()
            k = InlineKeyboardMarkup()
            k.add(InlineKeyboardButton('➕ Admin qo‘shish', callback_data='admin:add'))
            k.add(InlineKeyboardButton('➖ Admin o‘chirish', callback_data='admin:remove'))
            k.add(InlineKeyboardButton('⬅️ Panel', callback_data='admin'))
            return show(c, '👮 <b>Adminlar</b>\nSuper: <code>%s</code>\n%s' % (SUPER, '\n'.join(f'• <code>{i}</code>' for i in ids) or 'Qo‘shimcha adminlar yo‘q'), k)

    if d in ('admin:add', 'admin:remove'):
        if not is_super(uid):
            return send(chat, '🔒 Faqat Super Admin')
        admin_flow[uid] = d.split(':')[1]
        return send(chat, 'Admin Telegram ID raqamini yuboring. (/cancel — bekor)')

    if d == 'product:add':
        if not is_admin(uid):
            return
        admin_flow[uid] = 'new_product'
        return send(chat, 'Format (| bilan ajrating):\n<code>category|name|price|duration|emoji|description|command</code>\n'
                          'category: rank / token / title\nMisol:\n<code>rank|VIP|20000|30|⭐|VIP rank|lp user {player} parent set vip</code>')

    if d.startswith('edit:'):
        if not is_admin(uid):
            return
        p = db_product(int(d.split(':')[1]))
        if not p:
            return send(chat, 'Mahsulot topilmadi.')
        k = InlineKeyboardMarkup(row_width=2)
        for field, label in [('name', '📝 Nom'), ('price', '💰 Narx'), ('duration', '⏳ Muddat'), ('description', '📄 Tavsif'), ('emoji', '✨ Emoji'), ('command', '⚙️ RCON command')]:
            k.add(InlineKeyboardButton(label, callback_data=f'field:{p["id"]}:{field}'))
        k.add(InlineKeyboardButton('🗑 O‘chirish', callback_data=f'del:{p["id"]}'), InlineKeyboardButton('⬅️', callback_data='a:products'))
        return show(c, f'🛠 <b>{esc(p["name"])}</b> — tahrirlash\nNarx: {p["price"]:,}\nMuddat: {p["duration"]}\nCommand: <code>{esc(p["command"])}</code>', k)

    if d.startswith('field:'):
        if not is_admin(uid):
            return
        _, pid, field = d.split(':')
        admin_flow[uid] = f'field|{pid}|{field}'
        return send(chat, '🟡 Yangi qiymatni yuboring. (Command uchun {player} ishlatiladi.) /cancel — bekor')

    if d.startswith('del:'):
        if not is_admin(uid):
            return
        pid = int(d.split(':')[1])
        db_delete_product(pid)
        db_audit(uid, 'product_delete', pid)
        return show(c, '🗑 Mahsulot yashirildi.', back('a:products', '⬅️ Mahsulotlar'))

    if d.startswith('approve:'):
        if not is_admin(uid):
            return
        oid = int(d.split(':')[1])
        if not db_approve_once(oid):
            finish_buttons(c)
            return send(chat, '⚠️ Buyurtma allaqachon qayta ishlangan.')
        db_audit(uid, 'order_approve', oid)
        enqueue(oid)
        finish_buttons(c)
        return send(chat, f'🟢 #{oid} tasdiqlandi va navbatga qo‘shildi.')

    if d.startswith('retry:'):
        if not is_admin(uid):
            return
        oid = int(d.split(':')[1])
        if not db_retry_failed(oid):
            finish_buttons(c)
            return send(chat, '⚠️ Bu buyurtma FAILED holatida emas.')
        db_audit(uid, 'order_retry', oid)
        enqueue(oid)
        finish_buttons(c)
        return send(chat, f'🔁 #{oid} qayta navbatga qo‘shildi.')

    if d.startswith('reject:'):
        if not is_admin(uid):
            return
        oid = int(d.split(':')[1])
        o = db_get_order(oid)
        if not o or not db_reject_order(oid):
            finish_buttons(c)
            return send(chat, '⚠️ Status o‘zgargan.')
        db_audit(uid, 'order_reject', oid)
        try:
            bot.send_message(o['user_id'], f'🔴 Buyurtma #{oid} rad etildi. Savol bo‘lsa admin bilan bog‘laning.')
        except Exception:
            pass
        finish_buttons(c)
        return send(chat, f'🔴 #{oid} rad etildi.')

    if d.startswith('rcpt:'):
        if not is_admin(uid):
            return
        o = db_get_order(int(d.split(':')[1]))
        if not o or not o['receipt_file_id']:
            return send(chat, 'Chek topilmadi.')
        try:
            if o['receipt_kind'] == 'document':
                return bot.send_document(chat, o['receipt_file_id'], caption=f'🧾 Chek #{o["id"]}')
            return bot.send_photo(chat, o['receipt_file_id'], caption=f'🧾 Chek #{o["id"]}')
        except Exception:
            return send(chat, 'Chekni yuborib bo‘lmadi.')

    if d.startswith('set:'):
        if not is_super(uid):
            return
        key = d.split(':')[1]
        admin_flow[uid] = 'setting:' + key
        return send(chat, 'Yangi qiymatni yuboring.' + (' Parol xabaringiz xavfsizlik uchun o‘chiriladi.' if key == 'rcon_password' else '') + '\n/cancel — bekor')


# ===================== ADMIN EKRANLAR =====================
def admin_products(c):
    k = InlineKeyboardMarkup(row_width=1)
    for p in db_products():
        k.add(InlineKeyboardButton(f'{p["emoji"]} {p["name"]} • {p["price"]:,}', callback_data=f'edit:{p["id"]}'))
    k.add(InlineKeyboardButton('➕ Yangi mahsulot', callback_data='product:add'))
    k.add(InlineKeyboardButton('⬅️ Panel', callback_data='admin'))
    show(c, '📦 <b>Mahsulotlar</b>', k)


def admin_orders(chat):
    rows = db_list_orders(limit=20, statuses=OPEN_STATUSES)
    if not rows:
        return send(chat, '📥 Ochiq buyurtmalar yo‘q.', back('admin', '⬅️ Panel'))
    for o in rows:
        k = InlineKeyboardMarkup()
        if o['status'] in ('PENDING', 'PAYMENT_REVIEW'):
            k.add(InlineKeyboardButton('🟢 Tasdiqlash', callback_data=f'approve:{o["id"]}'), InlineKeyboardButton('🔴 Rad', callback_data=f'reject:{o["id"]}'))
        elif o['status'] == 'FAILED':
            k.add(InlineKeyboardButton('🔁 Qayta urinish', callback_data=f'retry:{o["id"]}'), InlineKeyboardButton('🔴 Rad', callback_data=f'reject:{o["id"]}'))
        if o['receipt_file_id']:
            k.add(InlineKeyboardButton('🧾 Chekni ko‘rish', callback_data=f'rcpt:{o["id"]}'))
        text = (f'#{o["id"]} {esc(o["product_name"])} — {o["price"]:,} UZS\n🎮 Nick: {esc(o["player"])}\n'
                f'👤 User: <code>{o["user_id"]}</code>\nStatus: {STATUS_UZ.get(o["status"], o["status"])}')
        if o['error']:
            text += f'\n⚠️ {esc(o["error"])}'
        send(chat, text, k)


def settings_menu(c, kind):
    if kind == 'server':
        labels = [('server_name', 'Server nomi'), ('server_host', 'Server IP'), ('server_port', 'Port'),
                  ('server_version', 'Minecraft versiyasi'), ('server_description', 'Tavsif'), ('support', 'Support kontakt')]
    else:
        labels = [('rcon_host', 'RCON host'), ('rcon_port', 'RCON port'), ('rcon_enabled', 'RCON enabled true/false'), ('rcon_password', 'RCON password')]
    k = InlineKeyboardMarkup(row_width=1)
    for key, label in labels:
        if key == 'rcon_password':
            shown = '••••••••' if (db_setting(key) or RCON_PASSWORD) else '(sozlanmagan)'
        else:
            shown = db_setting(key)
        k.add(InlineKeyboardButton(f'🟡 {label}: {shown[:30]}', callback_data=f'set:{key}'))
    if kind == 'rcon':
        k.add(InlineKeyboardButton('🔵 RCON test: list', callback_data='rcontest'))
    k.add(InlineKeyboardButton('⬅️ Panel', callback_data='admin'))
    show(c, '⚙️ Sozlamalar', k)


# ===================== CHEK (RASM / FAYL) =====================
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
    caption = (f'🧾 Chek • order #{oid}\n{esc(o["product_name"])} — {o["price"]:,} UZS\n🎮 {esc(o["player"])}\n'
               f'👤 {esc(m.from_user.first_name)} (<code>{uid}</code>)')
    for aid in admin_ids():
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton('🟢 Tasdiqlash', callback_data=f'approve:{oid}'),
                                        InlineKeyboardButton('🔴 Rad', callback_data=f'reject:{oid}'))
        try:
            if kind == 'document':
                bot.send_document(aid, file_id, caption=caption, reply_markup=kb)
            else:
                bot.send_photo(aid, file_id, caption=caption, reply_markup=kb)
        except Exception:
            log.warning('Adminga chek yuborilmadi: %s', aid)
    send(m.chat.id, f'🟢 Chek qabul qilindi. #{oid} admin tekshiruviga yuborildi.', back())


@bot.message_handler(content_types=['photo'], chat_types=['private'])
def photo(m):
    db_user(m.from_user)
    accept_receipt(m, m.photo[-1].file_id, 'photo')


@bot.message_handler(content_types=['document'], chat_types=['private'])
def document(m):
    mime = (m.document.mime_type or '')
    if not (mime.startswith('image/') or mime == 'application/pdf'):
        return send(m.chat.id, 'Chekni rasm (screenshot) yoki PDF ko‘rinishida yuboring.')
    db_user(m.from_user)
    accept_receipt(m, m.document.file_id, 'document')


# ===================== MATN =====================
@bot.message_handler(func=lambda m: True, content_types=['text'], chat_types=['private'])
def text_handler(m):
    uid = m.from_user.id
    txt = (m.text or '').strip()
    db_user(m.from_user)

    if uid in admin_flow:
        action = admin_flow.pop(uid)
        return handle_admin_text(m, uid, action, txt)

    if uid in buying:
        pid = buying.pop(uid)
        try:
            nick = clean_nick(txt)
        except ValueError as e:
            buying[uid] = pid
            return send(m.chat.id, '🔴 ' + str(e))
        p = db_product(pid)
        if not p:
            return send(m.chat.id, 'Mahsulot topilmadi.')
        oid = db_create_order(uid, p, nick)
        receipts[uid] = oid
        k = InlineKeyboardMarkup().add(InlineKeyboardButton(f'❌ Bekor #{oid}', callback_data=f'uc:{oid}'))
        return send(m.chat.id, f'🧾 <b>BUYURTMA #{oid}</b>\n{esc(p["emoji"])} {esc(p["name"])}\n💰 {p["price"]:,} UZS\n🎮 {esc(nick)}\n\n'
                               f'{esc(payment_instructions())}\n\nTo‘lovdan keyin chek screenshotini yuboring.', k)

    if txt.startswith('/'):
        return send(m.chat.id, '🟠 Buyruq topilmadi. /start')
    send(m.chat.id, 'Menyu: /start')


def handle_admin_text(m, uid, action, txt):
    chat = m.chat.id
    if action == 'payment':
        if not is_admin(uid):
            return
        db_set_setting('payment_text', txt)
        db_audit(uid, 'payment_text_update')
        return send(chat, '🟢 To‘lov matni saqlandi.', back('admin', '⬅️ Panel'))

    if action in ('add', 'remove'):
        if not is_super(uid):
            return send(chat, '🔒 Faqat Super Admin')
        try:
            target = int(txt)
        except ValueError:
            return send(chat, '🔴 Faqat ID raqam yuboring.')
        if action == 'add':
            db_admin_add(target, uid)
            db_audit(uid, 'admin_add', target)
            return send(chat, '🟢 Admin qo‘shildi.')
        if target == SUPER:
            return send(chat, 'Super Admin o‘chirilmaydi.')
        db_admin_remove(target)
        db_audit(uid, 'admin_remove', target)
        return send(chat, '🔴 Admin olib tashlandi.')

    if action.startswith('field|'):
        if not is_admin(uid):
            return
        _, pid, field = action.split('|')
        try:
            if field in ('price', 'duration'):
                value = int(txt)
                if value < 0:
                    raise ValueError()
            else:
                value = txt
                if not value:
                    raise ValueError()
            if field == 'command' and (len(value) > 500 or '\n' in value or '\r' in value):
                raise ValueError()
            db_save_product(int(pid), field, value)
            db_audit(uid, 'product_edit', f'{pid}:{field}')
        except ValueError:
            return send(chat, '🔴 Qiymat xato. Mahsulotni qaytadan tanlab urinib ko‘ring.')
        warn = ''
        if field == 'command' and '{player}' not in value:
            warn = '\n⚠️ Diqqat: buyruqda {player} yo‘q — o‘yinchi nickname almashtirilmaydi.'
        return send(chat, '🟢 Saqlandi.' + warn, back('a:products', '⬅️ Mahsulotlar'))

    if action == 'new_product':
        if not is_admin(uid):
            return
        parts = txt.split('|', 6)
        if len(parts) != 7 or parts[0].strip() not in ('rank', 'token', 'title'):
            return send(chat, '🔴 Format xato. category|name|price|duration|emoji|description|command (category: rank/token/title)')
        try:
            price, duration = int(parts[2]), int(parts[3])
            assert price >= 0 and duration >= 0
        except (ValueError, AssertionError):
            return send(chat, '🔴 Narx/muddat raqam bo‘lsin.')
        cmd = parts[6].strip()
        if len(cmd) > 500 or '\n' in cmd:
            return send(chat, '🔴 Command noto‘g‘ri.')
        db_add_product(parts[0].strip(), parts[1].strip(), price, duration, parts[5].strip(), parts[4].strip() or '🎁', cmd)
        db_audit(uid, 'product_add', parts[1])
        warn = '\n⚠️ Buyruqda {player} yo‘q.' if '{player}' not in cmd else ''
        return send(chat, '🟢 Mahsulot qo‘shildi.' + warn, back('a:products', '⬅️ Mahsulotlar'))

    if action.startswith('setting:'):
        if not is_super(uid):
            return
        key = action.split(':', 1)[1]
        if key in ('server_port', 'rcon_port'):
            try:
                v = int(txt)
                assert 1 <= v <= 65535
            except (ValueError, AssertionError):
                return send(chat, '🔴 Port 1–65535 oralig‘ida bo‘lsin.')
        elif key == 'rcon_enabled':
            v = txt.lower()
            if v not in ('true', 'false'):
                return send(chat, '🔴 true yoki false yuboring.')
        else:
            v = txt
        db_set_setting(key, v)
        db_audit(uid, 'setting_update', key)
        if key == 'rcon_password':  # parolni chatdan o'chiramiz
            try:
                bot.delete_message(chat, m.message_id)
            except Exception:
                pass
        return send(chat, '🟢 Sozlama saqlandi.', back('admin', '⬅️ Panel'))


def main():
    start_worker(bot)
    log.info('DARKZONA Donate Bot V3.1 started')
    bot.infinity_polling(skip_pending=False, timeout=30, long_polling_timeout=30)


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
💎 Virtual Bozor — Telegram o'yin boti (aiogram 3.27+)
Virtual coinlar bilan savdo o'yini. Hamma balans va foyda faqat o'yin ichida.

Ishga tushirish: quyidagi ikki qatorni (BOT_TOKEN, ADMIN_ID) to'ldiring va faylni ishga tushiring.
Hosting muhit o'zgaruvchilarini bermasa ham ishlaydi.

Premium emoji: bot egasida Telegram Premium bo'lishi kerak (Bot API 9.4).
Admin panel → 🎨 Premium emoji bo'limidan har bir emojini almashtirasiz.
"""
import asyncio
import copy
import csv
import hashlib
import io
import logging
import os
import platform
import random
import re
import secrets
import sqlite3
import sys
import time
from collections import deque
from datetime import datetime
from html import escape as esc
from urllib.parse import quote

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError as TelegramForbidden, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery,
                           InlineKeyboardButton, InlineKeyboardMarkup,
                           LabeledPrice, Message, PreCheckoutQuery)

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # Pillow bo'lmasa grafik o'chadi, bot ishlayveradi
    Image = None

# ───────────────────────── SOZLAMALAR ─────────────────────────
# ╔══════════════ SHU YERNI TO'LDIRING ══════════════╗
BOT_TOKEN = "9082119671:AAFuN0EVlR41Fj-Y4pZ7M5CF2m2P-WVPqCE"     # @BotFather bergan token, masalan "123456:ABC-DEF..."
ADMIN_ID = 8681116778       # sizning Telegram ID'ingiz (raqam). @userinfobot dan bilib oling
# ╚═══════════════════════════════════════════════════╝
TOKEN = (os.getenv("BOT_TOKEN") or BOT_TOKEN).strip()
_aid = int(os.getenv("ADMIN_ID") or ADMIN_ID or 0)
OWNERS = {_aid} if _aid else {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
DB_PATH = os.getenv("DB_PATH", "bozor.db")
TICK = 5                 # narx yangilanishi (soniya)
LIVE_TTL = 90            # ekran qancha vaqt jonli yangilanadi (soniya)
BCAST_EVERY = 3600       # narx xabarnomasi (soniya)
START_TS = time.time()

DEF = {  # admin panelidan o'zgartiriladi
    "start_balance": "1000", "ref_bonus": "10", "daily_bonus": "100",
    "liquidity": "50000", "vol": "1", "support": "", "bcast_on": "1",
    "maintenance": "0", "news_push": "1", "btn_color": "1", "extra_admins": "",
    "quest1": "50", "quest2": "30", "quest3": "20", "news_every": "25",
}
SHOP = [  # (kalit, nomi, narxi)
    ("trader", "🥉 Treyder", 5000),
    ("pro", "🥈 Pro", 25000),
    ("whale", "🐳 Kit", 100000),
    ("legend", "👑 Afsona", 500000),
]
BETS = [10, 50, 100, 500]
DEPOSITS = [(12, 2), (24, 5), (72, 18)]   # (soat, foiz)
WHEEL = [(10, 35), (25, 25), (50, 18), (100, 12), (250, 6), (500, 3), (1000, 1)]  # (summa, vazn)
VIEWS = {  # custom menyu tugmalari uchun ichki ekranlar
    "market": "📊 Bozor", "port": "💼 Portfel", "prices": "📈 Narxlar", "top": "🏆 Reyting",
    "games": "🎮 O'yinlar", "rewards": "🎁 Bonuslar", "ref": "👥 Referal", "pay": "⭐ To'ldirish",
    "shop": "🛍 Do'kon", "me": "👤 Profil", "news": "📰 Yangiliklar", "alerts": "🔔 Ogohlantirish",
    "quests": "📋 Vazifalar", "orders": "🎯 Avto-buyurtma", "tour": "🏁 Turnir", "deposit": "🏦 Omonat", "wheel": "🎰 G'ildirak", "help": "ℹ️ Yordam", "ach": "🏅 Yutuqlar",
}


class LogBuf(logging.Handler):
    """Oxirgi loglar admin panelda ko'rinishi uchun xotirada saqlanadi."""
    buf = deque(maxlen=300)

    def emit(self, rec):
        try:
            self.buf.append(self.format(rec))
        except Exception:
            pass


log = logging.getLogger("bozor")
bot: Bot = None  # main() da yaratiladi
BOT_USERNAME = ""

# ───────────────────────── BAZA ─────────────────────────
def _open_db(path):
    con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS _probe(x)")   # yozish mumkinligini tekshiradi
    return con


try:
    db = _open_db(DB_PATH)
except sqlite3.Error:   # hosting papkasi faqat o'qish uchun bo'lsa
    import tempfile
    DB_PATH = os.path.join(tempfile.gettempdir(), "bozor.db")
    print(f"⚠️ Baza joyi yozilmaydi, vaqtinchalik joy ishlatiladi: {DB_PATH}", flush=True)
    db = _open_db(DB_PATH)
try:
    db.execute("PRAGMA journal_mode=WAL")
except sqlite3.Error:
    pass
db.executescript("""
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, name TEXT, name_lc TEXT UNIQUE, tg_username TEXT,
 salt TEXT, pin TEXT, cash REAL, base REAL, logged_in INTEGER DEFAULT 1,
 banned INTEGER DEFAULT 0, notif INTEGER DEFAULT 1, ref_by INTEGER,
 ref_count INTEGER DEFAULT 0, ref_earned REAL DEFAULT 0, title TEXT DEFAULT '',
 donated INTEGER DEFAULT 0, streak INTEGER DEFAULT 0, last_daily REAL DEFAULT 0,
 fails INTEGER DEFAULT 0, lock_until REAL DEFAULT 0, created REAL, trades INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS coins(
 id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT UNIQUE, name TEXT, emoji TEXT,
 price REAL, base REAL, vol REAL DEFAULT 1, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS holdings(uid INTEGER, cid INTEGER, qty INTEGER, cost REAL, PRIMARY KEY(uid,cid));
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, cid INTEGER, side TEXT, qty INTEGER, price REAL, ts REAL);
CREATE TABLE IF NOT EXISTS hist(cid INTEGER, ts REAL, price REAL);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, stars INTEGER, amount REAL, charge TEXT UNIQUE, ts REAL, refunded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS packages(id INTEGER PRIMARY KEY AUTOINCREMENT, stars INTEGER, amount REAL);
CREATE TABLE IF NOT EXISTS preds(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, cid INTEGER, dir TEXT, bet REAL, p0 REAL, due REAL);
CREATE TABLE IF NOT EXISTS emojis(ch TEXT PRIMARY KEY, eid TEXT);
CREATE TABLE IF NOT EXISTS texts(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS menus(
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, text TEXT DEFAULT '', photo TEXT DEFAULT '',
 color TEXT DEFAULT 'primary', in_main INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS mbtns(
 id INTEGER PRIMARY KEY AUTOINCREMENT, menu_id INTEGER, label TEXT, kind TEXT, target TEXT,
 color TEXT DEFAULT 'primary', sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, cid INTEGER, target REAL, dir TEXT);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, cid INTEGER, pct REAL, text TEXT);
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, amount REAL, max_uses INTEGER, used INTEGER DEFAULT 0, expires REAL DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS promo_used(code TEXT, uid INTEGER, PRIMARY KEY(code,uid));
CREATE TABLE IF NOT EXISTS daily(uid INTEGER, day TEXT, trades INTEGER DEFAULT 0, games INTEGER DEFAULT 0, c1 INTEGER DEFAULT 0, c2 INTEGER DEFAULT 0, c3 INTEGER DEFAULT 0, PRIMARY KEY(uid,day));
CREATE TABLE IF NOT EXISTS plugins(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, code TEXT, prev_code TEXT DEFAULT '', enabled INTEGER DEFAULT 1, error TEXT DEFAULT '', updated REAL);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, cid INTEGER, kind TEXT, target REAL, created REAL);
CREATE TABLE IF NOT EXISTS tours(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, starts REAL, ends REAL, prizes TEXT, status TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS tour_players(tid INTEGER, uid INTEGER, p0 REAL, PRIMARY KEY(tid,uid));
CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, amount REAL, rate REAL, due REAL);
CREATE TABLE IF NOT EXISTS adminlog(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, admin INTEGER, action TEXT);
""")


def ensure_column(table, col, decl):
    if col not in [r["name"] for r in db.execute(f"PRAGMA table_info({table})")]:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


for _t, _c, _d in [("users", "last_seen", "REAL DEFAULT 0"), ("users", "spin_at", "REAL DEFAULT 0"),
                   ("users", "games", "INTEGER DEFAULT 0"), ("users", "wins", "INTEGER DEFAULT 0"),
                   ("payments", "refunded", "INTEGER DEFAULT 0"), ("tours", "result", "TEXT DEFAULT ''")]:
    ensure_column(_t, _c, _d)


def q(sql, *a):
    return db.execute(sql, a).fetchall()


def q1(sql, *a):
    return db.execute(sql, a).fetchone()


def ex(sql, *a):
    return db.execute(sql, a)


class tx:
    """Atomik tranzaksiya: with tx(): ..."""
    def __enter__(self):
        db.execute("BEGIN IMMEDIATE")

    def __exit__(self, et, ev, tb):
        db.execute("COMMIT" if et is None else "ROLLBACK")


if not q1("SELECT 1 FROM coins"):
    for sym, name, emo, p, v in [("NOVA", "NovaCoin", "🟣", 80, 1.0),
                                 ("BTC", "BitCoin", "🟠", 120, 0.7),
                                 ("FIT", "FitCoin", "🟢", 45, 1.3)]:
        ex("INSERT INTO coins(symbol,name,emoji,price,base,vol) VALUES(?,?,?,?,?,?)", sym, name, emo, p, p, v)
if not q1("SELECT 1 FROM packages"):
    for s, a in [(15, 5000), (50, 18000), (100, 40000)]:
        ex("INSERT INTO packages(stars,amount) VALUES(?,?)", s, a)


def cfg(k):
    r = q1("SELECT v FROM settings WHERE k=?", k)
    return r["v"] if r else DEF[k]


def cfgf(k):
    try:
        return float(cfg(k))
    except ValueError:
        return float(DEF[k])


def set_cfg(k, v):
    ex("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", k, str(v))


def get_user(uid):
    return q1("SELECT * FROM users WHERE id=?", uid)


def is_owner(uid):
    return uid in OWNERS


def admin_ids():
    return set(OWNERS)   # bitta admin (ADMIN_ID)


def is_admin(uid):
    return uid in admin_ids()


def alog(admin, action):
    ex("INSERT INTO adminlog(ts,admin,action) VALUES(?,?,?)", time.time(), admin, action[:300])
# ───────────────────────── FORMAT ─────────────────────────
def m(x):
    s, x = ("-" if x < 0 else ""), abs(x)
    if x >= 1e9:
        return f"{s}${x / 1e9:.2f}B"
    if x >= 1e6:
        return f"{s}${x / 1e6:.2f}M"
    if x >= 1e5:
        return f"{s}${x / 1e3:.1f}K"
    return f"{s}${x:,.2f}"


def pc(x):
    if abs(x) < 0.005:
        return "▬ 0.00%"
    return f"{'▲' if x > 0 else '▼'} {x:+.2f}%"


def sg(x):
    return ("🟢 +" if x >= 0 else "🔴 -") + m(abs(x))


def tag(u):
    return ((u["title"] + " ") if u["title"] else "") + ("💎 " if u["donated"] else "")


def clock():
    return datetime.now().strftime("%H:%M:%S")


CD = {}


def cooldown(uid, key, sec):
    """0 qaytarsa — mumkin; aks holda qolgan soniya."""
    t = time.time()
    left = CD.get((uid, key), 0) + sec - t
    if left > 0:
        return left
    CD[(uid, key)] = t
    return 0




# ───────────────────────── TAHRIRLANADIGAN MATNLAR ─────────────────────────
TEXTS = {
    "welcome": ("Boshlang'ich ekran ({start}, {bonus})",
                "💎 <b>Virtual Bozor</b>\n━━━━━━━━━━━━━━\n"
                "Coinlar bilan savdo qiling, narxlarni kuzating va reytingda birinchi bo'ling!\n\n"
                "🎁 Ro'yxatdan o'tsangiz <b>{start}</b> start balans beriladi.\n"
                "👥 Do'stingiz taklif qilgan bo'lsa — qo'shimcha bonus.\n\n"
                "<i>Bu virtual savdo o'yini: balans va daromad faqat o'yin ichida hisoblanadi.</i>"),
    "menu_head": ("Asosiy menyu sarlavhasi", "💎 <b>Virtual Bozor</b>"),
    "pay_intro": ("To'lov bo'limi matni",
                  "Telegram Stars orqali o'yin balansini to'ldiring va loyihani qo'llab-quvvatlang. "
                  "Donat qilganlar reytingda <b>💎</b> belgisi oladi.\n\n"
                  "<i>Balans faqat o'yin ichida ishlatiladi, haqiqiy pulga almashtirilmaydi.</i>"),
    "ref_intro": ("Referal matni ({bonus})",
                  "Do'stingiz sizning havolangiz orqali ro'yxatdan o'tsa, <b>ikkalangizga ham {bonus}</b> beriladi!"),
    "help_text": ("Yordam / qo'llanma matni",
                  "ℹ️ <b>Qo'llanma</b>\n━━━━━━━━━━━━━━\n"
                  "📊 <b>Bozor</b> — coin sotib oling va soting. Narx talabga qarab o'zgaradi.\n"
                  "💼 <b>Portfel</b> — coinlaringiz va foyda/zarar.\n"
                  "🎁 <b>Bonuslar</b> — kunlik bonus, g'ildirak, vazifalar, promo-kod.\n"
                  "🔔 <b>Ogohlantirish</b> — narx kerakli darajaga yetganda xabar beramiz.\n"
                  "🏆 <b>Reyting</b> — eng ko'p daromad topganlar.\n\n"
                  "Bu o'yin virtual: pul va daromad haqiqiy emas."),
    "support_intro": ("Adminga murojaat matni",
                      "🆘 <b>Adminga murojaat</b>\nMuammoingizni bitta xabarda yozing — admin javob beradi."),
}
TXT_OVERRIDE = {}


def load_texts():
    TXT_OVERRIDE.clear()
    for r_ in q("SELECT k,v FROM texts"):
        TXT_OVERRIDE[r_["k"]] = r_["v"]


def T(key, **kw):
    v = TXT_OVERRIDE.get(key) or TEXTS[key][1]
    for k, val in kw.items():
        v = v.replace("{" + k + "}", str(val))
    return v


# ───────────────────────── PREMIUM EMOJI ─────────────────────────
UI_EMOJIS = ["💎", "📊", "💼", "📈", "📉", "🏆", "🎮", "🎁", "👥", "⭐", "🛍", "👤", "🟢", "🔴", "🔵", "💵", "💰",
             "🔥", "🎲", "🪙", "🔮", "✅", "⚠️", "🚀", "🔑", "🔐", "🥇", "🥈", "🥉", "📦", "🎰", "📋", "📰", "🔔",
             "ℹ️", "🆘", "🎉", "⏳", "🦅", "🔢", "🔄", "🕐", "🌟", "💸", "🏅", "📍", "📜", "🚪", "🟣", "🟠"]
EMO = {}          # oddiy emoji -> premium emoji id
EMO_RX = None
_TAG = re.compile(r"(<[^>]*>)")


def load_emojis():
    global EMO_RX
    EMO.clear()
    for r_ in q("SELECT ch,eid FROM emojis"):
        EMO[r_["ch"]] = r_["eid"]
    EMO_RX = re.compile("|".join(re.escape(k) for k in sorted(EMO, key=len, reverse=True))) if EMO else None


def set_emoji(ch, eid):
    ex("INSERT INTO emojis(ch,eid) VALUES(?,?) ON CONFLICT(ch) DO UPDATE SET eid=excluded.eid", ch, eid)
    load_emojis()


def del_emoji(ch):
    ex("DELETE FROM emojis WHERE ch=?", ch)
    load_emojis()


def px(text):
    """Matndagi oddiy emojilarni premium emojiga almashtiradi (HTML)."""
    if not EMO_RX or not text:
        return text
    out, skip = [], 0
    for part in _TAG.split(text):
        if part.startswith("<") and part.endswith(">"):
            low = part.lower()
            if low.startswith(("<tg-emoji", "<code", "<pre")):
                skip += 1
            elif low.startswith(("</tg-emoji", "</code", "</pre")):
                skip = max(0, skip - 1)
            out.append(part)
        elif skip:
            out.append(part)
        else:
            out.append(EMO_RX.sub(lambda mo: f'<tg-emoji emoji-id="{EMO[mo.group(0)]}">{mo.group(0)}</tg-emoji>', part))
    return "".join(out)


def auto_style(text, cb):
    t, cb = (text or "").strip(), cb or ""
    if t.startswith(("⬅", "🔄")):
        return None
    if t.startswith(("✖", "🚫", "🗑", "🚪", "🔴")) or cb.startswith(("x:s", "logout", "adm:ban", "adm:pkdel", "ad:")):
        return "danger"
    if t.startswith(("🟢", "✅")) or cb.startswith(("x:b", "claim", "buy:", "reg:go", "login:go", "spin", "sb:", "qc:", "ac:", "pr:")):
        return "success"
    return "primary"


def _clone(btn, **upd):
    if hasattr(btn, "model_copy"):
        return btn.model_copy(update=upd)
    c = copy.copy(btn)
    c.__dict__.update(upd)
    return c


def decorate_markup(mk):
    """Tugmalarga rang (style) va premium emoji (icon_custom_emoji_id) qo'shadi."""
    color_on = cfg("btn_color") == "1"
    rows = []
    for row in mk.inline_keyboard:
        new = []
        for btn in row:
            upd = {}
            if color_on:
                st = getattr(btn, "style", None) or auto_style(btn.text, getattr(btn, "callback_data", None))
                if st:
                    upd["style"] = st
            if EMO_RX:
                mo = EMO_RX.match(btn.text or "")
                if mo and not getattr(btn, "icon_custom_emoji_id", None):
                    upd["icon_custom_emoji_id"] = EMO[mo.group(0)]
                    upd["text"] = (btn.text[mo.end():]).lstrip() or "·"
            new.append(_clone(btn, **upd) if upd else btn)
        rows.append(new)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plain_markup(mk):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=x.text, callback_data=x.callback_data, url=x.url) for x in row]
        for row in mk.inline_keyboard])


class PremiumMW(BaseRequestMiddleware):
    """Barcha chiquvchi xabarlarga premium emoji va tugma ranglarini qo'llaydi.
    Telegram rad etsa — oddiy ko'rinishda qayta yuboradi (bot to'xtamaydi)."""
    SEND = {"SendMessage", "EditMessageText", "SendPhoto", "EditMessageCaption", "SendDocument",
            "SendAnimation", "SendVideo"}

    async def __call__(self, make_request, bot, method):
        if type(method).__name__ not in self.SEND:
            return await make_request(bot, method)
        orig = {}
        for a in ("text", "caption"):
            v = getattr(method, a, None)
            if isinstance(v, str) and v:
                nv = px(v)
                if nv != v:
                    orig[a] = v
                    setattr(method, a, nv)
        mk = getattr(method, "reply_markup", None)
        if isinstance(mk, InlineKeyboardMarkup):
            orig["reply_markup"] = mk
            setattr(method, "reply_markup", decorate_markup(mk))
        if not orig:
            return await make_request(bot, method)
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as e:
            low = str(e).lower()
            if "not modified" in low or not any(w in low for w in ("entit", "emoji", "button", "style", "parse")):
                raise
            log.warning("Premium emoji/rang rad etildi, oddiy ko'rinishda yuboriladi: %s", e)
            for a, v in orig.items():
                setattr(method, a, plain_markup(v) if a == "reply_markup" else v)
            return await make_request(bot, method)
# ───────────────────────── NARX MEXANIZMI ─────────────────────────
COINS = {}   # cid -> dict (xotirada, asosiy manba)
H1 = {}      # cid -> deque[(ts, price)] — oxirgi 1 soat
MOM = {}     # cid -> momentum (trend)


def load_coins():
    now = time.time()
    for r in q("SELECT * FROM coins"):
        c = dict(r)
        COINS[c["id"]] = c
        rows = q("SELECT ts,price FROM hist WHERE cid=? AND ts>? ORDER BY ts", c["id"], now - 3600)
        H1[c["id"]] = deque([(r2["ts"], r2["price"]) for r2 in rows] or [(now, c["price"])], maxlen=720)
        MOM[c["id"]] = 0.0


def active_coins():
    return [c for c in COINS.values() if c["active"]]


def save_coin(c):
    ex("UPDATE coins SET symbol=?,name=?,emoji=?,price=?,base=?,vol=?,active=? WHERE id=?",
       c["symbol"], c["name"], c["emoji"], c["price"], c["base"], c["vol"], c["active"], c["id"])


def ch1h(c):
    first = H1[c["id"]][0][1]
    return (c["price"] / first - 1) * 100 if first else 0.0


def tick():
    vm, now = cfgf("vol"), time.time()
    for c in active_coins():
        cid = c["id"]
        MOM[cid] = MOM[cid] * 0.93 + random.gauss(0, 0.00015)
        shock = random.gauss(0, 0.0019 * vm * c["vol"]) + MOM[cid] * vm
        pull = (c["base"] - c["price"]) / c["base"] * 0.0008
        p = c["price"] * (1 + shock + pull)
        c["price"] = round(min(max(p, c["base"] * 0.25, 0.5), c["base"] * 4), 2)
        H1[cid].append((now, c["price"]))
    ex("BEGIN")
    for c in COINS.values():
        ex("UPDATE coins SET price=? WHERE id=?", c["price"], c["id"])
    ex("COMMIT")


def persist_hist():
    now = time.time()
    ex("BEGIN")
    for c in active_coins():
        ex("INSERT INTO hist(cid,ts,price) VALUES(?,?,?)", c["id"], now, c["price"])
    ex("DELETE FROM hist WHERE ts<?", now - 86400)
    ex("COMMIT")


def holdings_of(uid):
    return q("SELECT * FROM holdings WHERE uid=? AND qty>0 ORDER BY cid", uid)


def portfolio_value(uid):
    return sum(h["qty"] * COINS[h["cid"]]["price"] for h in holdings_of(uid) if h["cid"] in COINS)


def deposit_value(uid):
    return q1("SELECT COALESCE(SUM(amount),0) v FROM deposits WHERE uid=?", uid)["v"]


def net_worth(uid):
    u = get_user(uid)
    return u["cash"] + portfolio_value(uid) + deposit_value(uid)


def trade(uid, cid, side, qty):
    """side: 'b' yoki 's'. (ok, xabar) qaytaradi."""
    c = COINS.get(cid)
    if not c or qty < 1:
        return False, "Noto'g'ri so'rov"
    price = c["price"]
    total = round(price * qty, 2)
    with tx():
        u = get_user(uid)
        if side == "b":
            if not c["active"]:
                return False, "Bu coin hozir savdoda emas"
            if u["cash"] + 1e-9 < total:
                return False, "Mablag' yetarli emas"
            ex("UPDATE users SET cash=round(cash-?,2), trades=trades+1 WHERE id=?", total, uid)
            ex("INSERT INTO holdings(uid,cid,qty,cost) VALUES(?,?,?,?) "
               "ON CONFLICT(uid,cid) DO UPDATE SET qty=qty+excluded.qty, cost=cost+excluded.cost",
               uid, cid, qty, total)
            note = f"✅ {qty} ta {c['name']} olindi · {m(total)}"
        else:
            h = q1("SELECT * FROM holdings WHERE uid=? AND cid=?", uid, cid)
            if not h or h["qty"] < qty:
                return False, "Sizda bunchalik coin yo'q"
            used = h["cost"] / h["qty"] * qty
            ex("UPDATE holdings SET qty=qty-?, cost=cost-? WHERE uid=? AND cid=?", qty, used, uid, cid)
            ex("DELETE FROM holdings WHERE qty<=0")
            ex("UPDATE users SET cash=round(cash+?,2), trades=trades+1 WHERE id=?", total, uid)
            note = f"✅ {qty} ta {c['name']} sotildi · {m(total)} ({sg(total - used)})"
        ex("INSERT INTO trades(uid,cid,side,qty,price,ts) VALUES(?,?,?,?,?,?)", uid, cid, side, qty, price, time.time())
        bump(uid, "trades")
    # bozor ta'siri: sotib olinsa narx ko'tariladi, sotilsa tushadi
    imp = min(total / max(cfgf("liquidity"), 1), 0.08)
    c["price"] = round(max(price * (1 + imp if side == "b" else 1 - imp), 0.5), 2)
    H1[cid].append((time.time(), c["price"]))
    save_coin(c)
    return True, note




# ───────────────────────── QO'SHIMCHA FUNKSIYALAR (mantiq) ─────────────────────────
def today():
    return datetime.now().strftime("%Y-%m-%d")


def daily_row(uid):
    ex("INSERT OR IGNORE INTO daily(uid,day) VALUES(?,?)", uid, today())
    return q1("SELECT * FROM daily WHERE uid=? AND day=?", uid, today())


def bump(uid, field):
    """Kunlik vazifa hisoblagichi: field = 'trades' | 'games'."""
    if field in ("trades", "games"):
        daily_row(uid)
        ex(f"UPDATE daily SET {field}={field}+1 WHERE uid=? AND day=?", uid, today())


QUESTS = [  # (raqam, nomi, maydon, maqsad, sozlama kaliti)
    (1, "🔁 3 ta savdo qiling", "trades", 3, "quest1"),
    (2, "🎮 2 ta o'yin o'ynang", "games", 2, "quest2"),
    (3, "🎁 Kunlik bonusni oling", "daily", 1, "quest3"),
]


def quest_progress(uid, u=None):
    u = u or get_user(uid)
    d = daily_row(uid)
    got = 1 if datetime.fromtimestamp(u["last_daily"]).strftime("%Y-%m-%d") == today() and u["last_daily"] else 0
    return {"trades": d["trades"], "games": d["games"], "daily": got}, d


def claim_quest(uid, n):
    quest = next((x for x in QUESTS if x[0] == n), None)
    if not quest:
        return False, "Vazifa topilmadi"
    _, _, field, goal, key = quest
    prog, _ = quest_progress(uid)
    reward = cfgf(key)
    with tx():
        d = daily_row(uid)
        if d[f"c{n}"]:
            return False, "Bu mukofot allaqachon olingan"
        if prog[field] < goal:
            return False, "Vazifa hali bajarilmagan"
        ex(f"UPDATE daily SET c{n}=1 WHERE uid=? AND day=?", uid, today())
        ex("UPDATE users SET cash=round(cash+?,2), base=base+? WHERE id=?", reward, reward, uid)
    return True, f"🎉 +{m(reward)} mukofot olindi!"


def achievements(u):
    nw = net_worth(u["id"])
    return [("🎯", "Birinchi savdo", u["trades"] >= 1), ("⚡", "Faol treyder (50 savdo)", u["trades"] >= 50),
            ("💵", "$5 000 boylik", nw >= 5000), ("🏦", "$50 000 boylik", nw >= 50000),
            ("👥", "5 ta do'st taklif qilish", u["ref_count"] >= 5), ("💎", "Homiy", u["donated"] > 0),
            ("🔥", "7 kunlik seriya", u["streak"] >= 7), ("🍀", "10 ta o'yinda g'alaba", u["wins"] >= 10)]


POS_NEWS = ["{c} yangi hamkorlikni e'lon qildi", "{c} uchun talab keskin oshdi",
            "Yirik investor {c} sotib oldi", "{c} yangi cho'qqiga intilmoqda"]
NEG_NEWS = ["{c} bo'yicha yirik sotuvlar kuzatildi", "{c} investorlar e'tiborini yo'qotmoqda",
            "{c} tuzatish bosqichida", "Bozorda {c} bosim ostida"]


def make_event(cid=None, pct=None, custom=None):
    """Bozor voqeasi: narxni siltaydi va yangilik yozadi. (coin, pct, matn) qaytaradi."""
    c = COINS[cid] if cid else random.choice(active_coins())
    if pct is None:
        pct = random.choice([-1, 1]) * random.uniform(3, 9)
    c["price"] = round(min(max(c["price"] * (1 + pct / 100), c["base"] * 0.25, 0.5), c["base"] * 4), 2)
    H1[c["id"]].append((time.time(), c["price"]))
    save_coin(c)
    text = custom or random.choice(POS_NEWS if pct > 0 else NEG_NEWS).format(c=c["name"])
    ex("INSERT INTO news(ts,cid,pct,text) VALUES(?,?,?,?)", time.time(), c["id"], pct, text)
    ex("DELETE FROM news WHERE id<(SELECT MAX(id)-200 FROM news)")
    return c, pct, text


def news_text(c, pct, text):
    return (f"📰 <b>Yangilik</b>\n━━━━━━━━━━━━━━\n{c['emoji']} {esc(text)}\n\n"
            f"{esc(c['name'])}: <b>${c['price']:,.2f}</b>  {pc(pct)}")


def check_alerts():
    fired = []
    for a in q("SELECT * FROM alerts"):
        c = COINS.get(a["cid"])
        if not c:
            ex("DELETE FROM alerts WHERE id=?", a["id"])
        elif (a["dir"] == "u" and c["price"] >= a["target"]) or (a["dir"] == "d" and c["price"] <= a["target"]):
            ex("DELETE FROM alerts WHERE id=?", a["id"])
            fired.append((a, c))
    return fired


def redeem_promo(uid, code):
    code = (code or "").strip().upper()
    with tx():
        p = q1("SELECT * FROM promos WHERE code=?", code)
        if not p or not p["active"]:
            return False, "❌ Bunday promo-kod yo'q"
        if p["expires"] and p["expires"] < time.time():
            return False, "⌛ Promo-kod muddati tugagan"
        if p["max_uses"] and p["used"] >= p["max_uses"]:
            return False, "😕 Promo-kod limiti tugagan"
        if q1("SELECT 1 FROM promo_used WHERE code=? AND uid=?", code, uid):
            return False, "Siz bu kodni allaqachon ishlatgansiz"
        ex("INSERT INTO promo_used(code,uid) VALUES(?,?)", code, uid)
        ex("UPDATE promos SET used=used+1 WHERE code=?", code)
        ex("UPDATE users SET cash=round(cash+?,2), base=base+? WHERE id=?", p["amount"], p["amount"], uid)
    return True, f"🎉 Promo-kod qabul qilindi: +{m(p['amount'])}"


def spin_wheel(uid):
    """None — hali erta; aks holda yutuq summasi."""
    with tx():
        u = get_user(uid)
        if time.time() - u["spin_at"] < 86400:
            return None
        amt = random.choices([a for a, _ in WHEEL], [w for _, w in WHEEL])[0]
        ex("UPDATE users SET cash=round(cash+?,2), base=base+?, spin_at=? WHERE id=?", amt, amt, time.time(), uid)
    return amt


def seen(uid, _c={}):
    """Foydalanuvchi oxirgi faolligi (daqiqada bir marta yoziladi)."""
    now = time.time()
    if now - _c.get(uid, 0) > 60:
        _c[uid] = now
        ex("UPDATE users SET last_seen=? WHERE id=?", now, uid)


def make_order(uid, cid, kind, pct):
    """(ok, xabar). kind: tp | sl | bl."""
    c = COINS.get(cid)
    if not c or not c["active"] or kind not in ("tp", "sl", "bl") or not 0 < pct <= 50:
        return False, "Noto'g'ri buyurtma"
    if q1("SELECT COUNT(*) n FROM orders WHERE uid=?", uid)["n"] >= 5:
        return False, "Maksimum 5 ta buyurtma"
    if kind in ("tp", "sl") and not q1("SELECT 1 FROM holdings WHERE uid=? AND cid=? AND qty>0", uid, cid):
        return False, f"Avval {c['name']} sotib oling — sotish buyurtmasi uchun coin kerak"
    target = round(c["price"] * (1 + pct / 100 if kind == "tp" else 1 - pct / 100), 2)
    ex("INSERT INTO orders(uid,cid,kind,target,created) VALUES(?,?,?,?,?)", uid, cid, kind, target, time.time())
    return True, "✅ Avto-buyurtma qo'shildi"


def check_orders():
    """Narxi yetgan buyurtmalarni bajaradi: [(uid, matn)] qaytaradi."""
    done = []
    for o in q("SELECT * FROM orders"):
        c = COINS.get(o["cid"])
        if not c:
            ex("DELETE FROM orders WHERE id=?", o["id"])
            continue
        hit = (c["price"] >= o["target"]) if o["kind"] == "tp" else (c["price"] <= o["target"])
        if not hit:
            continue
        ex("DELETE FROM orders WHERE id=?", o["id"])
        if o["kind"] == "bl":
            qty = int(get_user(o["uid"])["cash"] * 0.25 // c["price"])
            ok, note = trade(o["uid"], o["cid"], "b", qty) if qty >= 1 else (False, "mablag' yetarli emas")
        else:
            h = q1("SELECT qty FROM holdings WHERE uid=? AND cid=? AND qty>0", o["uid"], o["cid"])
            ok, note = trade(o["uid"], o["cid"], "s", h["qty"]) if h else (False, "coin qolmagan")
            ex("DELETE FROM orders WHERE uid=? AND cid=? AND kind IN ('tp','sl')", o["uid"], o["cid"])  # qarama-qarshi buyurtma bekor
        title = {"tp": "🎯 Foyda buyurtmasi", "sl": "🛑 Zarar buyurtmasi", "bl": "🟢 Olish buyurtmasi"}[o["kind"]]
        done.append((o["uid"], f"{title} ishladi\n{note if ok else '⚠️ Bajarilmadi: ' + note}"))
    return done


# ── Turnir ──
def active_tour():
    return q1("SELECT * FROM tours WHERE status='active' AND ends>? ORDER BY id DESC LIMIT 1", time.time())


def tour_ranking(tid):
    out = []
    for pl in q("SELECT tp.uid, tp.p0, u.name, u.base FROM tour_players tp JOIN users u ON u.id=tp.uid WHERE tp.tid=? AND u.banned=0", tid):
        out.append((pl["name"], net_worth(pl["uid"]) - pl["base"] - pl["p0"], pl["uid"]))
    out.sort(key=lambda x: -x[1])
    return out


def join_tour(uid):
    t = active_tour()
    if not t:
        return False
    u = get_user(uid)
    ex("INSERT OR IGNORE INTO tour_players(tid,uid,p0) VALUES(?,?,?)", t["id"], uid, net_worth(uid) - u["base"])
    return True


def end_tours(force_id=None):
    """Muddati tugagan turnirlarni yakunlaydi. [(uid, xabar)] qaytaradi."""
    msgs = []
    for t in q("SELECT * FROM tours WHERE status='active' AND (ends<=? OR id=?)", time.time(), force_id or -1):
        rk = tour_ranking(t["id"])
        prizes = [float(x) for x in t["prizes"].split(",") if x]
        with tx():
            ex("UPDATE tours SET status='done', result=? WHERE id=?", ";".join(f"{n_.replace(';', ' ').replace(':', ' ')}:{sc:.2f}" for n_, sc, _ in rk[:3]), t["id"])
            for i, (_, _, uid) in enumerate(rk[:len(prizes)]):
                ex("UPDATE users SET cash=round(cash+?,2), base=base+? WHERE id=?", prizes[i], prizes[i], uid)
        for i, (_, sc, uid) in enumerate(rk):
            if i < len(prizes):
                msgs.append((uid, f"🏁 <b>{esc(t['name'])}</b> yakunlandi!\n🏆 Siz <b>#{i + 1}</b> o'rinni egalladingiz!\n🎁 Mukofot: <b>+{m(prizes[i])}</b>"))
            else:
                msgs.append((uid, f"🏁 <b>{esc(t['name'])}</b> yakunlandi.\nSizning o'rningiz: <b>#{i + 1}</b> ({sg(sc)}). Keyingi turnirda omad!"))
    return msgs


# ── Omonat ──
def make_deposit(uid, hours, amount):
    pct = dict(DEPOSITS).get(hours)
    if not pct or amount <= 0:
        return False, "Noto'g'ri omonat"
    with tx():
        if q1("SELECT COUNT(*) n FROM deposits WHERE uid=?", uid)["n"] >= 3:
            return False, "Maksimum 3 ta omonat"
        if get_user(uid)["cash"] < amount:
            return False, "Mablag' yetarli emas"
        ex("UPDATE users SET cash=round(cash-?,2) WHERE id=?", amount, uid)
        ex("INSERT INTO deposits(uid,amount,rate,due) VALUES(?,?,?,?)", uid, amount, pct, time.time() + hours * 3600)
    return True, f"✅ {m(amount)} omonatga qo'yildi (+{pct}%)"


def mature_deposits():
    msgs = []
    for d in q("SELECT * FROM deposits WHERE due<=?", time.time()):
        back = round(d["amount"] * (1 + d["rate"] / 100), 2)
        with tx():
            ex("DELETE FROM deposits WHERE id=?", d["id"])
            ex("UPDATE users SET cash=round(cash+?,2) WHERE id=?", back, d["uid"])
        msgs.append((d["uid"], f"🏦 <b>Omonat muddati tugadi!</b>\n{m(d['amount'])} → <b>{m(back)}</b> (+{m(back - d['amount'])})"))
    return msgs


# ───────────────────────── PLAGINLAR VA KOD YANGILASH (faqat bot egalari) ─────────────────────────
PLUG = Router(name="plugins")
PLUGINS = {}   # id -> {router, hooks, tick, fails}
PLUGIN_EXAMPLE = '''@router.message(Command("salom"))
async def salom(msg: Message):
    await msg.answer("Salom! 👋 Bu plagin orqali qo'shilgan buyruq.")

async def on_tick():      # ixtiyoriy: har 5 soniyada chaqiriladi
    pass
'''


def plugin_ns(name):
    rt = Router(name=f"plugin_{name}")
    hooks = []

    def add_view(vname, fn):
        """add_view('nom', lambda uid, arg, note: (matn, klaviatura)) — ekran qo'shadi yoki almashtiradi."""
        VIEW_HOOKS[vname] = fn
        hooks.append(vname)

    ns = dict(router=rt, bot=bot, add_view=add_view, q=q, q1=q1, ex=ex, tx=tx, m=m, pc=pc, sg=sg, esc=esc,
              b=b, ub=ub, kb=kb, view=view, view_builtin=lambda *a, **k: view(*a, hooks=False, **k), COINS=COINS,
              get_user=get_user, credit=credit, cfg=cfg, set_cfg=set_cfg, T=T, asyncio=asyncio, time=time,
              random=random, F=F, Command=Command, Message=Message, CallbackQuery=CallbackQuery,
              FSMContext=FSMContext, StatesGroup=StatesGroup, State=State, safe_send=safe_send, show=show,
              MENU_BTN=MENU_BTN, is_admin=is_admin, is_owner=is_owner, net_worth=net_worth, trade=trade,
              make_event=make_event, log=logging.getLogger(f"plugin.{name}"), __name__=f"plugin_{name}")
    return rt, hooks, ns


def unload_plugin(pid):
    pl = PLUGINS.pop(pid, None)
    if not pl:
        return
    for h in pl["hooks"]:
        VIEW_HOOKS.pop(h, None)
    try:
        PLUG.sub_routers.remove(pl["router"])
        pl["router"]._parent_router = None
    except Exception:
        log.exception("plagin routerini ajratib bo'lmadi")


def load_plugin(row):
    """(ok, xato_matni). Xato bo'lsa plagin o'chiriladi, bot ishlashda davom etadi."""
    import traceback
    unload_plugin(row["id"])
    rt, hooks, ns = plugin_ns(row["name"])
    try:
        exec(compile(row["code"], f"<plugin:{row['name']}>", "exec"), ns)
        if callable(ns.get("setup")):
            ns["setup"]()
        PLUG.include_router(rt)
    except BaseException as e:   # SystemExit ham plaginni yiqitmasin
        for h in hooks:
            VIEW_HOOKS.pop(h, None)
        tb = "".join(traceback.format_exception_only(type(e), e)).strip()[-500:]
        ex("UPDATE plugins SET enabled=0, error=? WHERE id=?", tb, row["id"])
        log.error("Plagin %s yuklanmadi: %s", row["name"], tb)
        return False, tb
    PLUGINS[row["id"]] = dict(router=rt, hooks=hooks, tick=ns.get("on_tick"), fails=0)
    ex("UPDATE plugins SET error='' WHERE id=?", row["id"])
    log.info("Plagin yuklandi: %s", row["name"])
    return True, ""


def check_code(code, name="plugin"):
    try:
        compile(code, name, "exec")
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (qator {e.lineno})"
    return ""


def save_plugin(name, code, pid=None):
    """Plaginni saqlaydi va yuklaydi. (ok, xabar, id)."""
    err = check_code(code, name)
    if err:
        return False, err, pid
    if pid:
        old = q1("SELECT code FROM plugins WHERE id=?", pid)
        ex("UPDATE plugins SET prev_code=?, code=?, enabled=1, updated=? WHERE id=?", old["code"], code, time.time(), pid)
    else:
        pid = ex("INSERT INTO plugins(name,code,updated) VALUES(?,?,?)", name, code, time.time()).lastrowid
    ok, e = load_plugin(q1("SELECT * FROM plugins WHERE id=?", pid))
    return ok, e, pid


def load_all_plugins():
    if os.getenv("SAFE_MODE") == "1":
        log.warning("SAFE_MODE: plaginlar yuklanmadi")
        return
    for row in q("SELECT * FROM plugins WHERE enabled=1"):
        load_plugin(row)


async def run_plugin_ticks():
    for pid, pl in list(PLUGINS.items()):
        fn = pl.get("tick")
        if not fn:
            continue
        try:
            res = fn()
            if asyncio.iscoroutine(res):
                await asyncio.wait_for(res, 10)
            pl["fails"] = 0
        except Exception:
            pl["fails"] += 1
            log.exception("plagin on_tick xatosi")
            if pl["fails"] >= 5:
                unload_plugin(pid)
                ex("UPDATE plugins SET enabled=0, error='on_tick 5 marta xato berdi' WHERE id=?", pid)


# ── main.py ni almashtirish ──
SELF = os.path.abspath(__file__)


def verify_new_main(path):
    """Yangi main.py ni alohida jarayonda import qilib ko'radi (bot ishga tushmaydi)."""
    import subprocess
    code = ("import importlib.util as u,sys;s=u.spec_from_file_location('m_check',sys.argv[1]);"
            "m=u.module_from_spec(s);s.loader.exec_module(m);assert hasattr(m,'main');print('OK')")
    try:
        res = subprocess.run([sys.executable, "-c", code, path], capture_output=True, text=True, timeout=40,
                             env={**os.environ, "DB_PATH": ":memory:"})
    except Exception as e:
        return f"Tekshirib bo'lmadi: {e}"
    return "" if res.returncode == 0 and "OK" in res.stdout else (res.stderr.strip().splitlines() or ["Noma'lum xato"])[-1][:300]


def restart_process():
    os.execv(sys.executable, [sys.executable] + sys.argv)
# ───────────────────────── TUGMALAR ─────────────────────────
def b(text, cb, style=None):
    """Callback tugma. style: primary | success | danger (ko'rsatilmasa — avtomatik)."""
    extra = {"style": style} if style in ("primary", "success", "danger") else {}
    return InlineKeyboardButton(text=text, callback_data=cb, **extra)


def ub(text, url, style=None):
    extra = {"style": style} if style in ("primary", "success", "danger") else {}
    return InlineKeyboardButton(text=text, url=url, **extra)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def support_btn():
    row = [b("🆘 Adminga murojaat", "v:support")]
    s = cfg("support").strip()
    if s:
        row.append(ub("✈️ Telegram", s if s.startswith("http") else "https://t.me/" + s.lstrip("@")))
    return row


MENU_BTN = [b("⬅ Menyu", "v:menu")]


# ───────────────────────── GRAFIK ─────────────────────────
def chart_png(c):
    if Image is None:
        return None
    pts = [p for _, p in H1[c["id"]]]
    if len(pts) < 2:
        pts = [c["price"], c["price"]]
    W, H, L, R, T, B = 640, 320, 70, 20, 50, 30
    img = Image.new("RGB", (W, H), (15, 19, 30))
    d = ImageDraw.Draw(img)
    try:
        f1, f2 = ImageFont.load_default(size=20), ImageFont.load_default(size=13)
    except Exception:
        f1 = f2 = ImageFont.load_default()
    lo, hi = min(pts), max(pts)
    if hi - lo < 0.02:
        lo, hi = lo - 0.5, hi + 0.5
    pad = (hi - lo) * 0.1
    lo, hi = lo - pad, hi + pad
    up = pts[-1] >= pts[0]
    col, fill = ((46, 204, 113), (20, 70, 50)) if up else ((231, 76, 60), (80, 30, 35))
    for i in range(5):
        y = T + (H - T - B) * i / 4
        d.line([(L, y), (W - R, y)], fill=(35, 42, 60))
        d.text((8, y - 7), f"{hi - (hi - lo) * i / 4:,.2f}", fill=(130, 140, 160), font=f2)
    n = len(pts)
    xy = [(L + (W - L - R) * i / (n - 1), T + (H - T - B) * (1 - (p - lo) / (hi - lo))) for i, p in enumerate(pts)]
    d.polygon(xy + [(xy[-1][0], H - B), (xy[0][0], H - B)], fill=fill)
    d.line(xy, fill=col, width=3)
    d.ellipse([xy[-1][0] - 5, xy[-1][1] - 5, xy[-1][0] + 5, xy[-1][1] + 5], fill=col)
    d.text((L, 14), f"{c['name']}  ${c['price']:,.2f}  ({ch1h(c):+.2f}%)", fill=(235, 240, 250), font=f1)
    d.text((L, H - 22), "Oxirgi 1 soat", fill=(130, 140, 160), font=f2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ───────────────────────── EKRANLAR ─────────────────────────
LIVE = {}              # uid -> {chat, mid, name, arg, exp, last}
LIVE_VIEWS = {"market", "prices", "port", "t"}
TOP_CACHE = {"ts": 0, "rows": []}


def coin_lines(with_hold=None):
    out = []
    for c in active_coins():
        line = f"{c['emoji']} <b>{esc(c['name'])}</b>\n      <code>${c['price']:,.2f}</code>   {pc(ch1h(c))}"
        out.append(line)
    return "\n\n".join(out) or "Hozircha coin yo'q"


def leaderboard():
    if time.time() - TOP_CACHE["ts"] < 10:
        return TOP_CACHE["rows"]
    hold = {}
    for h in q("SELECT uid,cid,qty FROM holdings WHERE qty>0"):
        if h["cid"] in COINS:
            hold[h["uid"]] = hold.get(h["uid"], 0) + h["qty"] * COINS[h["cid"]]["price"]
    rows = []
    for d_ in q("SELECT uid, SUM(amount) v FROM deposits GROUP BY uid"):
        hold[d_["uid"]] = hold.get(d_["uid"], 0) + d_["v"]
    for u in q("SELECT * FROM users WHERE banned=0"):
        rows.append((u["cash"] + hold.get(u["id"], 0) - u["base"], u))
    rows.sort(key=lambda x: -x[0])
    TOP_CACHE.update(ts=time.time(), rows=rows)
    return rows


VIEW_HOOKS = {}   # plaginlar ekranlarni almashtirishi yoki yangi ekran qo'shishi uchun


def view(uid, name, arg="", note="", hooks=True):
    """Har bir ekran: (matn, klaviatura)."""
    if hooks and name in VIEW_HOOKS:
        try:
            return VIEW_HOOKS[name](uid, arg, note)
        except Exception:
            log.exception("plagin ekrani xatosi: %s", name)
    u = get_user(uid)
    foot = f"\n\n{note}" if note else ""

    if name == "menu":
        pv, dv = portfolio_value(uid), deposit_value(uid)
        profit = u["cash"] + pv + dv - u["base"]
        text = (f"{T('menu_head')}\n━━━━━━━━━━━━━━\n"
                f"👤 {tag(u)}<b>{esc(u['name'])}</b>\n\n"
                f"💵 Hamyon: <b>{m(u['cash'])}</b>\n"
                f"📦 Coinlar: <b>{m(pv)}</b>\n"
                + (f"🏦 Omonat: <b>{m(dv)}</b>\n" if dv else "") +
                f"💰 Jami: <b>{m(u['cash'] + pv + dv)}</b>\n"
                f"📊 Daromad: {sg(profit)}{foot}")
        rows = [[b("📊 Bozor", "v:market"), b("💼 Portfel", "v:port")],
                [b("📈 Narxlar", "v:prices"), b("🏆 Reyting", "v:top")],
                [b("🎮 O'yinlar", "v:games"), b("🎁 Bonuslar", "v:rewards")],
                [b("📰 Yangiliklar", "v:news"), b("🔔 Ogohlantirish", "v:alerts")],
                [b("👥 Do'st taklif qilish (+$%g)" % cfgf("ref_bonus"), "v:ref")],
                [b("⭐ Hisobni to'ldirish", "v:pay"), b("🛍 Do'kon", "v:shop")]]
        custom = q("SELECT * FROM menus WHERE active=1 AND in_main=1 ORDER BY sort,id")
        for i in range(0, len(custom), 2):
            rows.append([b(mn["title"], f"m:{mn['id']}", mn["color"]) for mn in custom[i:i + 2]])
        rows.append([b("👤 Profil", "v:me"), b("ℹ️ Yordam", "v:help")])
        return text, kb(*rows)

    if name == "prices":
        text = (f"📈 <b>Narxlar</b>\n━━━━━━━━━━━━━━\n{coin_lines()}\n\n"
                f"<i>🔄 har {TICK} soniyada yangilanadi · {clock()}</i>{foot}")
        coins = [b(f"{c['emoji']} {c['symbol']} grafik", f"c:{c['id']}") for c in active_coins()]
        return text, kb(coins, [b("🔄 Yangilash", "v:prices"), *MENU_BTN])

    if name == "market":
        text = (f"📊 <b>Bozor</b>\n━━━━━━━━━━━━━━\n{coin_lines()}\n\n"
                f"💵 Hamyon: <b>{m(u['cash'])}</b>\n"
                f"<i>🟢 chapda sotib olish · 🔴 o'ngda sotish · {clock()}</i>{foot}")
        rows = [[b(f"🟢 Olish {c['symbol']}", f"t:b:{c['id']}"), b(f"🔴 Sotish {c['symbol']}", f"t:s:{c['id']}")]
                for c in active_coins()]
        return text, kb(*rows, [b("🎯 Avto-buyurtma", "v:orders")], [b("🔄", "v:market"), *MENU_BTN])

    if name == "t":  # savdo oynasi: arg = "b:3" yoki "s:3"
        side, cid = arg.split(":")
        cid = int(cid)
        c = COINS[cid]
        h = q1("SELECT qty,cost FROM holdings WHERE uid=? AND cid=? AND qty>0", uid, cid)
        held = h["qty"] if h else 0
        mine = f"\n📦 Sizda: <b>{held} ta</b> ({m(held * c['price'])})" if held else ""
        head = (f"{c['emoji']} <b>{esc(c['name'])}</b>\n      <code>${c['price']:,.2f}</code>   {pc(ch1h(c))}\n"
                f"💵 Hamyon: <b>{m(u['cash'])}</b>{mine}\n")
        if side == "b":
            mx = int(u["cash"] // c["price"]) if c["price"] else 0
            title = "🟢 <b>Sotib olish</b>"
            opts = [n for n in (1, 5, 10, 25) if n <= mx]
            row = [b(f"{n} ta", f"x:b:{cid}:{n}") for n in opts]
            if mx and mx not in opts:
                row.append(b(f"Max ({mx})", f"x:b:{cid}:{mx}"))
            hint = "Nechta olasiz?" if mx else "⚠️ Mablag' yetarli emas"
        else:
            title = "🔴 <b>Sotish</b>"
            opts = [n for n in (1, 5, 10, 25) if n < held]
            row = [b(f"{n} ta", f"x:s:{cid}:{n}") for n in opts]
            if held:
                row.append(b(f"Hammasi ({held})", f"x:s:{cid}:{held}"))
            hint = "Nechta sotasiz?" if held else "⚠️ Sizda bu coin yo'q"
        text = f"{title}\n━━━━━━━━━━━━━━\n{head}\n{hint}\n<i>Narx bosgan paytingizda hisoblanadi · {clock()}</i>{foot}"
        other = b("🔴 Sotish rejimi", f"t:s:{cid}") if side == "b" else b("🟢 Olish rejimi", f"t:b:{cid}")
        return text, kb(row, [other, b("🔄", f"v:t:{arg}")], [b("💼 Portfel", "v:port"), b("⬅ Bozor", "v:market")])

    if name == "port":
        lines, rows, tot_cost, tot_val = [], [], 0, 0
        for h in holdings_of(uid):
            c = COINS[h["cid"]]
            val, avg = h["qty"] * c["price"], h["cost"] / h["qty"]
            pnl = val - h["cost"]
            tot_cost += h["cost"]
            tot_val += val
            lines.append(f"{c['emoji']} <b>{esc(c['name'])}</b> × {h['qty']}\n"
                         f"      Hozir: <b>{m(val)}</b> · O'rtacha: ${avg:,.2f}\n"
                         f"      {sg(pnl)} ({pnl / h['cost'] * 100:+.1f}%)  {'📈' if pnl >= 0 else '📉'}")
            rows.append(b(f"🔴 Sotish {c['symbol']}", f"t:s:{c['id']}"))
        body = "\n\n".join(lines) or "Hali coin yo'q.\n📊 Bozor orqali birinchi xaridni qiling!"
        text = (f"💼 <b>Portfel</b>\n━━━━━━━━━━━━━━\n{body}\n\n"
                f"💵 Hamyon: <b>{m(u['cash'])}</b>\n💰 Jami: <b>{m(u['cash'] + tot_val)}</b>\n"
                f"📊 Umumiy daromad: {sg(u['cash'] + tot_val - u['base'])}\n<i>{clock()}</i>{foot}")
        chunks = [rows[i:i + 2] for i in range(0, len(rows), 2)]
        sell_all = [[b("💸 Hammasini sotish", "v:sellall")]] if rows else []
        return text, kb(*chunks, *sell_all, [b("📜 Tarix", "v:hist"), b("🔄", "v:port")], [b("📊 Bozor", "v:market"), *MENU_BTN])

    if name == "hist":
        rs = q("SELECT * FROM trades WHERE uid=? ORDER BY id DESC LIMIT 10", uid)
        lines = []
        for r in rs:
            c = COINS.get(r["cid"])
            ts = datetime.fromtimestamp(r["ts"]).strftime("%d.%m %H:%M")
            lines.append(f"{'🟢 Olindi' if r['side'] == 'b' else '🔴 Sotildi'} {c['symbol'] if c else '?'} × {r['qty']} @ ${r['price']:,.2f} · {ts}")
        text = "📜 <b>Oxirgi savdolar</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali savdo yo'q")
        return text, kb([b("⬅ Portfel", "v:port"), *MENU_BTN])

    if name == "top":
        mode = arg or "profit"
        medals = ["🥇", "🥈", "🥉"]
        mk = lambda i: medals[i] if i < 3 else f"<b>{i + 1}.</b>"
        mine = ""
        if mode == "donors":
            rs = q("SELECT * FROM users WHERE donated>0 AND banned=0 ORDER BY donated DESC LIMIT 10")
            lines = [f"{mk(i)} 💎 {esc(r['name'])} — <b>{r['donated']} ⭐</b>" for i, r in enumerate(rs)]
            head, empty = "💎 <b>Homiylar</b>\n<i>Loyihani qo'llab-quvvatlaganlar</i>", "Hali homiylar yo'q — birinchi bo'ling!"
        else:
            rows_ = leaderboard()
            if mode == "rich":
                rows_ = sorted(((pr + r_["base"], r_) for pr, r_ in rows_), key=lambda x: -x[0])
                head = "🏦 <b>Eng boylar</b>\n<i>Umumiy balans bo'yicha</i>"
                fmt = lambda v: f"<b>{m(v)}</b>"
            else:
                head = "🏆 <b>Top treyderlar</b>\n<i>Eng ko'p daromad topganlar</i>"
                fmt = lambda v: f"<b>{sg(v)}</b>"
            lines = [f"{mk(i)} {tag(r_)}{esc(r_['name'])} — {fmt(v)}" for i, (v, r_) in enumerate(rows_[:10])]
            empty = "Hali hech kim yo'q"
            me = next((i for i, (_, r_) in enumerate(rows_) if r_["id"] == uid), None)
            if me is not None:
                mine = f"\n\n📍 Sizning o'rningiz: <b>#{me + 1}</b> · {fmt(rows_[me][0])}"
        text = f"{head}\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or empty) + mine
        tab = lambda k, t: b(("✅ " if mode == k else "") + t, f"v:top:{k}" if k != "profit" else "v:top")
        return text, kb([tab("profit", "Daromad"), tab("rich", "Boylik"), tab("donors", "Homiylar")],
                        [b("⭐ Donat / To'ldirish", "v:pay")], [b("🔄", f"v:top:{mode}"), *MENU_BTN])

    if name == "bonus":
        left = u["last_daily"] + 86400 - time.time()
        streak = u["streak"] if time.time() - u["last_daily"] < 172800 else 0
        nxt = cfgf("daily_bonus") * (1 + min(streak, 6) * 0.5)
        if left > 0:
            hh, mm = int(left // 3600), int(left % 3600 // 60)
            text = f"🎁 <b>Kunlik bonus</b>\n━━━━━━━━━━━━━━\n🔥 Seriya: <b>{streak} kun</b>\n⏳ Keyingi bonus: <b>{hh} soat {mm} daqiqa</b>dan keyin"
            return text, kb(MENU_BTN)
        text = (f"🎁 <b>Kunlik bonus</b>\n━━━━━━━━━━━━━━\n🔥 Seriya: <b>{streak} kun</b>\n"
                f"Bugungi bonus: <b>{m(nxt)}</b>\n<i>Har kuni kirsangiz bonus oshib boradi (7 kungacha)</i>")
        return text, kb([b(f"🎁 Olish {m(nxt)}", "claim")], MENU_BTN)

    if name == "ref":
        link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
        bonus = cfgf("ref_bonus")
        text = (f"👥 <b>Do'stlarni taklif qiling</b>\n━━━━━━━━━━━━━━\n{T('ref_intro', bonus=m(bonus))}\n\n"
                f"🔗 Havolangiz:\n<code>{link}</code>\n\n"
                f"👤 Taklif qilinganlar: <b>{u['ref_count']}</b>\n💵 Daromad: <b>{m(u['ref_earned'])}</b>")
        share = f"https://t.me/share/url?url={quote(link)}&text={quote('💎 Virtual Bozor — coinlar bilan savdo o`yini. Kir va bonus ol!')}"
        return text, kb([ub("📤 Do'stga yuborish", share)], MENU_BTN)

    if name == "pay":
        pk = q("SELECT * FROM packages ORDER BY stars")
        text = (f"⭐ <b>Hisobni to'ldirish / Donat</b>\n━━━━━━━━━━━━━━\n{T('pay_intro')}\n\n"
                f"Paketni tanlang:{foot}")
        rows = [[b(f"⭐ {p['stars']}  →  {m(p['amount'])}", f"buy:{p['id']}")] for p in pk]
        return text, kb(*rows, support_btn(), MENU_BTN)

    if name == "shop":
        lines = [f"{n} — <b>{m(p)}</b>" for _, n, p in SHOP]
        text = (f"🛍 <b>Do'kon</b>\n━━━━━━━━━━━━━━\nUnvon sotib oling — ismingiz yonida va reytingda ko'rinadi.\n\n"
                + "\n".join(lines) + f"\n\n💵 Hamyon: <b>{m(u['cash'])}</b>\n"
                f"Hozirgi unvon: {u['title'] or '—'}{foot}")
        rows = [[b(f"{n} · {m(p)}", f"sb:{k}")] for k, n, p in SHOP]
        return text, kb(*rows, MENU_BTN)

    if name == "me":
        text = (f"👤 <b>Profil</b>\n━━━━━━━━━━━━━━\n{tag(u)}<b>{esc(u['name'])}</b>\n🆔 <code>{uid}</code>\n"
                f"📅 Ro'yxatdan o'tgan: {datetime.fromtimestamp(u['created']).strftime('%d.%m.%Y')}\n"
                f"🔁 Savdolar: <b>{u['trades']}</b> · 🎮 O'yinlar: <b>{u['games']}</b> (🏆 {u['wins']})\n"
                f"👥 Takliflar: <b>{u['ref_count']}</b>\n"
                f"🔔 Narx xabarnomasi: <b>{'yoqilgan' if u['notif'] else 'o`chirilgan'}</b>{foot}")
        return text, kb([b("🏅 Yutuqlar", "v:ach"), b("📜 Savdolar", "v:hist")],
                        [b("🔕 Xabarnomani o'chirish" if u["notif"] else "🔔 Xabarnomani yoqish", "tgl")],
                        support_btn(), [b("🚪 Chiqish", "logout")], MENU_BTN)

    more = view_more(uid, u, name, arg, foot)
    if more:
        return more

    if name == "g":
        return game_view(uid, u, arg, foot)

    return view(uid, "menu")


def bet_rows(prefix, u):
    row = [b(f"${x}", f"{prefix}:{x}") for x in BETS if x <= u["cash"]]
    return row


def game_view(uid, u, arg, foot):
    p = arg.split(":") if arg else []
    wallet = f"💵 Hamyon: <b>{m(u['cash'])}</b>"
    back = [b("⬅ O'yinlar", "v:g"), *MENU_BTN]
    if not p:
        return (f"🎮 <b>Mini o'yinlar</b>\n━━━━━━━━━━━━━━\n{wallet}\n\n"
                f"🎲 <b>Zar</b> — 4, 5 yoki 6 tushsa yutasiz\n🪙 <b>Tanga</b> — gerb yoki raqam\n"
                f"🔮 <b>Bashorat</b> — 30 soniyada narx qayoqqa ketadi?{foot}",
                kb([b("🎲 Zar", "v:g:dice"), b("🪙 Tanga", "v:g:flip")], [b("🔮 Bashorat", "v:g:pred")], MENU_BTN))
    game = p[0]
    if game == "dice":
        r = bet_rows("gx:dice", u)
        return f"🎲 <b>Zar</b>\n━━━━━━━━━━━━━━\n{wallet}\n4–6 tushsa <b>x1.9</b> yutuq.\n\nTikishni tanlang:{foot}", kb(r, back)
    if game == "flip":
        if len(p) == 1:
            return f"🪙 <b>Tanga</b>\n━━━━━━━━━━━━━━\n{wallet}\nTo'g'ri topsangiz <b>x1.9</b>.\n\nTikishni tanlang:{foot}", kb(bet_rows("v:g:flip", u), back)
        return (f"🪙 <b>Tanga</b> · tikish {m(float(p[1]))}\nTomonni tanlang:",
                kb([b("🦅 Gerb", f"gx:flip:{p[1]}:h"), b("🔢 Raqam", f"gx:flip:{p[1]}:t")], back))
    if game == "pred":
        if len(p) == 1:
            return f"🔮 <b>Bashorat</b>\n━━━━━━━━━━━━━━\n{wallet}\nCoin 30 soniyada ko'tariladimi yoki tushadimi? To'g'ri topsangiz <b>x1.9</b>.\n\nTikishni tanlang:{foot}", kb(bet_rows("v:g:pred", u), back)
        if len(p) == 2:
            rows = [[b(f"{c['emoji']} {c['name']}  ${c['price']:,.2f}", f"v:g:pred:{p[1]}:{c['id']}")] for c in active_coins()]
            return f"🔮 <b>Bashorat</b> · tikish {m(float(p[1]))}\nCoinni tanlang:", kb(*rows, back)
        c = COINS[int(p[2])]
        return (f"🔮 {c['emoji']} <b>{esc(c['name'])}</b>  ${c['price']:,.2f}\nTikish: {m(float(p[1]))}\n\n30 soniyadan keyin narx qayoqqa ketadi?",
                kb([b("📈 Ko'tariladi", f"gx:pred:{p[1]}:{c['id']}:u"), b("📉 Tushadi", f"gx:pred:{p[1]}:{c['id']}:d")], back))
    return view(uid, "g")




# ───────────────────────── YANGI EKRANLAR ─────────────────────────
def bar(p, g):
    p = min(p, g)
    return "▰" * p + "▱" * (g - p)


def left_txt(sec):
    sec = int(sec)
    return f"{sec // 3600} soat {sec % 3600 // 60} daqiqa"


def view_more(uid, u, name, arg, foot):
    """Qo'shimcha ekranlar. Noma'lum nom bo'lsa None qaytaradi."""
    if name == "rewards":
        dleft = u["last_daily"] + 86400 - time.time()
        sleft = u["spin_at"] + 86400 - time.time()
        prog, d = quest_progress(uid, u)
        done = sum(1 for qq in QUESTS if prog[qq[2]] >= qq[3])
        text = (f"🎁 <b>Bonuslar</b>\n━━━━━━━━━━━━━━\n"
                f"🎁 Kunlik bonus: {'✅ tayyor!' if dleft <= 0 else '⏳ ' + left_txt(dleft)}\n"
                f"🎰 G'ildirak: {'✅ tayyor!' if sleft <= 0 else '⏳ ' + left_txt(sleft)}\n"
                f"📋 Vazifalar: <b>{done}/{len(QUESTS)}</b> bajarildi\n"
                f"🎟 Promo-kod bo'lsa — kiriting va bonus oling{foot}")
        return text, kb([b("🎁 Kunlik bonus", "v:bonus"), b("🎰 G'ildirak", "v:wheel")],
                        [b("📋 Vazifalar", "v:quests"), b("🎟 Promo-kod", "v:promo")],
                        [b("🏁 Turnir", "v:tour"), b("🏦 Omonat", "v:deposit")],
                        [b("👥 Do'st taklif qilish", "v:ref")], MENU_BTN)

    if name == "quests":
        prog, d = quest_progress(uid, u)
        lines, rows = [], []
        for n, title, field, goal, key in QUESTS:
            p, claimed = prog[field], d[f"c{n}"]
            state = "✅ olingan" if claimed else (f"🎁 tayyor" if p >= goal else f"{min(p, goal)}/{goal}")
            lines.append(f"{title}\n      {bar(p, goal)} {state} · mukofot <b>{m(cfgf(key))}</b>")
            if p >= goal and not claimed:
                rows.append([b(f"🎁 Mukofot olish +{m(cfgf(key))}", f"qc:{n}")])
        text = f"📋 <b>Kunlik vazifalar</b>\n━━━━━━━━━━━━━━\n" + "\n\n".join(lines) + f"\n\n<i>Vazifalar har kuni yangilanadi.</i>{foot}"
        return text, kb(*rows, [b("🔄", "v:quests"), b("⬅ Bonuslar", "v:rewards")])

    if name == "wheel":
        left = u["spin_at"] + 86400 - time.time()
        prizes = " · ".join(f"${a}" for a, _ in WHEEL)
        if left > 0:
            text = f"🎰 <b>Omad g'ildiragi</b>\n━━━━━━━━━━━━━━\nBugungi urinish ishlatilgan.\n⏳ Keyingisi: <b>{left_txt(left)}</b>dan keyin{foot}"
            return text, kb([b("⬅ Bonuslar", "v:rewards")])
        text = f"🎰 <b>Omad g'ildiragi</b>\n━━━━━━━━━━━━━━\nKuniga 1 marta bepul aylantiring!\n\nYutuqlar: {prizes}{foot}"
        return text, kb([b("🎰 Aylantirish", "spin")], [b("⬅ Bonuslar", "v:rewards")])

    if name == "news":
        rs = q("SELECT * FROM news ORDER BY id DESC LIMIT 8")
        lines = []
        for n_ in rs:
            c = COINS.get(n_["cid"])
            lines.append(f"<b>{datetime.fromtimestamp(n_['ts']).strftime('%H:%M')}</b> {c['emoji'] if c else ''} {esc(n_['text'])} <i>({n_['pct']:+.1f}%)</i>")
        text = "📰 <b>Bozor yangiliklari</b>\n━━━━━━━━━━━━━━\n" + ("\n\n".join(lines) or "Hozircha yangilik yo'q — tez orada!") + foot
        return text, kb([b("📊 Bozor", "v:market"), b("🔄", "v:news")], MENU_BTN)

    if name == "alerts":
        p = arg.split(":") if arg else []
        if p and p[0] == "new":
            rows = [[b(f"{c['emoji']} {c['name']}  ${c['price']:,.2f}", f"v:alerts:c:{c['id']}")] for c in active_coins()]
            return "🔔 <b>Yangi ogohlantirish</b>\nQaysi coin uchun?", kb(*rows, [b("⬅ Orqaga", "v:alerts")])
        if p and p[0] == "c":
            c = COINS[int(p[1])]
            ups = [b(f"📈 +{x}% → ${c['price'] * (1 + x / 100):,.2f}", f"ac:{c['id']}:{x}") for x in (3, 5, 10)]
            dns = [b(f"📉 −{x}% → ${c['price'] * (1 - x / 100):,.2f}", f"ac:{c['id']}:-{x}") for x in (3, 5, 10)]
            return (f"🔔 {c['emoji']} <b>{esc(c['name'])}</b>  ${c['price']:,.2f}\nNarx qaysi darajaga yetganda xabar beray?",
                    kb(*[[x] for x in ups + dns], [b("⬅ Orqaga", "v:alerts:new")]))
        al = q("SELECT * FROM alerts WHERE uid=? ORDER BY id", uid)
        lines, rows = [], []
        for a in al:
            c = COINS.get(a["cid"])
            if c:
                lines.append(f"{c['emoji']} {esc(c['name'])} {'≥' if a['dir'] == 'u' else '≤'} <b>${a['target']:,.2f}</b> (hozir ${c['price']:,.2f})")
                rows.append([b(f"🗑 {c['symbol']} ${a['target']:,.2f}", f"ad:{a['id']}")])
        text = (f"🔔 <b>Narx ogohlantirishlari</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali ogohlantirish yo'q.\nNarx kerakli darajaga yetganda xabar beramiz.") + f"\n\n<i>Maksimum 5 ta.</i>{foot}")
        return text, kb(*rows, [b("➕ Yangi ogohlantirish", "v:alerts:new")], MENU_BTN)

    if name == "orders":
        p_ = arg.split(":") if arg else []
        if p_ and p_[0] == "new":
            rows = [[b(f"{c['emoji']} {c['name']}  ${c['price']:,.2f}", f"v:orders:c:{c['id']}")] for c in active_coins()]
            return "🎯 <b>Yangi avto-buyurtma</b>\nQaysi coin uchun?", kb(*rows, [b("⬅ Orqaga", "v:orders")])
        if p_ and p_[0] == "c":
            c = COINS[int(p_[1])]
            i, pr = c["id"], c["price"]
            rows = [[b(f"🎯 Foyda +{x}% → ${pr * (1 + x / 100):,.2f}", f"oc:{i}:tp:{x}") for x in (5, 10)],
                    [b(f"🛑 Zarar −{x}% → ${pr * (1 - x / 100):,.2f}", f"oc:{i}:sl:{x}") for x in (5, 10)],
                    [b(f"🟢 Tushsa olish −{x}% → ${pr * (1 - x / 100):,.2f}", f"oc:{i}:bl:{x}") for x in (3, 5)]]
            return (f"🎯 {c['emoji']} <b>{esc(c['name'])}</b>  ${pr:,.2f}\n\n"
                    f"🎯 <b>Foyda</b> — narx oshsa, barcha coinlaringiz sotiladi\n🛑 <b>Zarar</b> — narx tushsa, zararni cheklab sotadi\n"
                    f"🟢 <b>Tushsa olish</b> — narx tushsa, hamyonning 25% iga coin oladi",
                    kb(*rows, [b("⬅ Orqaga", "v:orders:new")]))
        os_ = q("SELECT * FROM orders WHERE uid=? ORDER BY id", uid)
        names = {"tp": "🎯 Foyda ≥", "sl": "🛑 Zarar ≤", "bl": "🟢 Olish ≤"}
        lines, rows = [], []
        for o in os_:
            c = COINS.get(o["cid"])
            if c:
                lines.append(f"{names[o['kind']]} <b>${o['target']:,.2f}</b> · {c['emoji']} {esc(c['name'])} (hozir ${c['price']:,.2f})")
                rows.append([b(f"🗑 {c['symbol']} {names[o['kind']]} ${o['target']:,.2f}", f"od:{o['id']}")])
        text = ("🎯 <b>Avto-buyurtmalar</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali buyurtma yo'q.\nNarx belgilangan darajaga yetsa, bot o'zi sotadi yoki oladi.")
                + f"\n\n<i>Maksimum 5 ta.</i>{foot}")
        return text, kb(*rows, [b("➕ Yangi buyurtma", "v:orders:new")], [b("📊 Bozor", "v:market"), *MENU_BTN])

    if name == "tour":
        t_ = active_tour()
        if not t_:
            last = q1("SELECT * FROM tours WHERE status='done' ORDER BY id DESC LIMIT 1")
            res = ""
            if last:
                top = [x_.rsplit(":", 1) for x_ in last["result"].split(";") if ":" in x_]
                res = f"\n\n🏆 <b>Oxirgi turnir: {esc(last['name'])}</b>\n" + "\n".join(f"{['🥇','🥈','🥉'][i]} {esc(n_)} — {sg(float(sc))}" for i, (n_, sc) in enumerate(top))
            return f"🏁 <b>Turnir</b>\n━━━━━━━━━━━━━━\nHozircha faol turnir yo'q. Tez orada yangisi boshlanadi!{res}{foot}", kb([b("🔄", "v:tour"), b("⬅ Bonuslar", "v:rewards")])
        joined = q1("SELECT 1 FROM tour_players WHERE tid=? AND uid=?", t_["id"], uid)
        rk = tour_ranking(t_["id"])
        prizes = [float(x) for x in t_["prizes"].split(",") if x]
        pr_txt = " · ".join(f"{['🥇','🥈','🥉'][i]} {m(p_)}" for i, p_ in enumerate(prizes[:3]))
        lines = [f"{['🥇','🥈','🥉'][i] if i < 3 else f'<b>{i + 1}.</b>'} {esc(n_)} — <b>{sg(sc)}</b>" for i, (n_, sc, _) in enumerate(rk[:10])]
        me = next((i for i, (_, sc, uid_) in enumerate(rk) if uid_ == uid), None)
        mine = f"\n\n📍 Sizning o'rningiz: <b>#{me + 1}</b> · {sg(rk[me][1])}" if me is not None else ""
        text = (f"🏁 <b>{esc(t_['name'])}</b>\n━━━━━━━━━━━━━━\n⏳ Qoldi: <b>{left_txt(t_['ends'] - time.time())}</b>\n🎁 Mukofotlar: {pr_txt}\n"
                f"👥 Qatnashchilar: <b>{len(rk)}</b>\n<i>Turnir davomida eng ko'p foyda topgan yutadi.</i>\n\n" + ("\n".join(lines) or "Hali qatnashchi yo'q — birinchi bo'ling!") + mine + foot)
        return text, kb(*([] if joined else [[b("🏁 Qatnashish", "tj")]]), [b("🔄", "v:tour"), b("⬅ Bonuslar", "v:rewards")])

    if name == "deposit":
        p_ = arg.split(":") if arg else []
        if p_ and p_[0] == "new":
            rows = [[b(f"⏱ {h} soat → +{pct}%", f"v:deposit:t:{h}")] for h, pct in DEPOSITS]
            return f"🏦 <b>Yangi omonat</b>\nMuddatni tanlang. Muddat tugagach pul foizi bilan qaytadi.\n💵 Hamyon: <b>{m(u['cash'])}</b>", kb(*rows, [b("⬅ Orqaga", "v:deposit")])
        if p_ and p_[0] == "t":
            h = int(p_[1])
            pct = dict(DEPOSITS)[h]
            amts = [b(f"${a:,} → +${a * pct / 100:,.0f}", f"dp:{h}:{a}") for a in (100, 500, 1000, 5000) if a <= u["cash"]]
            return (f"🏦 <b>{h} soatlik omonat (+{pct}%)</b>\n💵 Hamyon: <b>{m(u['cash'])}</b>\nQancha qo'yasiz?",
                    kb(*[[x] for x in amts], [b("⬅ Orqaga", "v:deposit:new")]))
        ds = q("SELECT * FROM deposits WHERE uid=? ORDER BY due", uid)
        lines = [f"🏦 <b>{m(d_['amount'])}</b> → {m(d_['amount'] * (1 + d_['rate'] / 100))} · ⏳ {left_txt(max(d_['due'] - time.time(), 0))}" for d_ in ds]
        text = ("🏦 <b>Omonat</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali omonat yo'q.\nPulni muddatga qo'ying — foiz bilan qaytadi.") + f"\n\n<i>Maksimum 3 ta omonat. Omonat umumiy balansga kiradi.</i>{foot}")
        return text, kb([b("➕ Yangi omonat", "v:deposit:new")], [b("⬅ Bonuslar", "v:rewards")])

    if name == "ach":
        lines = [f"{'✅' if ok else '🔒'} {e} {n}" for e, n, ok in achievements(u)]
        got = sum(1 for _, _, ok in achievements(u) if ok)
        return f"🏅 <b>Yutuqlar</b> · {got}/{len(lines)}\n━━━━━━━━━━━━━━\n" + "\n".join(lines), kb([b("⬅ Profil", "v:me")])

    if name == "help":
        return T("help_text") + foot, kb(support_btn(), MENU_BTN)

    if name == "support":
        return T("support_intro") + foot, kb([b("✍️ Xabar yozish", "sup")], MENU_BTN)

    if name == "promo":
        return (f"🎟 <b>Promo-kod</b>\n━━━━━━━━━━━━━━\nPromo-kodingiz bo'lsa kiriting va bonus oling.{foot}",
                kb([b("✍️ Kodni kiritish", "pr:go")], [b("⬅ Bonuslar", "v:rewards")]))

    if name == "sellall":
        hs = holdings_of(uid)
        tot = sum(h["qty"] * COINS[h["cid"]]["price"] for h in hs if h["cid"] in COINS)
        if not hs:
            return "Sotadigan coin yo'q.", kb([b("⬅ Portfel", "v:port")])
        lines = "\n".join(f"{COINS[h['cid']]['emoji']} {esc(COINS[h['cid']]['name'])} × {h['qty']}" for h in hs if h["cid"] in COINS)
        return (f"💸 <b>Hammasini sotish</b>\n━━━━━━━━━━━━━━\n{lines}\n\nTaxminiy summa: <b>{m(tot)}</b>\n"
                f"<i>Sotish narxni tushiradi.</i>", kb([b("🔴 Ha, hammasini sotish", "xa")], [b("⬅ Portfel", "v:port")]))
    return None


def custom_menu(mid):
    """Admin yaratgan menyu: (matn, klaviatura, rasm_file_id) yoki None."""
    mn = q1("SELECT * FROM menus WHERE id=? AND active=1", mid)
    if not mn:
        return None
    rows, pair = [], []
    for x in q("SELECT * FROM mbtns WHERE menu_id=? ORDER BY sort,id", mid):
        if x["kind"] == "url":
            bt = ub(x["label"], x["target"], x["color"])
        elif x["kind"] == "menu":
            bt = b(x["label"], f"m:{x['target']}", x["color"])
        else:
            bt = b(x["label"], f"v:{x['target']}", x["color"])
        pair.append(bt)
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append(MENU_BTN)
    text = f"<b>{esc(mn['title'])}</b>\n━━━━━━━━━━━━━━\n{mn['text']}"
    return text, kb(*rows), mn["photo"]
# ───────────────────────── HOLATLAR / ROUTER ─────────────────────────
class Reg(StatesGroup):
    name = State()
    pin = State()
    pin2 = State()
    login = State()


class Adm(StatesGroup):
    wait = State()


class Usr(StatesGroup):
    promo = State()
    support = State()


r = Router()
LAST = {}


class Gate(BaseMiddleware):
    """Ro'yxatdan o'tmagan / kirmagan / bloklangan foydalanuvchida hech qaysi tugma ishlamaydi."""
    async def __call__(self, handler, event, data):
        uid, d = event.from_user.id, event.data or ""
        if event.message is None:
            return await event.answer()
        if d.startswith("adm:"):
            if is_admin(uid):
                return await handler(event, data)
            return await event.answer("⛔ Ruxsat yo'q", show_alert=True)
        if cfg("maintenance") == "1" and not is_admin(uid):
            return await event.answer("🛠 Texnik ishlar ketmoqda. Birozdan keyin urinib ko'ring.", show_alert=True)
        if d.startswith(("reg:", "login:")):
            return await handler(event, data)
        u = get_user(uid)
        if not u:
            return await event.answer("Avval /start orqali ro'yxatdan o'ting", show_alert=True)
        if u["banned"]:
            return await event.answer("🚫 Hisobingiz bloklangan. Admin bilan bog'laning.", show_alert=True)
        if not u["logged_in"]:
            return await event.answer("🔐 Avval /start orqali kiring", show_alert=True)
        now = time.time()
        if now - LAST.get(uid, 0) < 0.35:
            return await event.answer("⏳")
        LAST[uid] = now
        seen(uid)
        return await handler(event, data)


async def show(cb, text, markup):
    msg = cb.message
    try:
        if msg.photo:
            await msg.delete()
            msg = await bot.send_message(msg.chat.id, text, reply_markup=markup)
        else:
            await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            msg = await bot.send_message(msg.chat.id, text, reply_markup=markup)
    return msg


def track_live(uid, msg, name, arg, text, note=""):
    if name in LIVE_VIEWS:
        LIVE[uid] = dict(chat=msg.chat.id, mid=msg.message_id, name=name, arg=arg, note=note,
                         exp=time.time() + LIVE_TTL, last=text)
    else:
        LIVE.pop(uid, None)


async def render(cb, name, arg="", note=""):
    uid = cb.from_user.id
    text, markup = view(uid, name, arg, note)
    msg = await show(cb, text, markup)
    track_live(uid, msg, name, arg, text, note)


async def send_menu(chat_id, uid, note=""):
    text, markup = view(uid, "menu", note=note)
    msg = await bot.send_message(chat_id, text, reply_markup=markup)
    LIVE.pop(uid, None)
    return msg


# ───────────────────────── RO'YXATDAN O'TISH / KIRISH ─────────────────────────
def hash_pin(salt, pin):
    return hashlib.sha256((salt + pin).encode()).hexdigest()


@r.message(CommandStart())
async def cmd_start(msg: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    if cfg("maintenance") == "1" and not is_admin(uid):
        return await msg.answer("🛠 <b>Texnik ishlar</b>\nBot vaqtincha ta'mirlanmoqda. Tez orada qaytamiz!")
    u = get_user(uid)
    if u and u["banned"]:
        sp = cfg("support").strip()
        return await msg.answer("🚫 Hisobingiz bloklangan.", reply_markup=kb(
            [ub("🆘 Adminga murojaat", sp if sp.startswith("http") else "https://t.me/" + sp.lstrip("@"))] if sp else []))
    if not u:
        arg = command.args or ""
        ref = int(arg[3:]) if arg.startswith("ref") and arg[3:].isdigit() else None
        await state.update_data(ref=ref)
        return await msg.answer(
            T("welcome", start=m(cfgf("start_balance")), bonus=m(cfgf("ref_bonus"))),
            reply_markup=kb([b("🚀 Ro'yxatdan o'tish", "reg:go")]))
    if not u["logged_in"]:
        await state.set_state(Reg.login)
        return await msg.answer(f"🔐 <b>Kirish</b>\nSalom, <b>{esc(u['name'])}</b>! PIN-kodingizni kiriting (4 raqam):")
    await send_menu(msg.chat.id, uid)


@r.callback_query(F.data == "reg:go")
async def reg_go(cb: CallbackQuery, state: FSMContext):
    if get_user(cb.from_user.id):
        return await cb.answer("Siz allaqachon ro'yxatdan o'tgansiz. /start", show_alert=True)
    await state.set_state(Reg.name)
    await cb.message.edit_text("📝 <b>1/3 · Ism tanlang</b>\n3–16 belgi (harf, raqam, _ - bo'sh joy).\nBu ism reytingda ko'rinadi.")
    await cb.answer()


@r.message(Reg.name, F.text)
async def reg_name(msg: Message, state: FSMContext):
    name = " ".join(msg.text.split())
    if not re.fullmatch(r"[\w\- ]{3,16}", name):
        return await msg.answer("⚠️ Ism 3–16 belgi bo'lsin (harf, raqam, _ - bo'sh joy). Qayta kiriting:")
    if q1("SELECT 1 FROM users WHERE name_lc=?", name.lower()):
        return await msg.answer("⚠️ Bu ism band. Boshqa ism yozing:")
    await state.update_data(name=name)
    await state.set_state(Reg.pin)
    await msg.answer("🔑 <b>2/3 · PIN-kod o'ylab toping</b>\n4 ta raqam. Keyin hisobga kirishda kerak bo'ladi.")


@r.message(Reg.pin, F.text)
async def reg_pin(msg: Message, state: FSMContext):
    pin = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass
    if not (pin.isdigit() and len(pin) == 4):
        return await msg.answer("⚠️ PIN aynan 4 ta raqam bo'lsin:")
    await state.update_data(pin=pin)
    await state.set_state(Reg.pin2)
    await msg.answer("🔁 <b>3/3 · PIN-kodni qayta kiriting</b>")


@r.message(Reg.pin2, F.text)
async def reg_pin2(msg: Message, state: FSMContext):
    d = await state.get_data()
    try:
        await msg.delete()
    except Exception:
        pass
    if msg.text.strip() != d.get("pin"):
        await state.set_state(Reg.pin)
        return await msg.answer("⚠️ PIN mos kelmadi. Qaytadan 4 raqamli PIN kiriting:")
    uid = msg.from_user.id
    if get_user(uid):
        await state.clear()
        return await send_menu(msg.chat.id, uid)
    salt = secrets.token_hex(8)
    sb = cfgf("start_balance")
    ref = d.get("ref")
    bonus = 0.0
    try:
        with tx():
            ex("INSERT INTO users(id,name,name_lc,tg_username,salt,pin,cash,base,created) VALUES(?,?,?,?,?,?,?,?,?)",
               uid, d["name"], d["name"].lower(), msg.from_user.username or "", salt, hash_pin(salt, d["pin"]), sb, sb, time.time())
            if ref and ref != uid and get_user(ref):
                bonus = cfgf("ref_bonus")
                ex("UPDATE users SET ref_by=?, cash=cash+?, base=base+? WHERE id=?", ref, bonus, bonus, uid)
                ex("UPDATE users SET cash=cash+?, base=base+?, ref_count=ref_count+1, ref_earned=ref_earned+? WHERE id=?",
                   bonus, bonus, bonus, ref)
    except sqlite3.IntegrityError:
        await state.set_state(Reg.name)
        return await msg.answer("⚠️ Bu ism band bo'lib qoldi. Boshqa ism yozing:")
    await state.clear()
    if bonus:
        try:
            await bot.send_message(ref, f"🎉 <b>{esc(d['name'])}</b> sizning havolangiz orqali qo'shildi! +{m(bonus)}")
        except Exception:
            pass
    extra = f"\n🎁 Taklif bonusi: <b>+{m(bonus)}</b>" if bonus else ""
    await send_menu(msg.chat.id, uid, f"✅ Xush kelibsiz! Start balans: <b>{m(sb)}</b>{extra}")


@r.callback_query(F.data == "login:go")
async def login_go(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Reg.login)
    await cb.message.edit_text("🔐 <b>Kirish</b>\nPIN-kodingizni kiriting (4 raqam):")
    await cb.answer()


@r.message(Reg.login, F.text)
async def login_pin(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    u = get_user(uid)
    try:
        await msg.delete()
    except Exception:
        pass
    if not u:
        await state.clear()
        return await msg.answer("Avval /start bosing.")
    if u["lock_until"] > time.time():
        return await msg.answer(f"⏳ Ko'p xato urinish. {int(u['lock_until'] - time.time()) + 1} soniyadan keyin urinib ko'ring.")
    if hash_pin(u["salt"], msg.text.strip()) != u["pin"]:
        fails = u["fails"] + 1
        if fails >= 5:
            ex("UPDATE users SET fails=0, lock_until=? WHERE id=?", time.time() + 300, uid)
            return await msg.answer("🔒 5 marta xato. 5 daqiqaga bloklandi. Admin bilan bog'lanib PIN ni tiklashingiz mumkin.")
        ex("UPDATE users SET fails=? WHERE id=?", fails, uid)
        return await msg.answer(f"❌ PIN noto'g'ri. Qolgan urinish: {5 - fails}")
    ex("UPDATE users SET logged_in=1, fails=0 WHERE id=?", uid)
    await state.clear()
    await send_menu(msg.chat.id, uid, "✅ Xush kelibsiz!")


@r.callback_query(F.data == "logout")
async def logout(cb: CallbackQuery):
    ex("UPDATE users SET logged_in=0 WHERE id=?", cb.from_user.id)
    LIVE.pop(cb.from_user.id, None)
    await cb.message.edit_text("🚪 Hisobdan chiqdingiz.", reply_markup=kb([b("🔑 Kirish", "login:go")]))
    await cb.answer()


# ───────────────────────── EKRANLAR ─────────────────────────
@r.callback_query(F.data.startswith("v:"))
async def on_view(cb: CallbackQuery):
    parts = cb.data.split(":", 2)
    try:
        await render(cb, parts[1], parts[2] if len(parts) > 2 else "")
    except (KeyError, ValueError, IndexError):
        await render(cb, "menu")
    await cb.answer()


@r.callback_query(F.data.startswith("t:"))
async def on_trade_open(cb: CallbackQuery):
    _, side, cid = cb.data.split(":")
    c = COINS.get(int(cid))
    if not c or (side == "b" and not c["active"]):
        return await cb.answer("Bu coin hozir savdoda emas", show_alert=True)
    await render(cb, "t", f"{side}:{cid}")
    await cb.answer()


@r.callback_query(F.data.startswith("x:"))
async def on_trade_do(cb: CallbackQuery):
    _, side, cid, qty = cb.data.split(":")
    uid = cb.from_user.id
    ok, note = trade(uid, int(cid), side, int(qty))
    if not ok:
        return await cb.answer("⚠️ " + note, show_alert=True)
    await render(cb, "t", f"{side}:{cid}", note)
    await cb.answer("✅ Bajarildi")


@r.callback_query(F.data.startswith("c:"))
async def on_coin(cb: CallbackQuery):
    c = COINS.get(int(cb.data[2:]))
    if not c:
        return await cb.answer()
    LIVE.pop(cb.from_user.id, None)
    lo, hi = q1("SELECT MIN(price) a, MAX(price) b FROM hist WHERE cid=?", c["id"])
    lo, hi = lo or c["price"], hi or c["price"]
    cap = (f"{c['emoji']} <b>{esc(c['name'])}</b> ({c['symbol']})\n"
           f"💲 <b>${c['price']:,.2f}</b>   {pc(ch1h(c))} (1 soat)\n"
           f"📉 24s min: ${min(lo, c['price']):,.2f} · 📈 max: ${max(hi, c['price']):,.2f}")
    markup = kb([b("🟢 Olish", f"t:b:{c['id']}"), b("🔴 Sotish", f"t:s:{c['id']}")],
                [b("🔄", f"c:{c['id']}"), b("⬅ Narxlar", "v:prices")])
    png = chart_png(c)
    try:
        await cb.message.delete()
    except Exception:
        pass
    if png:
        await bot.send_photo(cb.message.chat.id, BufferedInputFile(png, "chart.png"), caption=cap, reply_markup=markup)
    else:
        await bot.send_message(cb.message.chat.id, cap, reply_markup=markup)
    await cb.answer()


# ───────────────────────── BONUS / DO'KON / SOZLAMA ─────────────────────────
@r.callback_query(F.data == "claim")
async def claim(cb: CallbackQuery):
    uid, now = cb.from_user.id, time.time()
    with tx():
        u = get_user(uid)
        if now - u["last_daily"] < 86400:
            return await cb.answer("⏳ Bonus hali tayyor emas", show_alert=True)
        prev = u["streak"] if now - u["last_daily"] < 172800 else 0
        amt = cfgf("daily_bonus") * (1 + min(prev, 6) * 0.5)
        ex("UPDATE users SET cash=round(cash+?,2), base=base+?, streak=?, last_daily=? WHERE id=?", amt, amt, prev + 1, now, uid)
    await render(cb, "bonus", note=f"🎉 +{m(amt)} qo'shildi!")
    await cb.answer("🎁 Bonus olindi")


@r.callback_query(F.data.startswith("sb:"))
async def shop_buy(cb: CallbackQuery):
    item = next((x for x in SHOP if x[0] == cb.data[3:]), None)
    if not item:
        return await cb.answer()
    _, name, price = item
    uid = cb.from_user.id
    with tx():
        u = get_user(uid)
        if u["title"] == name:
            return await cb.answer("Bu unvon sizda allaqachon bor", show_alert=True)
        if u["cash"] < price:
            return await cb.answer("⚠️ Mablag' yetarli emas", show_alert=True)
        ex("UPDATE users SET cash=round(cash-?,2), base=base-?, title=? WHERE id=?", price, price, name, uid)
    await render(cb, "shop", note=f"✅ Yangi unvon: {name}")
    await cb.answer()


@r.callback_query(F.data == "tgl")
async def toggle_notif(cb: CallbackQuery):
    ex("UPDATE users SET notif=1-notif WHERE id=?", cb.from_user.id)
    await render(cb, "me")
    await cb.answer()


# ───────────────────────── O'YINLAR ─────────────────────────
def credit(uid, amt):
    if amt:
        ex("UPDATE users SET cash=round(cash+?,2) WHERE id=?", amt, uid)


@r.callback_query(F.data.startswith("gx:"))
async def play(cb: CallbackQuery):
    p = cb.data.split(":")
    game, bet, uid = p[1], float(p[2]), cb.from_user.id
    if bet not in BETS:
        return await cb.answer()
    left = cooldown(uid, "game", 8)
    if left:
        return await cb.answer(f"⏳ {int(left) + 1} soniya kuting", show_alert=True)
    with tx():
        ok = get_user(uid)["cash"] >= bet
        if ok:
            ex("UPDATE users SET cash=round(cash-?,2) WHERE id=?", bet, uid)
    if not ok:
        CD.pop((uid, "game"), None)
        return await cb.answer("⚠️ Mablag' yetarli emas", show_alert=True)
    again = [b("🔁 Yana", f"v:g:{game}"), b("🎮 O'yinlar", "v:g")]
    try:
        if game == "dice":
            await cb.answer()
            dm = await bot.send_dice(cb.message.chat.id, emoji="🎲")
            await asyncio.sleep(3.5)
            win = dm.dice.value >= 4
            res = f"🎲 Tushdi: <b>{dm.dice.value}</b>\n"
        elif game == "flip":
            side = random.choice("ht")
            win = side == p[3]
            res = f"🪙 Tushdi: <b>{'🦅 Gerb' if side == 'h' else '🔢 Raqam'}</b>\n"
        elif game == "pred":
            cid, d = int(p[3]), p[4]
            c = COINS[cid]
            ex("INSERT INTO preds(uid,cid,dir,bet,p0,due) VALUES(?,?,?,?,?,?)", uid, cid, d, bet, c["price"], time.time() + 30)
            ex("UPDATE users SET games=games+1 WHERE id=?", uid)
            bump(uid, "games")
            u = get_user(uid)
            await cb.answer("🔮 Qabul qilindi")
            await show(cb, f"🔮 <b>Bashorat qabul qilindi</b>\n{c['emoji']} {esc(c['name'])} ${c['price']:,.2f} → {'📈 ko`tariladi' if d == 'u' else '📉 tushadi'}\n"
                           f"Tikish: {m(bet)}\n\n⏳ Natija 30 soniyadan keyin xabar qilinadi.\n💵 Hamyon: {m(u['cash'])}",
                       kb([b("🔁 Yana", "v:g:pred")], [b("📊 Bozor", "v:market"), *MENU_BTN]))
            return
        else:
            return
        pay = round(bet * 1.9, 2) if win else 0
        credit(uid, pay)
        ex("UPDATE users SET games=games+1, wins=wins+? WHERE id=?", int(win), uid)
        bump(uid, "games")
        u = get_user(uid)
        head = f"🎉 <b>Yutdingiz! +{m(pay - bet)}</b>" if win else f"😕 <b>Yutqazdingiz −{m(bet)}</b>"
        await show(cb, f"{res}{head}\n💵 Hamyon: <b>{m(u['cash'])}</b>", kb(again, MENU_BTN))
        if game != "dice":
            await cb.answer()
    except Exception:
        log.exception("game error")
        credit(uid, bet)  # xatoda tikish qaytariladi
        try:
            await cb.answer("Xatolik. Tikish qaytarildi.", show_alert=True)
        except Exception:
            pass




# ───────────────────────── YANGI TUGMALAR: g'ildirak, vazifa, ogohlantirish, menyu, murojaat ─────────────────────────
@r.callback_query(F.data == "spin")
async def on_spin(cb: CallbackQuery):
    uid = cb.from_user.id
    amt = spin_wheel(uid)
    if amt is None:
        return await cb.answer("⏳ Bugungi urinish ishlatilgan", show_alert=True)
    await cb.answer()
    for frame in ("🎰 ❓ ❓ ❓", "🎰 💰 ❓ ❓", "🎰 💰 💎 ❓"):
        await show(cb, f"🎰 <b>Omad g'ildiragi</b>\n━━━━━━━━━━━━━━\n{frame}", None)
        await asyncio.sleep(0.5)
    await render(cb, "wheel", note=f"🎉 Yutuq: <b>+{m(amt)}</b>")


@r.callback_query(F.data.startswith("qc:"))
async def on_quest(cb: CallbackQuery):
    ok, msg_ = claim_quest(cb.from_user.id, int(cb.data[3:]))
    if not ok:
        return await cb.answer("⚠️ " + msg_, show_alert=True)
    await render(cb, "quests", note=msg_)
    await cb.answer("🎁 Olindi")


@r.callback_query(F.data.startswith("ac:"))
async def on_alert_add(cb: CallbackQuery):
    _, cid, pct = cb.data.split(":")
    uid, c = cb.from_user.id, COINS.get(int(cid))
    if not c or not c["active"]:
        return await cb.answer("Coin topilmadi", show_alert=True)
    if q1("SELECT COUNT(*) n FROM alerts WHERE uid=?", uid)["n"] >= 5:
        return await cb.answer("⚠️ Maksimum 5 ta ogohlantirish", show_alert=True)
    pct = int(pct)
    ex("INSERT INTO alerts(uid,cid,target,dir) VALUES(?,?,?,?)", uid, c["id"],
       round(c["price"] * (1 + pct / 100), 2), "u" if pct > 0 else "d")
    await render(cb, "alerts", note="✅ Ogohlantirish qo'shildi")
    await cb.answer()


@r.callback_query(F.data.startswith("ad:"))
async def on_alert_del(cb: CallbackQuery):
    ex("DELETE FROM alerts WHERE id=? AND uid=?", int(cb.data[3:]), cb.from_user.id)
    await render(cb, "alerts")
    await cb.answer("🗑 O'chirildi")


@r.callback_query(F.data == "xa")
async def on_sell_all(cb: CallbackQuery):
    uid, total, cnt = cb.from_user.id, 0.0, 0
    for h in holdings_of(uid):
        c = COINS.get(h["cid"])
        if not c:
            continue
        val = h["qty"] * c["price"]
        ok, _ = trade(uid, h["cid"], "s", h["qty"])
        if ok:
            total += val
            cnt += 1
    if not cnt:
        return await cb.answer("Sotadigan coin yo'q", show_alert=True)
    await render(cb, "port", note=f"✅ {cnt} ta coin sotildi · <b>{m(total)}</b>")
    await cb.answer("✅ Sotildi")


@r.callback_query(F.data.startswith("m:"))
async def on_custom_menu(cb: CallbackQuery):
    uid = cb.from_user.id
    res = custom_menu(int(cb.data[2:]))
    if not res:
        return await cb.answer("Menyu topilmadi", show_alert=True)
    text, markup, photo = res
    LIVE.pop(uid, None)
    if photo:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await bot.send_photo(cb.message.chat.id, photo, caption=text[:1024], reply_markup=markup)
    else:
        await show(cb, text, markup)
    await cb.answer()


@r.callback_query(F.data == "pr:go")
async def promo_go(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Usr.promo)
    await show(cb, "🎟 <b>Promo-kodni yozing:</b>", kb([b("✖ Bekor qilish", "v:rewards")]))
    await cb.answer()


@r.message(Usr.promo, F.text)
async def promo_text(msg: Message, state: FSMContext):
    await state.clear()
    if cooldown(msg.from_user.id, "promo", 3):
        return await msg.answer("⏳ Sekinroq urinib ko'ring.")
    ok, text = redeem_promo(msg.from_user.id, msg.text)
    await msg.answer(text, reply_markup=kb([b("🎁 Bonuslar", "v:rewards"), *MENU_BTN]))


@r.callback_query(F.data == "sup")
async def sup_go(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Usr.support)
    await show(cb, "✍️ <b>Xabaringizni yozing</b> (matn yoki rasm).\nAdmin javob bersa, shu yerda xabar keladi.",
               kb([b("✖ Bekor qilish", "v:menu")]))
    await cb.answer()


@r.message(Usr.support)
async def sup_msg(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    await state.clear()
    if cooldown(uid, "sup", 30):
        return await msg.answer("⏳ Iltimos, keyingi xabarni 30 soniyadan keyin yuboring.")
    u = get_user(uid)
    head = f"🆘 <b>Murojaat</b> · {esc(u['name'])} (<code>{uid}</code>)\n\n"
    sent = 0
    for a in admin_ids():
        try:
            await bot.send_message(a, head + esc(msg.text or msg.caption or "[media]"),
                                   reply_markup=kb([b("↩️ Javob yozish", f"adm:input:reply:{uid}"), b("👤 Profil", f"adm:u:{uid}")]))
            if msg.photo:
                await bot.send_photo(a, msg.photo[-1].file_id)
            sent += 1
        except Exception:
            pass
    await msg.answer("✅ Xabaringiz adminga yuborildi. Javobni shu yerda olasiz." if sent else
                     "⚠️ Hozircha adminga yetkazib bo'lmadi. Keyinroq urinib ko'ring.",
                     reply_markup=kb(MENU_BTN))


@r.callback_query(F.data.startswith("oc:"))
async def on_order_add(cb: CallbackQuery):
    _, cid, kind, pct = cb.data.split(":")
    ok, note = make_order(cb.from_user.id, int(cid), kind, int(pct))
    if not ok:
        return await cb.answer("⚠️ " + note, show_alert=True)
    await render(cb, "orders", note=note)
    await cb.answer()


@r.callback_query(F.data.startswith("od:"))
async def on_order_del(cb: CallbackQuery):
    ex("DELETE FROM orders WHERE id=? AND uid=?", int(cb.data[3:]), cb.from_user.id)
    await render(cb, "orders")
    await cb.answer("🗑 O'chirildi")


@r.callback_query(F.data == "tj")
async def on_tour_join(cb: CallbackQuery):
    if not join_tour(cb.from_user.id):
        return await cb.answer("Faol turnir yo'q", show_alert=True)
    await render(cb, "tour", note="✅ Siz turnirda qatnashyapsiz! Omad!")
    await cb.answer("🏁 Qatnashdingiz")


@r.callback_query(F.data.startswith("dp:"))
async def on_deposit(cb: CallbackQuery):
    _, h, amt = cb.data.split(":")
    ok, note = make_deposit(cb.from_user.id, int(h), float(amt))
    if not ok:
        return await cb.answer("⚠️ " + note, show_alert=True)
    await render(cb, "deposit", note=note)
    await cb.answer("🏦 Qo'yildi")
# ───────────────────────── TO'LOV (STARS) ─────────────────────────
@r.callback_query(F.data.startswith("buy:"))
async def buy(cb: CallbackQuery):
    pk = q1("SELECT * FROM packages WHERE id=?", int(cb.data[4:]))
    if not pk:
        return await cb.answer("Paket topilmadi", show_alert=True)
    try:
        await bot.send_invoice(
            chat_id=cb.from_user.id, title=f"💰 {m(pk['amount'])} o'yin balansi",
            description=f"Virtual Bozor o'yin balansi {m(pk['amount'])} + 💎 homiy belgisi. Balans faqat o'yin ichida ishlatiladi.",
            payload=f"pk:{pk['id']}:{pk['amount']}", currency="XTR",
            prices=[LabeledPrice(label=f"{pk['stars']} ⭐", amount=pk["stars"])])
        await cb.answer()
    except Exception:
        log.exception("invoice error")
        await cb.answer("⚠️ To'lovni ochib bo'lmadi. Adminga murojaat qiling.", show_alert=True)


@r.pre_checkout_query()
async def pre_checkout(pq: PreCheckoutQuery):
    u = get_user(pq.from_user.id)
    if not u or u["banned"] or not pq.invoice_payload.startswith("pk:"):
        return await pq.answer(ok=False, error_message="Hisob topilmadi yoki bloklangan. Adminga murojaat qiling.")
    await pq.answer(ok=True)


@r.message(F.successful_payment)
async def paid(msg: Message):
    sp, uid = msg.successful_payment, msg.from_user.id
    try:
        _, _, amount = sp.invoice_payload.split(":")
        amount = float(amount)
    except Exception:
        amount = 0.0
    try:
        with tx():
            ex("INSERT INTO payments(uid,stars,amount,charge,ts) VALUES(?,?,?,?,?)",
               uid, sp.total_amount, amount, sp.telegram_payment_charge_id, time.time())
            ex("UPDATE users SET cash=round(cash+?,2), base=base+?, donated=donated+? WHERE id=?", amount, amount, sp.total_amount, uid)
    except sqlite3.IntegrityError:
        return  # takroriy xabar
    u = get_user(uid)
    await msg.answer(f"✅ <b>To'lov qabul qilindi!</b>\n+{m(amount)} hisobingizga qo'shildi.\nRahmat! 💎 belgisi berildi.",
                     reply_markup=kb([b("📊 Bozor", "v:market"), b("⬅ Menyu", "v:menu")]))
    for a in admin_ids():
        try:
            await bot.send_message(a, f"⭐ <b>Yangi to'lov</b>: {sp.total_amount} Stars\n👤 {esc(u['name'])} (<code>{uid}</code>)\n💰 {m(amount)}")
        except Exception:
            pass



# ───────────────────────── ADMIN PANEL (alohida, faqat adminga) ─────────────────────────
PROMPTS = {
    "price": "💲 Yangi narxni yozing (masalan <code>85.5</code>):",
    "vol": "📈 Tebranish koeffitsienti (0.1–5, standart 1):",
    "addcoin": "➕ Format: <code>Nom | BELGI | emoji | narx</code>\nMasalan: <code>SunCoin | SUN | 🟡 | 60</code>",
    "coinedit": "✏️ Format: <code>Nom | BELGI | emoji</code>",
    "newsc": "📰 Format: <code>foiz | yangilik matni</code>\nMasalan: <code>+6 | Yangi hamkor topildi!</code> yoki <code>-4 | Sotuvlar ko'paydi</code>",
    "finduser": "🔎 Foydalanuvchi ID yoki ismini yozing:",
    "bal+": "➕ Qo'shiladigan summa:", "bal-": "➖ Ayiriladigan summa:",
    "dm": "✉️ Foydalanuvchiga yuboriladigan xabar (premium emoji va formatlash ishlaydi):",
    "title": "🏷 Foydalanuvchi unvoni (bo'sh qoldirish uchun <code>-</code>):",
    "reply": "↩️ Javobingizni yozing:",
    "bcast": "📣 Barcha foydalanuvchilarga xabar yozing (premium emoji va formatlash ishlaydi). Rasm bilan yuborsangiz — rasm bilan ketadi:",
    "giveall": "🎁 Barcha foydalanuvchilarga qo'shiladigan summa:",
    "promo": "🎟 Format: <code>KOD | summa | limit | kun</code>\nMasalan: <code>BAHOR | 250 | 100 | 7</code>\n(limit yoki kun uchun 0 — cheksiz)",
    "tour_new": "🏁 Format: <code>Nom | soat | 1-o'rin | 2-o'rin | 3-o'rin</code>\nMasalan: <code>Haftalik turnir | 168 | 5000 | 2500 | 1000</code>",
    "addpk": "➕ Format: <code>stars | dollar</code>\nMasalan: <code>25 | 9000</code>",
    "set": "✏️ Yangi qiymatni yozing:", "pin": "🔑 Yangi 4 xonali PIN:",
    "emo": "🎨 Endi shu emoji o'rniga qo'yiladigan <b>premium emoji</b>ni yuboring (faqat bitta premium emoji yozing).",
    "emo_new": "➕ Almashtiriladigan <b>oddiy emoji</b>ni yozing (masalan 💎):",
    "mn_title": "🧩 Yangi menyu <b>nomi</b> (tugmada ko'rinadi, emoji bilan). Masalan: <code>🎁 Aksiyalar</code>",
    "mn_body": "📝 Menyu <b>matni</b> (formatlash va premium emoji ishlaydi):",
    "mn_t": "✏️ Yangi nom:", "mn_b": "📝 Yangi matn:", "mn_p": "🖼 Menyu uchun rasm yuboring (o'chirish uchun <code>-</code> yozing):",
    "mb_add": ("➕ Format: <code>Yozuv | tur | maqsad | rang</code>\n"
               "• tur <b>url</b>: <code>Kanal | url | https://t.me/kanal | primary</code>\n"
               "• tur <b>menu</b>: maqsad — menyu raqami\n"
               "• tur <b>view</b>: maqsad — " + ", ".join(VIEWS) + "\n"
               "Rang: primary (ko'k), success (yashil), danger (qizil)"),
    "tx": "📝 Yangi matnni yuboring (formatlash va premium emoji ishlaydi):",
    "sql": "🧮 Faqat <b>SELECT</b> so'rovi (o'qish rejimi). Masalan: <code>select name,cash from users order by cash desc limit 5</code>",
    "pl_new": "🧩 Yangi plagin <b>nomi</b> (lotin harflari, raqam, _; 3–24 belgi). Masalan: <code>salomlashuv</code>",
    "pl_code": ("🧩 Plagin <b>kodini</b> yuboring — matn yoki <code>.py</code> fayl.\n\n<b>Namuna:</b>\n<pre>" + esc(PLUGIN_EXAMPLE) + "</pre>"
                "Mavjud: <code>router, bot, add_view, q, q1, ex, b, kb, view, COINS, get_user, credit, cfg, T, safe_send, trade...</code>\n"
                "Kod xatosiz bo'lsa darhol ishga tushadi, xato bo'lsa o'chirib qo'yiladi (bot to'xtamaydi).\n"
                "⚠️ Xabar (message) handlerlarida har doim filtr bering (masalan Command) va ro'yxatdan o'tganlikni <code>get_user(uid)</code> bilan tekshiring."),
    "selfupd": "📦 Yangi <b>main.py</b> faylini yuboring. Avval alohida jarayonda tekshiriladi, keyin tasdiq so'raladi. Eski fayl <code>main.py.bak</code> ga saqlanadi.",
    "addadmin": "👮 Yangi admin Telegram ID sini yozing:", "deladmin": "👮 O'chiriladigan admin ID sini yozing:",
}
SET_NAMES = {"start_balance": "Start balans", "ref_bonus": "Referal bonus", "daily_bonus": "Kunlik bonus",
             "liquidity": "Bozor chuqurligi", "vol": "Tebranish (global)", "support": "Support (@username)",
             "quest1": "Vazifa 1 mukofoti", "quest2": "Vazifa 2 mukofoti", "quest3": "Vazifa 3 mukofoti",
             "news_every": "Yangilik oralig'i (daqiqa)"}
TOGGLES = {"bcast_on": "Soatlik narx xabari", "news_push": "Yangiliklarni yuborish",
           "btn_color": "Rangli tugmalar", "maintenance": "Texnik ish rejimi"}
COLORS = ["primary", "success", "danger"]
COLOR_ICON = {"primary": "🔵", "success": "🟢", "danger": "🔴"}


def onoff(v):
    return "✅ yoqilgan" if str(v) == "1" else "⛔ o'chirilgan"


def adm_user_card(uid):
    u = get_user(uid)
    if not u:
        return "Topilmadi", kb([b("⬅ Admin", "adm:menu")])
    hold = ", ".join(f"{COINS[h['cid']]['symbol']}×{h['qty']}" for h in holdings_of(uid) if h["cid"] in COINS) or "—"
    nw = net_worth(uid)
    text = (f"👤 <b>{esc(u['name'])}</b> {'🚫' if u['banned'] else ''}\n🆔 <code>{uid}</code> · @{u['tg_username'] or '—'}\n"
            f"💵 Hamyon: {m(u['cash'])}\n💰 Jami: {m(nw)}\n📊 Daromad: {sg(nw - u['base'])}\n"
            f"📦 {hold}\n⭐ Donat: {u['donated']} · 👥 Takliflar: {u['ref_count']} · 🔁 Savdolar: {u['trades']}\n"
            f"🏷 Unvon: {u['title'] or '—'} · Oxirgi faollik: "
            f"{datetime.fromtimestamp(u['last_seen']).strftime('%d.%m %H:%M') if u['last_seen'] else '—'}")
    return text, kb([b("➕ Balans", f"adm:input:bal+:{uid}"), b("➖ Balans", f"adm:input:bal-:{uid}")],
                    [b("✉️ Xabar", f"adm:input:dm:{uid}"), b("🏷 Unvon", f"adm:input:title:{uid}")],
                    [b("✅ Blokdan chiqarish" if u["banned"] else "🚫 Bloklash", f"adm:ban:{uid}"), b("🔑 PIN", f"adm:input:pin:{uid}")],
                    [b("⬅ Foydalanuvchilar", "adm:users")])


def adm_view(name, arg="", uid=0):
    back = [b("⬅ Admin", "adm:menu")]
    if name == "stats":
        day = time.time() - 86400
        st = q1("SELECT COUNT(*) n, SUM(banned) bn, SUM(cash) cs FROM users")
        new = q1("SELECT COUNT(*) n FROM users WHERE created>?", day)["n"]
        act = q1("SELECT COUNT(*) n FROM users WHERE last_seen>?", day)["n"]
        tr = q1("SELECT COUNT(*) n, SUM(CASE WHEN ts>? THEN 1 ELSE 0 END) d FROM trades", day)
        pay = q1("SELECT COUNT(*) n, SUM(stars) s FROM payments WHERE refunded=0")
        text = (f"📊 <b>Statistika</b>\n━━━━━━━━━━━━━━\n👥 Foydalanuvchilar: <b>{st['n']}</b> (🚫 {st['bn'] or 0})\n"
                f"🆕 24 soatda: <b>{new}</b> · 🟢 faol: <b>{act}</b>\n💵 Aylanmadagi pul: {m(st['cs'] or 0)}\n"
                f"🔁 Savdolar: <b>{tr['n']}</b> (24s: {tr['d'] or 0})\n⭐ To'lovlar: <b>{pay['n']}</b> · {pay['s'] or 0} Stars\n"
                f"🟢 Jonli ekranlar: {len(LIVE)} · 🧩 Menyular: {q1('SELECT COUNT(*) n FROM menus')['n']}")
        return text, kb([b("🔄", "adm:stats")], back)

    if name == "coins":
        lines = [f"{'✅' if c['active'] else '⛔'} {c['emoji']} <b>{esc(c['name'])}</b> ({c['symbol']}) — ${c['price']:,.2f}" for c in COINS.values()]
        rows = [[b(f"{c['emoji']} {c['symbol']}", f"adm:c:{c['id']}")] for c in COINS.values()]
        return "🪙 <b>Coinlar</b>\n━━━━━━━━━━━━━━\n" + "\n".join(lines), kb(*rows, [b("➕ Yangi coin", "adm:input:addcoin")], back)

    if name == "c":
        c = COINS[int(arg)]
        holders = q1("SELECT COUNT(*) n, SUM(qty) s FROM holdings WHERE cid=? AND qty>0", c["id"])
        text = (f"{c['emoji']} <b>{esc(c['name'])}</b> ({c['symbol']})\n💲 Narx: <b>${c['price']:,.2f}</b> (asos: ${c['base']:,.2f})\n"
                f"📈 Tebranish: ×{c['vol']}\n👥 Egalar: {holders['n']} · jami {holders['s'] or 0} ta\nHolat: {'✅ savdoda' if c['active'] else '⛔ o`chirilgan'}")
        i = c["id"]
        return text, kb([b("💲 Narx", f"adm:input:price:{i}"), b("📈 Tebranish", f"adm:input:vol:{i}"), b("✏️ Nom/emoji", f"adm:input:coinedit:{i}")],
                        [b("🚀 +5%", f"adm:shock:{i}:5"), b("🚀 +10%", f"adm:shock:{i}:10"), b("💥 −5%", f"adm:shock:{i}:-5"), b("💥 −10%", f"adm:shock:{i}:-10")],
                        [b("📰 Yangilik e'lon qilish", f"adm:input:newsc:{i}")],
                        [b("⛔ O'chirish" if c["active"] else "✅ Yoqish", f"adm:tog:{i}"), b("🗑 Butunlay o'chirish", f"adm:cdel:{i}")],
                        [b("⬅ Coinlar", "adm:coins")])

    if name == "users":
        page = int(arg or 0)
        n = q1("SELECT COUNT(*) n FROM users")["n"]
        rs = q("SELECT * FROM users ORDER BY created DESC LIMIT 8 OFFSET ?", page * 8)
        rows = [[b(f"{'🚫 ' if r_['banned'] else ''}{r_['name']} · {m(r_['cash'])}", f"adm:u:{r_['id']}")] for r_ in rs]
        nav = []
        if page > 0:
            nav.append(b("◀", f"adm:users:{page - 1}"))
        if (page + 1) * 8 < n:
            nav.append(b("▶", f"adm:users:{page + 1}"))
        return (f"👥 <b>Foydalanuvchilar</b> ({n})\n━━━━━━━━━━━━━━\nEng yangilari birinchi.",
                kb(*rows, nav, [b("🔎 Qidirish", "adm:input:finduser")], back))

    if name == "u":
        return adm_user_card(int(arg))

    if name == "bonus":
        ps = q("SELECT * FROM promos ORDER BY rowid DESC LIMIT 8")
        lines = [f"{'✅' if p['active'] else '⛔'} <code>{esc(p['code'])}</code> — {m(p['amount'])} · {p['used']}/{p['max_uses'] or '∞'}"
                 + (f" · {datetime.fromtimestamp(p['expires']).strftime('%d.%m')} gacha" if p["expires"] else "") for p in ps]
        rows = [[b(f"{'⛔' if p['active'] else '✅'} {p['code']}", f"adm:ptg:{p['code']}"), b("🗑", f"adm:pdel:{p['code']}")] for p in ps]
        return ("🎁 <b>Bonus va promo-kodlar</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Promo-kod yo'q"),
                kb([b("🎁 Hammaga bonus", "adm:input:giveall"), b("🎟 Promo yaratish", "adm:input:promo")], *rows, back))

    if name == "tour":
        ts = q("SELECT * FROM tours ORDER BY id DESC LIMIT 5")
        lines, rows = [], []
        for t_ in ts:
            n_pl = q1("SELECT COUNT(*) n FROM tour_players WHERE tid=?", t_["id"])["n"]
            lines.append(f"{'🟢' if t_['status'] == 'active' else '🏁'} #{t_['id']} <b>{esc(t_['name'])}</b> · {n_pl} kishi · {datetime.fromtimestamp(t_['ends']).strftime('%d.%m %H:%M')} gacha · 🎁 {esc(t_['prizes'])}")
            if t_["status"] == "active":
                rows.append([b(f"⏹ #{t_['id']} ni yakunlash", f"adm:tourend:{t_['id']}")])
        return ("🏁 <b>Turnirlar</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Turnir yo'q.") +
                "\n\n<i>Qatnashchilar turnir davomida topgan foydasi bo'yicha yarashadi. Muddat tugagach mukofotlar avtomatik beriladi.</i>",
                kb([b("➕ Yangi turnir", "adm:input:tour_new")], *rows, back))

    if name == "pay":
        ps = q("SELECT p.*, u.name FROM payments p LEFT JOIN users u ON u.id=p.uid ORDER BY p.id DESC LIMIT 8")
        pk = q("SELECT * FROM packages ORDER BY stars")
        lines = [f"{'↩️' if p['refunded'] else '⭐'} {p['stars']} · {esc(p['name'] or '?')} · {datetime.fromtimestamp(p['ts']).strftime('%d.%m %H:%M')}" for p in ps]
        text = ("⭐ <b>To'lovlar</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali to'lov yo'q") +
                "\n\n📦 <b>Paketlar</b>\n" + "\n".join(f"{p['stars']} ⭐ → {m(p['amount'])}" for p in pk) +
                "\n\n<i>Stars bot egasi hisobiga tushadi. Xato to'lovni ↩️ bilan qaytarishingiz mumkin.</i>")
        rows = [[b(f"🗑 {p['stars']}⭐ → {m(p['amount'])}", f"adm:pkdel:{p['id']}")] for p in pk]
        rf = [[b(f"↩️ Qaytarish: {p['stars']}⭐ {p['name'] or ''}", f"adm:rf:{p['id']}")] for p in ps if not p["refunded"]][:4]
        return text, kb(*rows, [b("➕ Paket", "adm:input:addpk")], *rf, back)

    if name == "set":
        lines = [f"• {n}: <code>{esc(cfg(k)) or '—'}</code>" for k, n in SET_NAMES.items()]
        lines += [f"• {n}: <b>{onoff(cfg(k))}</b>" for k, n in TOGGLES.items()]
        rows = [[b(f"✏️ {n}", f"adm:input:set:{k}")] for k, n in SET_NAMES.items()]
        rows = [rows[i] + (rows[i + 1] if i + 1 < len(rows) else []) for i in range(0, len(rows), 2)]
        tg = [[b(f"{'✅' if cfg(k) == '1' else '⛔'} {n}", f"adm:tg:{k}")] for k, n in TOGGLES.items()]
        return "⚙️ <b>Sozlamalar</b>\n━━━━━━━━━━━━━━\n" + "\n".join(lines), kb(*rows, *tg, back)

    if name == "emo":
        rows, row = [], []
        for i, ch in enumerate(UI_EMOJIS):
            row.append(b(f"{ch}{'✅' if ch in EMO else ''}", f"adm:input:emo:{i}"))
            if len(row) == 5:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        text = (f"🎨 <b>Premium emoji</b>\n━━━━━━━━━━━━━━\nAlmashtirmoqchi bo'lgan emojini bosing, keyin shu emoji o'rniga "
                f"<b>premium emoji</b> yuboring. Bot barcha menyu, xabar va tugmalarda uni avtomatik almashtiradi.\n\n"
                f"Almashtirilgan: <b>{len(EMO)}</b> ta ✅\n<i>Bot egasida Telegram Premium bo'lishi shart. Tugmalarda emoji tugma boshida ko'rinadi.</i>")
        return text, kb(*rows, [b("➕ Boshqa emoji", "adm:input:emo_new"), b("♻️ Hammasini tiklash", "adm:emoreset")], back)

    if name == "tx":
        rows = [[b(f"{'✏️' if k in TXT_OVERRIDE else '📄'} {v[0]}", f"adm:txk:{k}")] for k, v in TEXTS.items()]
        return ("📝 <b>Matnlar</b>\n━━━━━━━━━━━━━━\nBot matnlarini shu yerdan o'zgartiring. ✏️ — o'zgartirilgan.", kb(*rows, back))

    if name == "txk":
        cur = TXT_OVERRIDE.get(arg) or TEXTS[arg][1]
        text = (f"📝 <b>{esc(TEXTS[arg][0])}</b>\n━━━━━━━━━━━━━━\n<b>Hozirgi (ko'rinishi):</b>\n{cur[:1500]}")
        return text, kb([b("✏️ O'zgartirish", f"adm:input:tx:{arg}")], [b("♻️ Standartga qaytarish", f"adm:txr:{arg}")], [b("⬅ Matnlar", "adm:tx")])

    if name == "mn":
        ms = q("SELECT * FROM menus ORDER BY sort,id")
        lines = [f"{'✅' if x['active'] else '⛔'} #{x['id']} {esc(x['title'])} {COLOR_ICON.get(x['color'], '')}{'' if x['in_main'] else ' (yashirin)'}" for x in ms]
        rows = [[b(f"#{x['id']} {x['title']}", f"adm:mc:{x['id']}")] for x in ms]
        return ("🧩 <b>Menyular</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali menyu yo'q.\nYangi menyu qo'shing — u asosiy menyuda tugma bo'lib chiqadi.") +
                "\n\n<i>Har bir menyuga matn, rasm va rangli tugmalar qo'shish mumkin.</i>",
                kb(*rows, [b("➕ Yangi menyu", "adm:input:mn_title")], back))

    if name == "mc":
        x = q1("SELECT * FROM menus WHERE id=?", int(arg))
        if not x:
            return adm_view("mn")
        bs = q("SELECT * FROM mbtns WHERE menu_id=? ORDER BY sort,id", x["id"])
        bl = "\n".join(f"  {COLOR_ICON.get(y['color'], '')} {esc(y['label'])} → {y['kind']}:{esc(y['target'])}" for y in bs) or "  —"
        text = (f"🧩 <b>Menyu #{x['id']}</b>: {esc(x['title'])}\nRang: {COLOR_ICON.get(x['color'], '')} {x['color']} · Asosiy menyuda: {'✅' if x['in_main'] else '❌'} · Rasm: {'✅' if x['photo'] else '—'}\n\n"
                f"<b>Matn:</b>\n{x['text'][:600] or '—'}\n\n<b>Tugmalar:</b>\n{bl}")
        i = x["id"]
        return text, kb([b("✏️ Nom", f"adm:input:mn_t:{i}"), b("📝 Matn", f"adm:input:mn_b:{i}"), b("🖼 Rasm", f"adm:input:mn_p:{i}")],
                        [b(f"{COLOR_ICON.get(x['color'], '')} Rang", f"adm:mcol:{i}"), b("📍 Asosiy menyuda", f"adm:mmain:{i}"), b("🔼", f"adm:mup:{i}"), b("🔽", f"adm:mdn:{i}")],
                        [b("➕ Tugma qo'shish", f"adm:input:mb_add:{i}"), b("🗑 Tugma o'chirish", f"adm:mbl:{i}")],
                        [b("👁 Ko'rish", f"adm:mview:{i}"), b("⛔ O'chirish" if x["active"] else "✅ Yoqish", f"adm:mact:{i}"), b("🗑 Menyuni o'chirish", f"adm:mdel:{i}")],
                        [b("⬅ Menyular", "adm:mn")])

    if name == "mbl":
        bs = q("SELECT * FROM mbtns WHERE menu_id=? ORDER BY sort,id", int(arg))
        rows = [[b(f"🗑 {y['label']}", f"adm:mbd:{y['id']}:{arg}")] for y in bs]
        return "🗑 O'chiriladigan tugmani tanlang:", kb(*rows, [b("⬅ Menyu", f"adm:mc:{arg}")])

    if name == "tech":
        rows = [[b("📈 Tizim holati", "adm:sys"), b("📜 Loglar", "adm:logs")],
                [b("💾 Zaxira nusxa", "adm:backup"), b("👥 CSV eksport", "adm:csv")],
                [b("🧮 SQL (o'qish)", "adm:input:sql"), b("📒 Admin jurnali", "adm:alog")],
                [b("🔄 Qayta yuklash", "adm:reload"), b("🎲 Voqea yaratish", "adm:event")],
                [b(f"{'✅' if cfg('maintenance') == '1' else '⛔'} Texnik ish rejimi", "adm:tg:maintenance")],
                [b("🧩 Plaginlar (kod)", "adm:pl"), b("📦 main.py yangilash", "adm:input:selfupd")],
                [b("♻️ Qayta ishga tushirish", "adm:restart"), b("↩️ Oldingi main.py", "adm:rb")]]
        return ("🛠 <b>Texnik bo'lim</b>\n━━━━━━━━━━━━━━\nTizim holati, loglar, zaxira, SQL (faqat o'qish), adminlar boshqaruvi. "
                "Bot matnlari, menyular, emoji va narxlar — alohida bo'limlarda.", kb(*rows, back))

    if name == "pl":
        ps = q("SELECT * FROM plugins ORDER BY id")
        lines = [f"{'✅' if p_['enabled'] else ('⚠️' if p_['error'] else '⛔')} #{p_['id']} <b>{esc(p_['name'])}</b>" + (f"\n      <i>{esc(p_['error'][-120:])}</i>" if p_["error"] else "") for p_ in ps]
        rows = [[b(f"#{p_['id']} {p_['name']}", f"adm:plc:{p_['id']}")] for p_ in ps]
        return ("🧩 <b>Plaginlar</b>\n━━━━━━━━━━━━━━\nPlagin — bot ishlab turganda qo'shiladigan Python kodi: yangi buyruq, tugma, ekran yoki fon vazifa.\n\n"
                + ("\n".join(lines) or "Hali plagin yo'q."), kb(*rows, [b("➕ Yangi plagin", "adm:input:pl_new")], [b("⬅ Texnik", "adm:tech")]))

    if name == "plc":
        p_ = q1("SELECT * FROM plugins WHERE id=?", int(arg))
        if not p_:
            return adm_view("pl")
        state_ = "✅ ishlayapti" if p_["enabled"] else "⛔ o'chirilgan"
        text = (f"🧩 <b>{esc(p_['name'])}</b> · {state_}\nO'zgartirilgan: {datetime.fromtimestamp(p_['updated']).strftime('%d.%m %H:%M')} · {len(p_['code'])} belgi"
                + (f"\n⚠️ <i>{esc(p_['error'])}</i>" if p_["error"] else "") + f"\n\n<pre>{esc(p_['code'][:700])}</pre>")
        i = p_["id"]
        return text, kb([b("✏️ Kodni almashtirish", f"adm:input:pl_code:{i}"), b("📄 Kodni olish", f"adm:plv:{i}")],
                        [b("⛔ O'chirish" if p_["enabled"] else "✅ Yoqish", f"adm:plt:{i}"), b("↩️ Oldingi versiya", f"adm:plr:{i}")],
                        [b("🗑 Butunlay o'chirish", f"adm:pld:{i}"), b("⬅ Plaginlar", "adm:pl")])

    if name == "restart":
        return ("♻️ <b>Qayta ishga tushirish</b>\nBot jarayoni qayta ishga tushadi (taxminan 5–10 soniya).",
                kb([b("✅ Ha, qayta ishga tushirish", "adm:restartgo")], [b("⬅ Texnik", "adm:tech")]))

    if name == "rb":
        has = os.path.exists(SELF + ".bak")
        return ("↩️ <b>Oldingi main.py</b>\n" + ("Zaxiradagi (<code>main.py.bak</code>) fayl tiklanadi va bot qayta ishga tushadi." if has else "Zaxira fayl hali yo'q."),
                kb(*([[b("✅ Tiklash", "adm:rbgo")]] if has else []), [b("⬅ Texnik", "adm:tech")]))

    if name == "selfq":
        return ("📦 <b>Yangi main.py tekshirildi ✅</b>\nAlmashtirilsinmi? Eski fayl <code>main.py.bak</code> ga saqlanadi va bot qayta ishga tushadi.",
                kb([b("✅ Almashtirish va qayta ishga tushirish", "adm:selfgo")], [b("✖ Bekor qilish", "adm:tech")]))

    if name == "admins":
        ex_ = sorted(admin_ids() - OWNERS)
        text = ("👮 <b>Adminlar</b>\n━━━━━━━━━━━━━━\n<b>Egalar:</b> " + (", ".join(f"<code>{i}</code>" for i in sorted(OWNERS)) or "—") +
                "\n<b>Qo'shimcha adminlar:</b> " + (", ".join(f"<code>{i}</code>" for i in ex_) or "—") +
                "\n\n<i>Qo'shimcha adminlar texnik bo'lim va adminlarni boshqara olmaydi.</i>")
        return text, kb([b("➕ Admin qo'shish", "adm:input:addadmin"), b("➖ Admin o'chirish", "adm:input:deladmin")], [b("⬅ Texnik", "adm:tech")])

    owner = is_owner(uid)
    n = q1("SELECT COUNT(*) n FROM users")["n"]
    rows = [[b("📊 Statistika", "adm:stats"), b("🪙 Coinlar", "adm:coins")],
            [b("👥 Foydalanuvchilar", "adm:users"), b("📣 Xabar yuborish", "adm:input:bcast")],
            [b("🎁 Bonus va promo", "adm:bonus"), b("⭐ To'lovlar", "adm:pay")],
            [b("🏁 Turnirlar", "adm:tour")],
            [b("🎨 Premium emoji", "adm:emo"), b("🧩 Menyular", "adm:mn")],
            [b("📝 Matnlar", "adm:tx"), b("⚙️ Sozlamalar", "adm:set")]]
    if owner:
        rows.append([b("🛠 Texnik bo'lim", "adm:tech")])
    rows.append([b("✖ Yopish", "adm:close")])
    return (f"🛠 <b>Admin panel</b>\n━━━━━━━━━━━━━━\n👥 {n} foydalanuvchi · 🪙 {len(COINS)} coin"
            f"{' · 🛠 <b>texnik ish rejimi</b>' if cfg('maintenance') == '1' else ''}", kb(*rows))


OWNER_ONLY = {"tech", "admins", "sys", "logs", "backup", "csv", "alog", "reload", "event", "pl", "plc", "plt", "pld", "plr", "plv",
              "restart", "restartgo", "rb", "rbgo", "selfq", "selfgo"}


@r.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await state.clear()
    text, markup = adm_view("menu", uid=msg.from_user.id)
    await msg.answer(text, reply_markup=markup)


async def push_news(c, pct, text):
    if cfg("news_push") != "1":
        return
    body = news_text(c, pct, text)
    for u in q("SELECT id FROM users WHERE banned=0 AND notif=1 AND last_seen>? LIMIT 400", time.time() - 6 * 3600):
        await safe_send(u["id"], body, kb([b("📊 Bozorga o'tish", "v:market")]))
        await asyncio.sleep(0.05)


def sql_readonly(query):
    qs = query.strip().rstrip(";")
    if not qs.lower().startswith("select") or ";" in qs:
        raise ValueError("Faqat bitta SELECT so'rovi ruxsat etiladi")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        cur = con.execute(qs)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(25)
    finally:
        con.close()
    hide = {i for i, c in enumerate(cols) if c.lower() in ("pin", "salt")}
    out = [" | ".join(cols)]
    for row in rows:
        out.append(" | ".join("***" if i in hide else str(v) for i, v in enumerate(row)))
    return "\n".join(out)[:3500]


@r.callback_query(F.data.startswith("adm:"))
async def adm_cb(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    parts = cb.data.split(":", 2)
    name, arg = parts[1], (parts[2] if len(parts) > 2 else "")
    await state.clear()
    if (name in OWNER_ONLY or (name == "input" and arg.split(":")[0] in ("sql", "addadmin", "deladmin", "pl_new", "pl_code", "selfupd"))
            or (name == "tg" and arg == "maintenance")) and not is_owner(uid):
        return await cb.answer("⛔ Faqat bot egasi uchun", show_alert=True)
    chat = cb.message.chat.id
    try:
        if name == "close":
            await cb.message.delete()
            return await cb.answer()
        if name == "input":
            act, _, a = arg.partition(":")
            await state.set_state(Adm.wait)
            await state.update_data(act=act, a=a)
            await show(cb, PROMPTS[act], kb([b("✖ Bekor qilish", "adm:menu")]))
            return await cb.answer()
        if name == "tog":
            c = COINS[int(arg)]
            c["active"] = 0 if c["active"] else 1
            save_coin(c)
            alog(uid, f"coin {c['symbol']} active={c['active']}")
            name = "c"
        elif name == "ban":
            ex("UPDATE users SET banned=1-banned, logged_in=CASE WHEN banned=0 THEN 0 ELSE logged_in END WHERE id=?", int(arg))
            alog(uid, f"ban toggle {arg}")
            name = "u"
        elif name == "pkdel":
            ex("DELETE FROM packages WHERE id=?", int(arg))
            name = "pay"
        elif name == "tg":
            if arg in TOGGLES:
                set_cfg(arg, "0" if cfg(arg) == "1" else "1")
                alog(uid, f"toggle {arg}={cfg(arg)}")
            name, arg = ("tech", "") if arg == "maintenance" else ("set", "")
        elif name == "shock":
            i, pct = arg.split(":")
            c, p, text = make_event(int(i), float(pct))
            alog(uid, f"shock {c['symbol']} {pct}%")
            asyncio.create_task(push_news(c, p, text))
            name, arg = "c", i
        elif name == "cdel":
            i = int(arg)
            if q1("SELECT 1 FROM holdings WHERE cid=? AND qty>0", i):
                return await cb.answer("⚠️ Bu coinning egalari bor. Avval ⛔ o'chirib qo'ying.", show_alert=True)
            for t_ in ("coins WHERE id", "alerts WHERE cid", "hist WHERE cid", "preds WHERE cid"):
                ex(f"DELETE FROM {t_}=?", i)
            COINS.pop(i, None)
            H1.pop(i, None)
            alog(uid, f"coin deleted {i}")
            name = "coins"
        elif name == "ptg":
            ex("UPDATE promos SET active=1-active WHERE code=?", arg)
            name = "bonus"
        elif name == "pdel":
            ex("DELETE FROM promos WHERE code=?", arg)
            name = "bonus"
        elif name == "rf":
            p = q1("SELECT * FROM payments WHERE id=? AND refunded=0", int(arg))
            if not p:
                return await cb.answer("To'lov topilmadi yoki qaytarilgan", show_alert=True)
            try:
                await bot.refund_star_payment(user_id=p["uid"], telegram_payment_charge_id=p["charge"])
            except Exception as e:
                return await cb.answer(f"⚠️ Qaytarib bo'lmadi: {str(e)[:150]}", show_alert=True)
            with tx():
                ex("UPDATE payments SET refunded=1 WHERE id=?", p["id"])
                ex("UPDATE users SET cash=round(MAX(cash-?,0),2), base=base-?, donated=MAX(donated-?,0) WHERE id=?",
                   p["amount"], p["amount"], p["stars"], p["uid"])
            alog(uid, f"refund {p['stars']} stars to {p['uid']}")
            await safe_send(p["uid"], f"↩️ {p['stars']} ⭐ to'lovingiz qaytarildi.")
            name = "pay"
        elif name == "emoreset":
            ex("DELETE FROM emojis")
            load_emojis()
            name = "emo"
        elif name == "txr":
            ex("DELETE FROM texts WHERE k=?", arg)
            load_texts()
            name = "txk"
        elif name == "mcol":
            x = q1("SELECT color FROM menus WHERE id=?", int(arg))
            ex("UPDATE menus SET color=? WHERE id=?", COLORS[(COLORS.index(x["color"]) + 1) % 3 if x["color"] in COLORS else 0], int(arg))
            name = "mc"
        elif name == "plt":
            p_ = q1("SELECT * FROM plugins WHERE id=?", int(arg))
            if p_["enabled"]:
                unload_plugin(p_["id"])
                ex("UPDATE plugins SET enabled=0 WHERE id=?", p_["id"])
            else:
                ex("UPDATE plugins SET enabled=1 WHERE id=?", p_["id"])
                ok, e_ = load_plugin(q1("SELECT * FROM plugins WHERE id=?", p_["id"]))
                if not ok:
                    await cb.answer("⚠️ Yuklanmadi: " + e_[-150:], show_alert=True)
            alog(uid, f"plugin toggle {p_['name']}")
            name = "plc"
        elif name == "plr":
            p_ = q1("SELECT * FROM plugins WHERE id=?", int(arg))
            if not p_["prev_code"]:
                return await cb.answer("Oldingi versiya yo'q", show_alert=True)
            ok, e_, _ = save_plugin(p_["name"], p_["prev_code"], p_["id"])
            alog(uid, f"plugin rollback {p_['name']}")
            name = "plc"
        elif name == "pld":
            p_ = q1("SELECT * FROM plugins WHERE id=?", int(arg))
            unload_plugin(p_["id"])
            ex("DELETE FROM plugins WHERE id=?", p_["id"])
            alog(uid, f"plugin deleted {p_['name']}")
            name = "pl"
        elif name == "plv":
            p_ = q1("SELECT * FROM plugins WHERE id=?", int(arg))
            await bot.send_document(chat, BufferedInputFile(p_["code"].encode("utf-8"), f"{p_['name']}.py"))
            return await cb.answer()
        elif name == "restartgo":
            alog(uid, "restart")
            await cb.answer("♻️ Qayta ishga tushmoqda...", show_alert=True)
            await bot.session.close()
            restart_process()
        elif name == "selfgo":
            new = SELF + ".new"
            if not os.path.exists(new):
                return await cb.answer("Yangi fayl topilmadi. Qayta yuboring.", show_alert=True)
            import shutil
            shutil.copy(SELF, SELF + ".bak")
            os.replace(new, SELF)
            alog(uid, "main.py replaced")
            await cb.answer("✅ Almashtirildi. Qayta ishga tushmoqda...", show_alert=True)
            await bot.session.close()
            restart_process()
        elif name == "rbgo":
            import shutil
            if not os.path.exists(SELF + ".bak"):
                return await cb.answer("Zaxira yo'q", show_alert=True)
            shutil.copy(SELF + ".bak", SELF)
            alog(uid, "main.py rollback")
            await cb.answer("↩️ Tiklandi. Qayta ishga tushmoqda...", show_alert=True)
            await bot.session.close()
            restart_process()
        elif name == "tourend":
            msgs = end_tours(int(arg))
            alog(uid, f"tour ended {arg}")
            for u_, t_ in msgs:
                asyncio.create_task(safe_send(u_, t_))
            name, arg = "tour", ""
        elif name == "mmain":
            ex("UPDATE menus SET in_main=1-in_main WHERE id=?", int(arg))
            name = "mc"
        elif name == "mact":
            ex("UPDATE menus SET active=1-active WHERE id=?", int(arg))
            name = "mc"
        elif name in ("mup", "mdn"):
            ids = [x["id"] for x in q("SELECT id FROM menus ORDER BY sort,id")]
            i = ids.index(int(arg))
            j = i - 1 if name == "mup" else i + 1
            if 0 <= j < len(ids):
                ids[i], ids[j] = ids[j], ids[i]
            for pos, mid in enumerate(ids):
                ex("UPDATE menus SET sort=? WHERE id=?", pos, mid)
            name = "mc"
        elif name == "mdel":
            ex("DELETE FROM mbtns WHERE menu_id=?", int(arg))
            ex("DELETE FROM menus WHERE id=?", int(arg))
            alog(uid, f"menu deleted {arg}")
            name = "mn"
        elif name == "mbd":
            bid, mid = arg.split(":")
            ex("DELETE FROM mbtns WHERE id=?", int(bid))
            name, arg = "mc", mid
        elif name == "mview":
            res = custom_menu(int(arg))
            if not res:
                return await cb.answer("Menyu topilmadi", show_alert=True)
            text, markup, photo = res
            if photo:
                await bot.send_photo(chat, photo, caption=text[:1024], reply_markup=markup)
            else:
                await bot.send_message(chat, text, reply_markup=markup)
            return await cb.answer("👁 Ko'rish uchun yuborildi")
        elif name == "backup":
            tmp = f"{DB_PATH}.bak"
            dst = sqlite3.connect(tmp)
            db.backup(dst)
            dst.close()
            with open(tmp, "rb") as f_:
                data = f_.read()
            os.remove(tmp)
            await bot.send_document(chat, BufferedInputFile(data, f"bozor-{datetime.now():%Y%m%d-%H%M}.db"), caption="💾 Zaxira nusxa")
            alog(uid, "backup")
            return await cb.answer("💾 Yuborildi")
        elif name == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "name", "username", "cash", "base", "donated", "trades", "created", "last_seen", "banned"])
            for u_ in q("SELECT * FROM users ORDER BY created"):
                w.writerow([u_["id"], u_["name"], u_["tg_username"], u_["cash"], u_["base"], u_["donated"], u_["trades"],
                            datetime.fromtimestamp(u_["created"]).isoformat(" ", "seconds"),
                            datetime.fromtimestamp(u_["last_seen"]).isoformat(" ", "seconds") if u_["last_seen"] else "", u_["banned"]])
            await bot.send_document(chat, BufferedInputFile(buf.getvalue().encode("utf-8-sig"), "users.csv"), caption="👥 Foydalanuvchilar")
            return await cb.answer("📤 Yuborildi")
        elif name == "logs":
            lines = list(LogBuf.buf)[-40:]
            await bot.send_message(chat, "📜 <b>Oxirgi loglar</b>\n<pre>" + esc("\n".join(lines) or "bo'sh")[-3500:] + "</pre>")
            return await cb.answer()
        elif name == "sys":
            import aiogram
            tot = q1("SELECT COUNT(*) n FROM users")["n"]
            size = os.path.getsize(DB_PATH) / 1024 / 1024 if os.path.exists(DB_PATH) else 0
            up = int(time.time() - START_TS)
            text = (f"📈 <b>Tizim holati</b>\n━━━━━━━━━━━━━━\n⏱ Ishlash vaqti: {up // 3600} soat {up % 3600 // 60} daq\n"
                    f"🐍 Python {platform.python_version()} · aiogram {aiogram.__version__}\n💾 Baza: {size:.2f} MB\n"
                    f"👥 Foydalanuvchilar: {tot} · 🟢 jonli ekran: {len(LIVE)}\n🪙 Coinlar: {len(COINS)} · 🎨 emoji: {len(EMO)} · 🧩 menyu: {q1('SELECT COUNT(*) n FROM menus')['n']}\n"
                    f"⚠️ Oxirgi xatolar: {sum(1 for l in LogBuf.buf if 'ERROR' in l)}")
            await show(cb, text, kb([b("🔄", "adm:sys"), b("⬅ Texnik", "adm:tech")]))
            return await cb.answer()
        elif name == "alog":
            rs = q("SELECT * FROM adminlog ORDER BY id DESC LIMIT 15")
            text = "📒 <b>Admin jurnali</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(
                f"{datetime.fromtimestamp(x['ts']).strftime('%d.%m %H:%M')} · <code>{x['admin']}</code> · {esc(x['action'])}" for x in rs) or "bo'sh")
            await show(cb, text, kb([b("⬅ Texnik", "adm:tech")]))
            return await cb.answer()
        elif name == "reload":
            load_texts()
            load_emojis()
            return await cb.answer("✅ Matnlar va emojilar qayta yuklandi", show_alert=True)
        elif name == "event":
            if not active_coins():
                return await cb.answer("Faol coin yo'q", show_alert=True)
            c, p, text = make_event()
            alog(uid, f"event {c['symbol']} {p:+.1f}%")
            asyncio.create_task(push_news(c, p, text))
            return await cb.answer(f"🎲 {c['symbol']} {p:+.1f}%", show_alert=True)
        text, markup = adm_view(name, arg, uid)
        await show(cb, text, markup)
    except (KeyError, ValueError, IndexError):
        return await cb.answer("⚠️ Xatolik", show_alert=True)
    await cb.answer()


def num(t):
    v = float(t.replace(",", ".").replace("$", "").strip())
    if v <= 0:
        raise ValueError
    return v


@r.message(Adm.wait)
async def adm_input(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if not is_admin(uid):
        return await state.clear()
    d = await state.get_data()
    act, a, x = d.get("act"), d.get("a", ""), d.get("x", "")
    has_text = bool(msg.text or msg.caption)
    t = (msg.text or msg.caption or "").strip()
    html = msg.html_text if has_text else ""
    await state.clear()
    back = kb([b("⬅ Admin", "adm:menu")])

    async def retry(note="⚠️ Format noto'g'ri yoki qiymat mos emas. Qayta yuboring yoki ✖ Bekor qiling."):
        await state.set_state(Adm.wait)
        await state.update_data(act=act, a=a, x=x)
        await msg.answer(note, reply_markup=kb([b("✖ Bekor qilish", "adm:menu")]))

    async def card(view_name, arg="", note=""):
        text, markup = adm_view(view_name, arg, uid)
        await msg.answer((note + "\n\n" if note else "") + text, reply_markup=markup)

    try:
        if act in ("sql", "addadmin", "deladmin", "pl_new", "pl_code", "selfupd") and not is_owner(uid):
            return await msg.answer("⛔ Faqat bot egasi uchun.")
        if act == "price":
            c = COINS[int(a)]
            c["price"] = c["base"] = round(num(t), 2)
            H1[c["id"]].append((time.time(), c["price"]))
            save_coin(c)
            alog(uid, f"price {c['symbol']}={c['price']}")
            return await card("c", a, f"✅ Narx: ${c['price']:,.2f}")
        if act == "vol":
            v = num(t)
            assert 0.1 <= v <= 5
            c = COINS[int(a)]
            c["vol"] = v
            save_coin(c)
            return await card("c", a, f"✅ Tebranish: ×{v}")
        if act == "addcoin":
            nm, sym, emo, pr = [x_.strip() for x_ in t.split("|")]
            pr = num(pr)
            assert nm and sym and emo
            cur = ex("INSERT INTO coins(symbol,name,emoji,price,base) VALUES(?,?,?,?,?)", sym.upper(), nm, emo, pr, pr)
            c = dict(q1("SELECT * FROM coins WHERE id=?", cur.lastrowid))
            COINS[c["id"]], H1[c["id"]], MOM[c["id"]] = c, deque([(time.time(), pr)], maxlen=720), 0.0
            alog(uid, f"coin added {sym}")
            return await card("c", str(c["id"]), "✅ Coin qo'shildi")
        if act == "coinedit":
            nm, sym, emo = [x_.strip() for x_ in t.split("|")]
            c = COINS[int(a)]
            c.update(name=nm, symbol=sym.upper(), emoji=emo)
            save_coin(c)
            return await card("c", a, "✅ Saqlandi")
        if act == "newsc":
            pct_s, text = [x_.strip() for x_ in t.split("|", 1)]
            c, p, tx_ = make_event(int(a), float(pct_s.replace(",", ".").replace("+", "")), text)
            alog(uid, f"news {c['symbol']} {p:+.1f}%")
            asyncio.create_task(push_news(c, p, tx_))
            return await card("c", a, "✅ Yangilik e'lon qilindi")
        if act == "finduser":
            u = get_user(int(t)) if t.isdigit() else (q1("SELECT * FROM users WHERE name_lc=?", t.lower()) or q1("SELECT * FROM users WHERE name_lc LIKE ?", f"%{t.lower()}%"))
            if not u:
                return await msg.answer("❌ Topilmadi", reply_markup=back)
            text, markup = adm_user_card(u["id"])
            return await msg.answer(text, reply_markup=markup)
        if act in ("bal+", "bal-"):
            v, target = num(t), int(a)
            if act == "bal-":
                v = -min(v, get_user(target)["cash"])
            ex("UPDATE users SET cash=round(cash+?,2), base=base+? WHERE id=?", v, v, target)
            alog(uid, f"balance {v:+.2f} -> {target}")
            await safe_send(target, f"{'🎁' if v > 0 else '⚖️'} Balansingiz o'zgardi: <b>{'+' if v > 0 else '−'}{m(abs(v))}</b>")
            text, markup = adm_user_card(target)
            return await msg.answer("✅ Bajarildi\n\n" + text, reply_markup=markup)
        if act == "dm":
            ok = await safe_send(int(a), html or esc(t))
            return await msg.answer("✅ Yuborildi" if ok else "⚠️ Yetkazib bo'lmadi", reply_markup=back)
        if act == "title":
            ex("UPDATE users SET title=? WHERE id=?", "" if t == "-" else t[:24], int(a))
            text, markup = adm_user_card(int(a))
            return await msg.answer("✅ Saqlandi\n\n" + text, reply_markup=markup)
        if act == "reply":
            ok = await safe_send(int(a), "💬 <b>Admin javobi:</b>\n" + (html or esc(t)), kb([b("🆘 Yana yozish", "v:support"), *MENU_BTN]))
            return await msg.answer("✅ Javob yuborildi" if ok else "⚠️ Yetkazib bo'lmadi", reply_markup=back)
        if act == "bcast":
            assert has_text or msg.photo
            asyncio.create_task(broadcast_text(html, uid, msg.photo[-1].file_id if msg.photo else None))
            alog(uid, "broadcast")
            return await msg.answer("📣 Yuborish boshlandi. Tugagach xabar beraman.", reply_markup=back)
        if act == "giveall":
            v = num(t)
            ex("UPDATE users SET cash=round(cash+?,2), base=base+? WHERE banned=0", v, v)
            alog(uid, f"giveall {v}")
            asyncio.create_task(broadcast_text(f"🎁 Sizga <b>{m(v)}</b> bonus berildi! Rahmat, biz bilan qolganingiz uchun.", uid))
            return await msg.answer(f"✅ Hammaga {m(v)} qo'shildi.", reply_markup=back)
        if act == "promo":
            p = [x_.strip() for x_ in t.split("|")]
            code = p[0].upper()
            assert re.fullmatch(r"[A-Z0-9_\-]{3,20}", code)
            amount, mx, days = num(p[1]), int(p[2]) if len(p) > 2 else 0, int(p[3]) if len(p) > 3 else 0
            ex("INSERT OR REPLACE INTO promos(code,amount,max_uses,used,expires,active) VALUES(?,?,?,0,?,1)",
               code, amount, mx, time.time() + days * 86400 if days > 0 else 0)
            return await card("bonus", "", f"✅ Promo-kod yaratildi: <code>{code}</code>")
        if act == "addpk":
            s_, am = [float(x_.replace(",", ".")) for x_ in t.split("|")]
            assert s_ >= 1 and am > 0
            ex("INSERT INTO packages(stars,amount) VALUES(?,?)", int(s_), am)
            return await card("pay", "", "✅ Paket qo'shildi")
        if act == "set":
            if a != "support":
                assert float(t.replace(",", ".")) >= 0
            set_cfg(a, t.replace(",", ".") if a != "support" else t)
            alog(uid, f"set {a}={t}")
            return await card("set", "", "✅ Saqlandi")
        if act == "pin":
            assert t.isdigit() and len(t) == 4
            salt = secrets.token_hex(8)
            ex("UPDATE users SET salt=?, pin=?, fails=0, lock_until=0 WHERE id=?", salt, hash_pin(salt, t), int(a))
            return await msg.answer("✅ PIN yangilandi", reply_markup=back)
        if act == "emo_new":
            assert t and len(t) <= 8 and not t.isascii()
            x = "c" + t
            act, a = "emo", x
            await state.set_state(Adm.wait)
            await state.update_data(act="emo", a=x)
            return await msg.answer(PROMPTS["emo"], reply_markup=kb([b("✖ Bekor qilish", "adm:emo")]))
        if act == "emo":
            ch = UI_EMOJIS[int(a)] if a.isdigit() else a[1:]
            ent = next((e for e in (msg.entities or []) if e.type == "custom_emoji"), None)
            if not ent:
                return await retry("⚠️ Premium emoji topilmadi. Faqat <b>premium</b> emoji yuboring (matn bilan emas).")
            set_emoji(ch, ent.custom_emoji_id)
            alog(uid, f"emoji {ch} -> {ent.custom_emoji_id}")
            return await card("emo", "", f"✅ {ch} endi premium emoji bilan almashtiriladi!")
        if act == "mn_title":
            assert t and len(t) <= 40
            x = t
            act = "mn_body"
            await state.set_state(Adm.wait)
            await state.update_data(act="mn_body", a="", x=x)
            return await msg.answer(PROMPTS["mn_body"], reply_markup=kb([b("✖ Bekor qilish", "adm:mn")]))
        if act == "mn_body":
            assert has_text
            sort = (q1("SELECT COALESCE(MAX(sort),0)+1 n FROM menus")["n"])
            cur = ex("INSERT INTO menus(title,text,sort) VALUES(?,?,?)", x, html, sort)
            alog(uid, f"menu created {x}")
            return await card("mc", str(cur.lastrowid), "✅ Menyu yaratildi! Endi tugma va rasm qo'shing.")
        if act == "mn_t":
            assert t and len(t) <= 40
            ex("UPDATE menus SET title=? WHERE id=?", t, int(a))
            return await card("mc", a, "✅ Saqlandi")
        if act == "mn_b":
            assert has_text
            ex("UPDATE menus SET text=? WHERE id=?", html, int(a))
            return await card("mc", a, "✅ Saqlandi")
        if act == "mn_p":
            if msg.photo:
                ex("UPDATE menus SET photo=? WHERE id=?", msg.photo[-1].file_id, int(a))
            elif t == "-":
                ex("UPDATE menus SET photo='' WHERE id=?", int(a))
            else:
                raise ValueError
            return await card("mc", a, "✅ Saqlandi")
        if act == "mb_add":
            p = [x_.strip() for x_ in t.split("|")]
            label, kind, target = p[0], p[1].lower(), p[2]
            color = p[3].lower() if len(p) > 3 and p[3] else "primary"
            assert label and color in COLORS
            if kind == "url":
                assert target.startswith(("http://", "https://", "tg://"))
            elif kind == "menu":
                assert q1("SELECT 1 FROM menus WHERE id=?", int(target))
            elif kind == "view":
                assert target in VIEWS
            else:
                raise ValueError
            sort = q1("SELECT COALESCE(MAX(sort),0)+1 n FROM mbtns WHERE menu_id=?", int(a))["n"]
            ex("INSERT INTO mbtns(menu_id,label,kind,target,color,sort) VALUES(?,?,?,?,?,?)", int(a), label[:40], kind, target, color, sort)
            return await card("mc", a, "✅ Tugma qo'shildi")
        if act == "pl_new":
            assert re.fullmatch(r"[a-z][a-z0-9_]{2,23}", t) and not q1("SELECT 1 FROM plugins WHERE name=?", t)
            await state.set_state(Adm.wait)
            await state.update_data(act="pl_code", a="", x=t)
            return await msg.answer(PROMPTS["pl_code"], reply_markup=kb([b("✖ Bekor qilish", "adm:pl")]))
        if act in ("pl_code", "selfupd"):
            raw = None
            if msg.document:
                assert (msg.document.file_size or 0) < 2_000_000
                buf = await bot.download(msg.document, destination=io.BytesIO())
                raw = buf.getvalue()
            elif act == "pl_code" and msg.text:
                raw = msg.text.encode("utf-8")
            assert raw
            code = raw.decode("utf-8")
            if act == "selfupd":
                err = check_code(code, "main.py") or ("" if "async def main" in code else "main() topilmadi")
                if not err:
                    with open(SELF + ".new", "wb") as f_:
                        f_.write(raw)
                    err = await asyncio.get_running_loop().run_in_executor(None, verify_new_main, SELF + ".new")
                if err:
                    return await retry(f"⚠️ Yangi fayl yaroqsiz:\n<code>{esc(err)}</code>")
                alog(uid, f"main.py uploaded sha={hashlib.sha256(raw).hexdigest()[:12]} {len(raw)}B")
                return await card("selfq")
            ok, e_, pid = save_plugin(x or q1("SELECT name FROM plugins WHERE id=?", int(a))["name"], code, int(a) if a else None)
            alog(uid, f"plugin {'updated' if a else 'created'} id={pid} sha={hashlib.sha256(raw).hexdigest()[:12]}")
            return await card("plc", str(pid), "✅ Plagin ishga tushdi!" if ok else f"⚠️ Saqlandi, lekin yuklanmadi:\n<code>{esc(e_)}</code>")
        if act == "tour_new":
            p_ = [x_.strip() for x_ in t.split("|")]
            nm, hours = p_[0], float(p_[1])
            prizes = [str(num(x_)) for x_ in p_[2:5]]
            assert nm and 0.1 <= hours <= 24 * 60 and prizes
            tid = ex("INSERT INTO tours(name,starts,ends,prizes) VALUES(?,?,?,?)", nm, time.time(), time.time() + hours * 3600, ",".join(prizes)).lastrowid
            alog(uid, f"tour created {nm}")
            asyncio.create_task(broadcast_text(f"🏁 <b>Yangi turnir: {esc(nm)}!</b>\nMukofotlar: " + " · ".join(m(float(x_)) for x_ in prizes) +
                                               "\n🎁 Bonuslar → 🏁 Turnir bo'limida qatnashing!", uid))
            return await card("tour", "", "✅ Turnir boshlandi, e'lon yuborilmoqda")
        if act == "tx":
            assert has_text and a in TEXTS
            ex("INSERT INTO texts(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", a, html)
            load_texts()
            alog(uid, f"text {a} changed")
            return await card("txk", a, "✅ Matn yangilandi")
        if act == "sql":
            try:
                res = sql_readonly(t)
            except (sqlite3.Error, ValueError) as e:
                return await retry(f"⚠️ {esc(str(e))}")
            alog(uid, f"sql: {t[:120]}")
            return await msg.answer(f"<pre>{esc(res)}</pre>", reply_markup=kb([b("🧮 Yana", "adm:input:sql"), b("⬅ Texnik", "adm:tech")]))
        if act in ("addadmin", "deladmin"):
            tid = int(t)
            cur_ = {i for i in admin_ids() - OWNERS}
            (cur_.add if act == "addadmin" else cur_.discard)(tid)
            set_cfg("extra_admins", ",".join(str(i) for i in sorted(cur_)))
            alog(uid, f"{act} {tid}")
            return await card("admins", "", "✅ Saqlandi")
    except (ValueError, AssertionError, KeyError, IndexError, TypeError, sqlite3.Error):
        return await retry()
    await msg.answer("⚠️ Noma'lum amal.", reply_markup=back)


# ───────────────────────── XABAR YUBORISH ─────────────────────────
async def safe_send(uid, text, markup=None, photo=None):
    """True — yetkazildi. Bot bloklangan bo'lsa xabarnoma o'chiriladi."""
    try:
        if photo:
            await bot.send_photo(uid, photo, caption=text[:1024], reply_markup=markup)
        else:
            await bot.send_message(uid, text, reply_markup=markup)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        return await safe_send(uid, text, markup, photo)
    except TelegramForbidden:
        ex("UPDATE users SET notif=0 WHERE id=?", uid)
    except Exception:
        pass
    return False


async def broadcast_text(text, admin_id, photo=None):
    ok = total = 0
    for u in q("SELECT id FROM users WHERE banned=0"):
        total += 1
        ok += await safe_send(u["id"], f"📣 {text}", None, photo)
        await asyncio.sleep(0.05)
    await safe_send(admin_id, f"✅ Xabar {ok}/{total} kishiga yetkazildi.")


async def hourly():
    while True:
        await asyncio.sleep(BCAST_EVERY)
        if cfg("bcast_on") != "1":
            continue
        for u in q("SELECT id FROM users WHERE banned=0 AND notif=1"):
            try:
                lines = "\n".join(f"{c['emoji']} {esc(c['name'])}  <b>${c['price']:,.2f}</b>  {pc(ch1h(c))}" for c in active_coins())
                nw = net_worth(u["id"])
                base = get_user(u["id"])["base"]
                text = (f"🕐 <b>Soatlik narxlar</b> · {clock()[:5]}\n━━━━━━━━━━━━━━\n{lines}\n\n"
                        f"💰 Balansingiz: <b>{m(nw)}</b> ({sg(nw - base)})\n<i>Narxlar harakatda — imkoniyatni qo'ldan boy bermang!</i>")
                await safe_send(u["id"], text, kb([b("📊 Bozorga o'tish", "v:market")], [b("🔕 Xabarnomani o'chirish", "tgl")]))
            except Exception:
                log.exception("hourly")
            await asyncio.sleep(0.05)


# ───────────────────────── FON JARAYONLARI ─────────────────────────
async def resolve_preds():
    for p in q("SELECT * FROM preds WHERE due<=?", time.time()):
        c = COINS.get(p["cid"])
        win = False
        with tx():
            ex("DELETE FROM preds WHERE id=?", p["id"])
            if not c:
                pay, res = p["bet"], "⚠️ Coin topilmadi — tikish qaytarildi"
            elif c["price"] == p["p0"]:
                pay, res = p["bet"], "🤝 Narx o'zgarmadi — tikish qaytarildi"
            elif (c["price"] > p["p0"]) == (p["dir"] == "u"):
                pay, win, res = round(p["bet"] * 1.9, 2), True, f"🎉 <b>To'g'ri topdingiz! +{m(p['bet'] * 0.9)}</b>"
            else:
                pay, res = 0, f"😕 <b>Topolmadingiz −{m(p['bet'])}</b>"
            credit(p["uid"], pay)
            if win:
                ex("UPDATE users SET wins=wins+1 WHERE id=?", p["uid"])
        now_p = f"{c['emoji']} {esc(c['name'])}: ${p['p0']:,.2f} → <b>${c['price']:,.2f}</b>\n" if c else ""
        await safe_send(p["uid"], f"🔮 <b>Bashorat natijasi</b>\n{now_p}{res}",
                        kb([b("🔁 Yana", "v:g:pred"), b("⬅ Menyu", "v:menu")]))


async def fire_alerts():
    for a, c in check_alerts():
        arrow = "📈 oshdi" if a["dir"] == "u" else "📉 tushdi"
        await safe_send(a["uid"], f"🔔 <b>Narx ogohlantirishi</b>\n{c['emoji']} {esc(c['name'])} {arrow}: <b>${c['price']:,.2f}</b>\n"
                                  f"(maqsad: ${a['target']:,.2f})",
                        kb([b("🟢 Olish", f"t:b:{c['id']}"), b("🔴 Sotish", f"t:s:{c['id']}")], [b("📊 Bozor", "v:market")]))


async def fire_orders():
    for uid_, text in check_orders():
        await safe_send(uid_, text, kb([b("💼 Portfel", "v:port"), b("🎯 Buyurtmalar", "v:orders")]))


async def fire_misc():
    for uid_, text in end_tours() + mature_deposits():
        await safe_send(uid_, text, kb([b("🏁 Turnir", "v:tour"), b("⬅ Menyu", "v:menu")]))


async def push_live():
    now = time.time()
    for uid, e in list(LIVE.items()):
        expired = e["exp"] < now
        if expired:
            LIVE.pop(uid, None)
        try:
            note = "⏸ <i>Jonli yangilanish to'xtadi. 🔄 ni bosing.</i>" if expired else e.get("note", "")
            text, markup = view(uid, e["name"], e["arg"], note)
            if text != e["last"]:
                await bot.edit_message_text(text, chat_id=e["chat"], message_id=e["mid"], reply_markup=markup)
                e["last"] = text
        except TelegramRetryAfter as ex_:
            await asyncio.sleep(ex_.retry_after)
        except Exception:
            LIVE.pop(uid, None)
        await asyncio.sleep(0.03)


async def engine():
    last_min, next_event = 0.0, time.time() + cfgf("news_every") * 60
    while True:
        await asyncio.sleep(TICK)
        try:
            tick()
            now = time.time()
            if now - last_min >= 60:
                persist_hist()
                last_min = now
                for k in [k for k, t in CD.items() if now - t > 86400]:
                    CD.pop(k, None)
                ex("DELETE FROM daily WHERE day<?", (datetime.now().date().fromordinal(datetime.now().date().toordinal() - 7)).isoformat())
            if now >= next_event:
                next_event = now + cfgf("news_every") * 60 * random.uniform(0.6, 1.4)
                if active_coins():
                    c, p, text = make_event()
                    asyncio.create_task(push_news(c, p, text))
            await resolve_preds()
            await fire_alerts()
            await fire_orders()
            await fire_misc()
            await run_plugin_ticks()
            await push_live()
        except Exception:
            log.exception("engine")


# ───────────────────────── BOSHQA XABARLAR ─────────────────────────
@r.message(StateFilter(None))
async def fallback(msg: Message):
    u = get_user(msg.from_user.id)
    if cfg("maintenance") == "1" and not is_admin(msg.from_user.id):
        return await msg.answer("🛠 Texnik ishlar ketmoqda. Birozdan keyin urinib ko'ring.")
    if u and u["logged_in"] and not u["banned"]:
        seen(u["id"])
        await send_menu(msg.chat.id, u["id"])
    else:
        await msg.answer("👋 Boshlash uchun /start ni bosing.")


async def main():
    global bot, BOT_USERNAME
    h = LogBuf()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(), h])
    print("Bot ishga tushmoqda...", flush=True)
    if not TOKEN or ":" not in TOKEN:
        raise SystemExit("❌ BOT_TOKEN yozilmagan! Faylning boshidagi BOT_TOKEN = \"...\" qatoriga @BotFather bergan tokenni yozing.")
    if not OWNERS:
        print("⚠️ ADMIN_ID yozilmagan — admin panel ishlamaydi. Faylning boshiga o'z Telegram ID'ingizni yozing.", flush=True)
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot.session.middleware(PremiumMW())
    BOT_USERNAME = (await bot.get_me()).username
    load_coins()
    load_texts()
    load_emojis()
    dp = Dispatcher()
    r.callback_query.outer_middleware(Gate())
    PLUG.callback_query.outer_middleware(Gate())
    dp.include_router(PLUG)     # plaginlar asosiy router (fallback) dan oldin tekshiriladi
    dp.include_router(r)
    load_all_plugins()
    tasks = [asyncio.create_task(engine()), asyncio.create_task(hourly())]
    log.info("Bot ishga tushdi: @%s | egalar: %s", BOT_USERNAME, sorted(OWNERS) or "YO'Q (ADMIN_IDS ni o'rnating)")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "pre_checkout_query"])
    finally:
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e_:
        if isinstance(e_, SystemExit) and e_.code:
            print(e_.code, flush=True)
    except Exception:
        import traceback
        print("❌ Bot xato bilan to'xtadi:\n" + traceback.format_exc(), flush=True)
        raise

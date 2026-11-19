# -*- coding: utf-8 -*-
"""
💎 Virtual Bozor — Telegram o'yin boti (aiogram 3.x)
Virtual coinlar bilan savdo o'yini. Hamma balans va foyda faqat o'yin ichida.

Ishga tushirish:
    export BOT_TOKEN="9082119671:AAFuN0EVlR41Fj-Y4pZ7M5CF2m2P-WVPqCE"
    export ADMIN_IDS="8681116778,8681116778"
    python main.py
"""
import asyncio
import hashlib
import io
import logging
import os
import random
import re
import secrets
import sqlite3
import time
from collections import deque
from datetime import datetime
from html import escape as esc
from urllib.parse import quote

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbidden, TelegramRetryAfter
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
TOKEN = os.getenv("BOT_TOKEN", "")
ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
DB_PATH = os.getenv("DB_PATH", "bozor.db")
TICK = 5                 # narx yangilanishi (soniya)
LIVE_TTL = 90            # ekran qancha vaqt jonli yangilanadi (soniya)
BCAST_EVERY = 3600       # narx xabarnomasi (soniya)

DEF = {  # admin panelidan o'zgartiriladi
    "start_balance": "100", "ref_bonus": "10", "daily_bonus": "100",
    "liquidity": "50000", "vol": "1", "support": "", "bcast_on": "1",
}
SHOP = [  # (kalit, nomi, narxi)
    ("trader", "🥉 Treyder", 5000),
    ("pro", "🥈 Pro", 25000),
    ("whale", "🐳 Kit", 100000),
    ("legend", "👑 Afsona", 500000),
]
BETS = [10, 50, 100, 500]

log = logging.getLogger("bozor")
bot: Bot = None  # main() da yaratiladi
BOT_USERNAME = ""

# ───────────────────────── BAZA ─────────────────────────
db = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
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
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, stars INTEGER, amount REAL, charge TEXT UNIQUE, ts REAL);
CREATE TABLE IF NOT EXISTS packages(id INTEGER PRIMARY KEY AUTOINCREMENT, stars INTEGER, amount REAL);
CREATE TABLE IF NOT EXISTS preds(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, cid INTEGER, dir TEXT, bet REAL, p0 REAL, due REAL);
""")


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


def net_worth(uid):
    u = get_user(uid)
    return u["cash"] + portfolio_value(uid)


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
    # bozor ta'siri: sotib olinsa narx ko'tariladi, sotilsa tushadi
    imp = min(total / max(cfgf("liquidity"), 1), 0.08)
    c["price"] = round(max(price * (1 + imp if side == "b" else 1 - imp), 0.5), 2)
    H1[cid].append((time.time(), c["price"]))
    save_coin(c)
    return True, note


# ───────────────────────── TUGMALAR ─────────────────────────
def b(text, cb):
    return InlineKeyboardButton(text=text, callback_data=cb)


def ub(text, url):
    return InlineKeyboardButton(text=text, url=url)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def support_url():
    s = cfg("support").strip()
    if s:
        return "https://t.me/" + s.lstrip("@") if not s.startswith("http") else s
    if ADMINS:
        return f"tg://user?id={min(ADMINS)}"
    return None


def support_btn():
    u = support_url()
    return [ub("🆘 Adminga murojaat", u)] if u else []


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
    for u in q("SELECT * FROM users WHERE banned=0"):
        rows.append((u["cash"] + hold.get(u["id"], 0) - u["base"], u))
    rows.sort(key=lambda x: -x[0])
    TOP_CACHE.update(ts=time.time(), rows=rows)
    return rows


def view(uid, name, arg="", note=""):
    """Har bir ekran: (matn, klaviatura)."""
    u = get_user(uid)
    foot = f"\n\n{note}" if note else ""

    if name == "menu":
        pv = portfolio_value(uid)
        profit = u["cash"] + pv - u["base"]
        text = (f"💎 <b>Virtual Bozor</b>\n━━━━━━━━━━━━━━\n"
                f"👤 {tag(u)}<b>{esc(u['name'])}</b>\n\n"
                f"💵 Hamyon: <b>{m(u['cash'])}</b>\n"
                f"📦 Coinlar: <b>{m(pv)}</b>\n"
                f"💰 Jami: <b>{m(u['cash'] + pv)}</b>\n"
                f"📊 Daromad: {sg(profit)}{foot}")
        return text, kb(
            [b("📊 Bozor", "v:market"), b("💼 Portfel", "v:port")],
            [b("📈 Narxlar", "v:prices"), b("🏆 Reyting", "v:top")],
            [b("🎮 O'yinlar", "v:games"), b("🎁 Kunlik bonus", "v:bonus")],
            [b("👥 Do'st taklif qilish (+$%g)" % cfgf("ref_bonus"), "v:ref")],
            [b("⭐ Hisobni to'ldirish", "v:pay"), b("🛍 Do'kon", "v:shop")],
            [b("👤 Profil", "v:me")])

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
        return text, kb(*rows, [b("🔄", "v:market"), *MENU_BTN])

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
        return text, kb(*chunks, [b("📜 Tarix", "v:hist"), b("🔄", "v:port")], [b("📊 Bozor", "v:market"), *MENU_BTN])

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
        rows = leaderboard()
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (pr, r) in enumerate(rows[:10]):
            lines.append(f"{medals[i] if i < 3 else f'<b>{i + 1}.</b>'} {tag(r)}{esc(r['name'])} — <b>{sg(pr)}</b>")
        me = next((i for i, (_, r) in enumerate(rows) if r["id"] == uid), None)
        mine = f"\n\n📍 Sizning o'rningiz: <b>#{me + 1}</b> · {sg(rows[me][0])}" if me is not None else ""
        text = f"🏆 <b>Top treyderlar</b>\n<i>Eng ko'p daromad topganlar</i>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali hech kim yo'q") + mine
        return text, kb([b("⭐ Donat / To'ldirish", "v:pay")], [b("🔄", "v:top"), *MENU_BTN])

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
        text = (f"👥 <b>Do'stlarni taklif qiling</b>\n━━━━━━━━━━━━━━\n"
                f"Do'stingiz sizning havolangiz orqali ro'yxatdan o'tsa, <b>ikkalangizga ham {m(bonus)}</b> beriladi!\n\n"
                f"🔗 Havolangiz:\n<code>{link}</code>\n\n"
                f"👤 Taklif qilinganlar: <b>{u['ref_count']}</b>\n💵 Daromad: <b>{m(u['ref_earned'])}</b>")
        share = f"https://t.me/share/url?url={quote(link)}&text={quote('💎 Virtual Bozor — coinlar bilan savdo o`yini. Kir va bonus ol!')}"
        return text, kb([ub("📤 Do'stga yuborish", share)], MENU_BTN)

    if name == "pay":
        pk = q("SELECT * FROM packages ORDER BY stars")
        text = (f"⭐ <b>Hisobni to'ldirish / Donat</b>\n━━━━━━━━━━━━━━\n"
                f"Telegram Stars orqali o'yin balansini to'ldiring va loyihani qo'llab-quvvatlang. "
                f"Donat qilganlar reytingda <b>💎</b> belgisi oladi.\n\n"
                f"<i>Balans faqat o'yin ichida ishlatiladi, haqiqiy pulga almashtirilmaydi.</i>\n\n"
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
                f"🔁 Savdolar: <b>{u['trades']}</b>\n👥 Takliflar: <b>{u['ref_count']}</b>\n"
                f"🔔 Narx xabarnomasi: <b>{'yoqilgan' if u['notif'] else 'o`chirilgan'}</b>{foot}")
        return text, kb([b("🔕 Xabarnomani o'chirish" if u["notif"] else "🔔 Xabarnomani yoqish", "tgl")],
                        support_btn(), [b("🚪 Chiqish", "logout")], MENU_BTN)

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


# ───────────────────────── HOLATLAR / ROUTER ─────────────────────────
class Reg(StatesGroup):
    name = State()
    pin = State()
    pin2 = State()
    login = State()


class Adm(StatesGroup):
    wait = State()


r = Router()
LAST = {}


class Gate(BaseMiddleware):
    """Ro'yxatdan o'tmagan / kirmagan / bloklangan foydalanuvchida hech qaysi tugma ishlamaydi."""
    async def __call__(self, handler, event, data):
        uid, d = event.from_user.id, event.data or ""
        if d.startswith(("reg:", "login:")):
            return await handler(event, data)
        if d.startswith("adm:"):
            if uid in ADMINS:
                return await handler(event, data)
            return await event.answer("⛔ Ruxsat yo'q", show_alert=True)
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
    u = get_user(uid)
    if u and u["banned"]:
        return await msg.answer("🚫 Hisobingiz bloklangan.", reply_markup=kb(support_btn()))
    if not u:
        arg = command.args or ""
        ref = int(arg[3:]) if arg.startswith("ref") and arg[3:].isdigit() else None
        await state.update_data(ref=ref)
        return await msg.answer(
            f"💎 <b>Virtual Bozor</b>\n━━━━━━━━━━━━━━\n"
            f"Coinlar bilan savdo qiling, narxlarni kuzating va reytingda birinchi bo'ling!\n\n"
            f"🎁 Ro'yxatdan o'tsangiz <b>{m(cfgf('start_balance'))}</b> start balans beriladi.\n"
            f"👥 Do'stingiz taklif qilgan bo'lsa — qo'shimcha bonus.\n\n"
            f"<i>Bu virtual savdo o'yini: balans va daromad faqat o'yin ichida hisoblanadi.</i>",
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
            return await msg.answer("🔒 5 marta xato. 5 daqiqaga bloklandi.", reply_markup=kb(support_btn()))
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
    for a in ADMINS:
        try:
            await bot.send_message(a, f"⭐ <b>Yangi to'lov</b>: {sp.total_amount} Stars\n👤 {esc(u['name'])} (<code>{uid}</code>)\n💰 {m(amount)}")
        except Exception:
            pass


# ───────────────────────── ADMIN PANEL (alohida, faqat adminga) ─────────────────────────
PROMPTS = {
    "price": "💲 Yangi narxni yozing (masalan <code>85.5</code>):",
    "vol": "📈 Tebranish koeffitsienti (0.1–5, standart 1):",
    "addcoin": "➕ Format: <code>Nom | BELGI | emoji | narx</code>\nMasalan: <code>SunCoin | SUN | 🟡 | 60</code>",
    "finduser": "👤 Foydalanuvchi ID yoki ismini yozing:",
    "bal+": "➕ Qo'shiladigan summa:", "bal-": "➖ Ayiriladigan summa:",
    "bcast": "📣 Barcha foydalanuvchilarga yuboriladigan matnni yozing:",
    "addpk": "➕ Format: <code>stars | dollar</code>\nMasalan: <code>25 | 9000</code>",
    "set": "✏️ Yangi qiymatni yozing:", "pin": "🔑 Yangi 4 xonali PIN:",
}
SET_NAMES = {"start_balance": "Start balans", "ref_bonus": "Referal bonus", "daily_bonus": "Kunlik bonus",
             "liquidity": "Bozor chuqurligi", "vol": "Tebranish (global)", "support": "Support (@username)"}


def adm_user_card(uid):
    u = get_user(uid)
    if not u:
        return "Topilmadi", kb([b("⬅ Admin", "adm:menu")])
    hold = ", ".join(f"{COINS[h['cid']]['symbol']}×{h['qty']}" for h in holdings_of(uid) if h["cid"] in COINS) or "—"
    text = (f"👤 <b>{esc(u['name'])}</b> {'🚫' if u['banned'] else ''}\n🆔 <code>{uid}</code> · @{u['tg_username'] or '—'}\n"
            f"💵 Hamyon: {m(u['cash'])}\n💰 Jami: {m(net_worth(uid))}\n📊 Daromad: {sg(net_worth(uid) - u['base'])}\n"
            f"📦 {hold}\n⭐ Donat: {u['donated']} · 👥 Takliflar: {u['ref_count']}")
    return text, kb([b("➕ Balans", f"adm:input:bal+:{uid}"), b("➖ Balans", f"adm:input:bal-:{uid}")],
                    [b("✅ Blokdan chiqarish" if u["banned"] else "🚫 Bloklash", f"adm:ban:{uid}"), b("🔑 PIN", f"adm:input:pin:{uid}")],
                    [b("⬅ Admin", "adm:menu")])


def adm_view(name, arg=""):
    back = [b("⬅ Admin", "adm:menu")]
    if name == "stats":
        day = time.time() - 86400
        st = q1("SELECT COUNT(*) n, SUM(banned) bn, SUM(cash) cs FROM users")
        new = q1("SELECT COUNT(*) n FROM users WHERE created>?", day)["n"]
        tr = q1("SELECT COUNT(*) n, SUM(CASE WHEN ts>? THEN 1 ELSE 0 END) d FROM trades", day)
        pay = q1("SELECT COUNT(*) n, SUM(stars) s FROM payments")
        text = (f"📊 <b>Statistika</b>\n━━━━━━━━━━━━━━\n👥 Foydalanuvchilar: <b>{st['n']}</b> (🚫 {st['bn'] or 0})\n"
                f"🆕 24 soatda: <b>{new}</b>\n💵 Aylanmadagi pul: {m(st['cs'] or 0)}\n"
                f"🔁 Savdolar: <b>{tr['n']}</b> (24s: {tr['d'] or 0})\n⭐ To'lovlar: <b>{pay['n']}</b> · {pay['s'] or 0} Stars\n"
                f"🟢 Jonli ekranlar: {len(LIVE)}")
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
        return text, kb([b("💲 Narx", f"adm:input:price:{c['id']}"), b("📈 Tebranish", f"adm:input:vol:{c['id']}")],
                        [b("⛔ O'chirish" if c["active"] else "✅ Yoqish", f"adm:tog:{c['id']}")], [b("⬅ Coinlar", "adm:coins")])
    if name == "u":
        return adm_user_card(int(arg))
    if name == "pay":
        ps = q("SELECT p.*, u.name FROM payments p LEFT JOIN users u ON u.id=p.uid ORDER BY p.id DESC LIMIT 10")
        pk = q("SELECT * FROM packages ORDER BY stars")
        lines = [f"⭐ {p['stars']} · {esc(p['name'] or '?')} · {datetime.fromtimestamp(p['ts']).strftime('%d.%m %H:%M')}" for p in ps]
        text = ("⭐ <b>To'lovlar</b>\n━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "Hali to'lov yo'q") +
                "\n\n📦 <b>Paketlar</b>\n" + "\n".join(f"{p['stars']} ⭐ → {m(p['amount'])}" for p in pk) +
                "\n\n<i>Stars bot egasi hisobiga tushadi (Telegram → bot balansi).</i>")
        rows = [[b(f"🗑 {p['stars']}⭐ → {m(p['amount'])}", f"adm:pkdel:{p['id']}")] for p in pk]
        return text, kb(*rows, [b("➕ Paket", "adm:input:addpk")], back)
    if name == "set":
        lines = [f"• {n}: <code>{esc(cfg(k)) or '—'}</code>" for k, n in SET_NAMES.items()]
        lines.append(f"• Soatlik xabar: <b>{'yoqilgan' if cfg('bcast_on') == '1' else 'o`chirilgan'}</b>")
        rows = [[b(f"✏️ {n}", f"adm:input:set:{k}")] for k, n in SET_NAMES.items()]
        return "⚙️ <b>Sozlamalar</b>\n━━━━━━━━━━━━━━\n" + "\n".join(lines), kb(*rows, [b("🔔 Soatlik xabarni yoqish/o'chirish", "adm:bc")], back)
    n = q1("SELECT COUNT(*) n FROM users")["n"]
    return (f"🛠 <b>Admin panel</b>\n━━━━━━━━━━━━━━\n👥 {n} foydalanuvchi · 🪙 {len(COINS)} coin",
            kb([b("📊 Statistika", "adm:stats"), b("🪙 Coinlar", "adm:coins")],
               [b("👤 Foydalanuvchi", "adm:input:finduser"), b("📣 Xabar", "adm:input:bcast")],
               [b("⭐ To'lovlar", "adm:pay"), b("⚙️ Sozlamalar", "adm:set")],
               [b("✖ Yopish", "adm:close")]))


@r.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    await state.clear()
    text, markup = adm_view("menu")
    await msg.answer(text, reply_markup=markup)


@r.callback_query(F.data.startswith("adm:"))
async def adm_cb(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":", 2)
    name, arg = parts[1], (parts[2] if len(parts) > 2 else "")
    await state.clear()
    try:
        if name == "close":
            await cb.message.delete()
            return await cb.answer()
        if name == "input":
            act, _, a = arg.partition(":")
            await state.set_state(Adm.wait)
            await state.update_data(act=act, a=a)
            await cb.message.edit_text(PROMPTS[act], reply_markup=kb([b("✖ Bekor qilish", "adm:menu")]))
            return await cb.answer()
        if name == "tog":
            c = COINS[int(arg)]
            c["active"] = 0 if c["active"] else 1
            save_coin(c)
            name = "c"
        elif name == "ban":
            ex("UPDATE users SET banned=1-banned, logged_in=CASE WHEN banned=0 THEN 0 ELSE logged_in END WHERE id=?", int(arg))
            name = "u"
        elif name == "pkdel":
            ex("DELETE FROM packages WHERE id=?", int(arg))
            name = "pay"
        elif name == "bc":
            set_cfg("bcast_on", "0" if cfg("bcast_on") == "1" else "1")
            name = "set"
        text, markup = adm_view(name, arg)
        await show(cb, text, markup)
    except (KeyError, ValueError):
        await cb.answer("⚠️ Xatolik", show_alert=True)
        return
    await cb.answer()


@r.message(Adm.wait, F.text)
async def adm_input(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return await state.clear()
    d = await state.get_data()
    act, a, t = d.get("act"), d.get("a", ""), msg.text.strip()
    await state.clear()
    back = kb([b("⬅ Admin", "adm:menu")])
    try:
        if act == "price":
            v = float(t.replace(",", "."))
            assert v > 0
            c = COINS[int(a)]
            c["price"] = c["base"] = round(v, 2)
            H1[c["id"]].append((time.time(), c["price"]))
            save_coin(c)
            return await msg.answer(f"✅ {esc(c['name'])} narxi: ${c['price']:,.2f}", reply_markup=kb([b("⬅ Coin", f"adm:c:{c['id']}")]))
        if act == "vol":
            v = float(t.replace(",", "."))
            assert 0.1 <= v <= 5
            c = COINS[int(a)]
            c["vol"] = v
            save_coin(c)
            return await msg.answer(f"✅ Tebranish: ×{v}", reply_markup=kb([b("⬅ Coin", f"adm:c:{c['id']}")]))
        if act == "addcoin":
            nm, sym, emo, pr = [x.strip() for x in t.split("|")]
            pr = float(pr.replace(",", "."))
            assert pr > 0 and nm and sym
            cur = ex("INSERT INTO coins(symbol,name,emoji,price,base) VALUES(?,?,?,?,?)", sym.upper(), nm, emo, pr, pr)
            c = dict(q1("SELECT * FROM coins WHERE id=?", cur.lastrowid))
            COINS[c["id"]], H1[c["id"]], MOM[c["id"]] = c, deque([(time.time(), pr)], maxlen=720), 0.0
            return await msg.answer(f"✅ Coin qo'shildi: {emo} {esc(nm)} ${pr:,.2f}", reply_markup=kb([b("🪙 Coinlar", "adm:coins")]))
        if act == "finduser":
            u = get_user(int(t)) if t.isdigit() else (q1("SELECT * FROM users WHERE name_lc=?", t.lower()) or q1("SELECT * FROM users WHERE name_lc LIKE ?", f"%{t.lower()}%"))
            if not u:
                return await msg.answer("❌ Topilmadi", reply_markup=back)
            text, markup = adm_user_card(u["id"])
            return await msg.answer(text, reply_markup=markup)
        if act in ("bal+", "bal-"):
            v = float(t.replace(",", "."))
            assert v > 0
            uid = int(a)
            if act == "bal-":
                v = -min(v, get_user(uid)["cash"])
            ex("UPDATE users SET cash=round(cash+?,2), base=base+? WHERE id=?", v, v, uid)
            text, markup = adm_user_card(uid)
            return await msg.answer("✅ Bajarildi\n\n" + text, reply_markup=markup)
        if act == "pin":
            assert t.isdigit() and len(t) == 4
            salt = secrets.token_hex(8)
            ex("UPDATE users SET salt=?, pin=?, fails=0, lock_until=0 WHERE id=?", salt, hash_pin(salt, t), int(a))
            return await msg.answer("✅ PIN yangilandi", reply_markup=back)
        if act == "bcast":
            asyncio.create_task(broadcast_text(t, msg.from_user.id))
            return await msg.answer("📣 Yuborish boshlandi. Tugagach xabar beraman.", reply_markup=back)
        if act == "addpk":
            s, am = [float(x.replace(",", ".")) for x in t.split("|")]
            assert s >= 1 and am > 0
            ex("INSERT INTO packages(stars,amount) VALUES(?,?)", int(s), am)
            return await msg.answer("✅ Paket qo'shildi", reply_markup=kb([b("⭐ To'lovlar", "adm:pay")]))
        if act == "set":
            if a != "support":
                assert float(t.replace(",", ".")) >= 0
            set_cfg(a, t.replace(",", ".") if a != "support" else t)
            return await msg.answer("✅ Saqlandi", reply_markup=kb([b("⚙️ Sozlamalar", "adm:set")]))
    except (ValueError, AssertionError, KeyError, IndexError, TypeError, sqlite3.IntegrityError):
        pass
    await msg.answer("⚠️ Format noto'g'ri yoki qiymat mos emas. Qaytadan urinib ko'ring.", reply_markup=back)


# ───────────────────────── XABAR YUBORISH ─────────────────────────
async def safe_send(uid, text, markup=None):
    """True — yetkazildi. Bot bloklangan bo'lsa xabarnoma o'chiriladi."""
    try:
        await bot.send_message(uid, text, reply_markup=markup)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        return await safe_send(uid, text, markup)
    except TelegramForbidden:
        ex("UPDATE users SET notif=0 WHERE id=?", uid)
    except Exception:
        pass
    return False


async def broadcast_text(text, admin_id):
    ok = 0
    for u in q("SELECT id FROM users WHERE banned=0"):
        ok += await safe_send(u["id"], f"📣 {text}")
        await asyncio.sleep(0.05)
    await safe_send(admin_id, f"✅ Xabar {ok} kishiga yetkazildi.")


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
        with tx():
            ex("DELETE FROM preds WHERE id=?", p["id"])
            if not c:
                pay, res = p["bet"], "⚠️ Coin topilmadi — tikish qaytarildi"
            elif c["price"] == p["p0"]:
                pay, res = p["bet"], "🤝 Narx o'zgarmadi — tikish qaytarildi"
            elif (c["price"] > p["p0"]) == (p["dir"] == "u"):
                pay, res = round(p["bet"] * 1.9, 2), f"🎉 <b>To'g'ri topdingiz! +{m(p['bet'] * 0.9)}</b>"
            else:
                pay, res = 0, f"😕 <b>Topolmadingiz −{m(p['bet'])}</b>"
            credit(p["uid"], pay)
        now_p = f"{c['emoji']} {esc(c['name'])}: ${p['p0']:,.2f} → <b>${c['price']:,.2f}</b>\n" if c else ""
        await safe_send(p["uid"], f"🔮 <b>Bashorat natijasi</b>\n{now_p}{res}",
                        kb([b("🔁 Yana", "v:g:pred"), b("⬅ Menyu", "v:menu")]))


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
    last_min = 0.0
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
            await resolve_preds()
            await push_live()
        except Exception:
            log.exception("engine")


# ───────────────────────── BOSHQA XABARLAR ─────────────────────────
@r.message(StateFilter(None))
async def fallback(msg: Message):
    u = get_user(msg.from_user.id)
    if u and u["logged_in"] and not u["banned"]:
        await send_menu(msg.chat.id, u["id"])
    else:
        await msg.answer("👋 Boshlash uchun /start ni bosing.")


async def main():
    global bot, BOT_USERNAME
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not TOKEN:
        raise SystemExit("BOT_TOKEN o'rnatilmagan: export BOT_TOKEN='...'")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_USERNAME = (await bot.get_me()).username
    load_coins()
    dp = Dispatcher()
    r.callback_query.outer_middleware(Gate())
    dp.include_router(r)
    tasks = [asyncio.create_task(engine()), asyncio.create_task(hourly())]
    log.info("Bot ishga tushdi: @%s | adminlar: %s", BOT_USERNAME, sorted(ADMINS) or "YO'Q (ADMIN_IDS ni o'rnating)")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "pre_checkout_query"])
    finally:
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    asyncio.run(main())

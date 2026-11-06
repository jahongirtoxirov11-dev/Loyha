import asyncio
import random
import string
import os
import time
import sqlite3
from aiohttp import web  # Render Web Service "Live" bo'lishi uchun kerak
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors

# ==================== MAXFIY MA'LUMOTLAR (ENVIRONMENT VARIABLES) ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "8371392099"))

if not BOT_TOKEN:
    raise ValueError("XATOLIK: BOT_TOKEN topilmadi! Render Environment Variables bo'limiga BOT_TOKEN ni kiriting.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_NAME = "smart_school_v2.db"

# ==================== DATABASE (MA'LUMOTLAR BAZASI) ====================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                full_name TEXT,
                school_num INTEGER,
                grade INTEGER,
                rating INTEGER DEFAULT 1000,
                last_bonus INTEGER DEFAULT 0,
                referred_by INTEGER DEFAULT NULL
            )
        """)
        try:
            cur.execute("ALTER TABLE users ADD COLUMN last_bonus INTEGER DEFAULT 0")
        except:
            pass
        try:
            cur.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL")
        except:
            pass

        cur.execute("CREATE TABLE IF NOT EXISTS admins (telegram_id INTEGER PRIMARY KEY)")
        cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER,
                grade INTEGER,
                question_text TEXT,
                photo_id TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                creator_id INTEGER,
                subject_id INTEGER,
                status TEXT DEFAULT 'active'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE,
                title TEXT,
                invite_link TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_mistakes (
                user_id INTEGER,
                question_id INTEGER,
                UNIQUE(user_id, question_id)
            )
        """)
        conn.commit()

def register_user(telegram_id, full_name, school_num, grade, referred_by=None):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO users (telegram_id, full_name, school_num, grade, rating, last_bonus, referred_by)
            VALUES (
                ?, ?, ?, ?, 
                COALESCE((SELECT rating FROM users WHERE telegram_id = ?), 1000),
                COALESCE((SELECT last_bonus FROM users WHERE telegram_id = ?), 0),
                COALESCE((SELECT referred_by FROM users WHERE telegram_id = ?), ?)
            )
        """, (telegram_id, full_name, school_num, grade, telegram_id, telegram_id, telegram_id, referred_by))
        conn.commit()

def get_user(telegram_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT full_name, school_num, grade, rating, last_bonus, referred_by FROM users WHERE telegram_id = ?", (telegram_id,))
        return cur.fetchone()

def get_user_league(rating):
    if rating < 3000:
        return "🥉 Bronza"
    elif rating < 4000:
        return "🥈 Kumush"
    elif rating < 5000:
        return "🥇 Oltin"
    elif rating < 7000:
        return "💎 Olmos"
    else:
        return "👑 Grossmeyster"

def get_referrals_count(telegram_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (telegram_id,))
        return cur.fetchone()[0]

def claim_daily_bonus(telegram_id, bonus_amount=100):
    now = int(time.time())
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT last_bonus FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cur.fetchone()
        if not row:
            return False, 0
        last_bonus = row[0] or 0
        if now - last_bonus >= 86400:
            cur.execute("UPDATE users SET rating = rating + ?, last_bonus = ? WHERE telegram_id = ?", (bonus_amount, now, telegram_id))
            conn.commit()
            return True, 0
        else:
            return False, 86400 - (now - last_bonus)

def is_admin(telegram_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins WHERE telegram_id = ?", (telegram_id,))
        return cur.fetchone() is not None

def add_admin(telegram_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (telegram_id,))
        conn.commit()

def add_subject(name):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO subjects (name) VALUES (?)", (name,))
        conn.commit()

def get_subjects():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM subjects")
        return cur.fetchall()

def add_question(subject_id, grade, q_text, photo_id, opt_a, opt_b, opt_c, opt_d, correct):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO questions (subject_id, grade, question_text, photo_id, option_a, option_b, option_c, option_d, correct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (subject_id, grade, q_text, photo_id, opt_a, opt_b, opt_c, opt_d, correct))
        conn.commit()

def get_random_questions(subject_id, grade, limit=10):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, question_text, photo_id, option_a, option_b, option_c, option_d, correct 
            FROM questions WHERE subject_id = ? AND grade = ?
        """, (subject_id, grade))
        rows = cur.fetchall()
        random.shuffle(rows)
        return rows[:limit]

def get_question_by_id(q_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, question_text, photo_id, option_a, option_b, option_c, option_d, correct FROM questions WHERE id = ?", (q_id,))
        return cur.fetchone()

# --- XATOLAR USTIDA ISHLASH BAZA FUNKSIYALARI ---
def add_mistake(user_id, question_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO user_mistakes (user_id, question_id) VALUES (?, ?)", (user_id, question_id))
        conn.commit()

def remove_mistake(user_id, question_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_mistakes WHERE user_id = ? AND question_id = ?", (user_id, question_id))
        conn.commit()

def get_user_mistakes(user_id, limit=10):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT q.id, q.question_text, q.photo_id, q.option_a, q.option_b, q.option_c, q.option_d, q.correct
            FROM questions q
            JOIN user_mistakes m ON q.id = m.question_id
            WHERE m.user_id = ?
            LIMIT ?
        """, (user_id, limit))
        return cur.fetchall()

def get_mistakes_count(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM user_mistakes WHERE user_id = ?", (user_id,))
        return cur.fetchone()[0]

# --- REYTING FUNKSIYALARI ---
def get_global_rating():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT full_name, school_num, grade, rating FROM users ORDER BY rating DESC LIMIT 10")
        return cur.fetchall()

def get_schools_rating():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT school_num, COUNT(telegram_id) as cnt, SUM(rating) as total_rating 
            FROM users GROUP BY school_num ORDER BY total_rating DESC LIMIT 10
        """)
        return cur.fetchall()

def get_grade_rating(grade):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT full_name, school_num, rating FROM users WHERE grade = ? ORDER BY rating DESC LIMIT 10", (grade,))
        return cur.fetchall()

def add_user_points(telegram_id, points):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET rating = MAX(0, rating + ?) WHERE telegram_id = ?", (points, telegram_id))
        conn.commit()

def create_promo(creator_id, subject_id):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO promo_codes (code, creator_id, subject_id, status) VALUES (?, ?, ?, 'active')", (code, creator_id, subject_id))
        conn.commit()
    return code

def get_promo(code):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT creator_id, subject_id, status FROM promo_codes WHERE code = ?", (code,))
        return cur.fetchone()

def use_promo(code):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE promo_codes SET status = 'used' WHERE code = ?", (code,))
        conn.commit()

def add_channel_db(chat_id, title, invite_link):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO channels (chat_id, title, invite_link) VALUES (?, ?, ?)", (str(chat_id), title, invite_link))
        conn.commit()

def get_channels_db():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, chat_id, title, invite_link FROM channels")
        return cur.fetchall()

def delete_channel_db(channel_db_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM channels WHERE id = ?", (channel_db_id,))
        conn.commit()


# ==================== MAJBURIY OBUNA TEKSHIRUVI ====================
async def get_unsubscribed_channels(user_id):
    if is_admin(user_id):
        return []
    channels = get_channels_db()
    unsubscribed = []
    for ch_id, chat_id, title, link in channels:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                unsubscribed.append((title, link))
        except Exception:
            pass
    return unsubscribed

def sub_check_kb(unsubscribed):
    rows = [[InlineKeyboardButton(text=f"➕ {title}", url=link)] for title, link in unsubscribed]
    rows.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

class ForceSubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        if isinstance(event, types.CallbackQuery) and event.data == "check_subscription":
            return await handler(event, data)
        if isinstance(event, types.Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        unsubscribed = await get_unsubscribed_channels(user.id)
        if unsubscribed:
            text = "⚠️ <b>Botdan to'liq foydalanish uchun quyidagi kanallarga obuna bo'ling!</b>\n\nObuna bo'lgach, <b>«✅ Obuna bo'ldim»</b> tugmasini bosing:"
            kb = sub_check_kb(unsubscribed)
            if isinstance(event, types.Message):
                await event.answer(text, reply_markup=kb, parse_mode="HTML")
            elif isinstance(event, types.CallbackQuery):
                await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
                await event.answer()
            return
        return await handler(event, data)

dp.message.middleware(ForceSubMiddleware())
dp.callback_query.middleware(ForceSubMiddleware())


# ==================== PDF SERTIFIKAT GENERATSIYASI ====================
def generate_certificate(full_name, school_num, grade, league_name, points, filename="certificate.pdf"):
    c = canvas.Canvas(filename, pagesize=landscape(letter))
    width, height = landscape(letter)

    c.setStrokeColor(colors.HexColor("#1A365D"))
    c.setLineWidth(5)
    c.rect(30, 30, width - 60, height - 60)

    c.setStrokeColor(colors.HexColor("#D69E2E"))
    c.setLineWidth(2)
    c.rect(40, 40, width - 80, height - 80)

    c.setFillColor(colors.HexColor("#1A365D"))
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 100, "FAXRIY SERTIFIKAT")

    c.setFont("Helvetica", 14)
    c.setFillColor(colors.HexColor("#4A5568"))
    c.drawCentredString(width / 2, height - 130, "Ushbu sertifikat quyidagi faol o'quvchiga beriladi:")

    c.setFont("Helvetica-Bold", 32)
    c.setFillColor(colors.HexColor("#2B6CB0"))
    c.drawCentredString(width / 2, height - 190, full_name)

    c.setFont("Helvetica", 14)
    c.setFillColor(colors.HexColor("#2D3748"))
    c.drawCentredString(width / 2, height - 240, f"Smart School intellektual turnirida {grade}-sinflar o'rtasida")
    c.drawCentredString(width / 2, height - 265, f"{school_num}-maktab sharafini munosib himoya qilib, {points} reyting ball to'plagani")
    c.drawCentredString(width / 2, height - 290, f"hamda faxrli «{league_name}» darajasiga erishgani uchun taqdirlanadi!")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(100, 90, "Tashkilotchi: Smart School Platformasi")
    c.drawRightString(width - 100, 90, f"Reyting: {points} ball")

    c.save()
    return filename


# ==================== TUGMALAR VA HOLATLAR ====================
waiting_match_queue = {}
live_duel_sessions = {}
duel_detailed_stats = {}
duel_finished_scores = {}
answered_events = {}

class RegState(StatesGroup):
    full_name = State()
    school_num = State()
    grade = State()

class AdminState(StatesGroup):
    add_subject = State()
    q_subject = State()
    q_grade = State()
    q_content = State()
    q_options = State()
    q_correct = State()
    broadcast = State()
    restore_db = State()
    add_channel = State()
    bulk_sub = State()
    bulk_grade = State()
    bulk_file = State()

class PromoState(StatesGroup):
    enter_code = State()

def main_menu_kb(is_adm=False):
    kb = [
        [KeyboardButton(text="⚔️ Turnirda ishtirok etish"), KeyboardButton(text="🏋️ Mashg'ulot (Yolg'iz)")],
        [KeyboardButton(text="❌ Xatolar ustida ishlash"), KeyboardButton(text="🤝 Promokod orqali ulanish")],
        [KeyboardButton(text="🎁 Kunlik bonus"), KeyboardButton(text="👥 Do'stni taklif qilish")],
        [KeyboardButton(text="🏆 Reyting"), KeyboardButton(text="👤 Mening profilim")]
    ]
    if is_adm:
        kb.append([KeyboardButton(text="👑 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

admin_menu_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Fan qo'shish"), KeyboardButton(text="📝 Savol qo'shish")],
    [KeyboardButton(text="📂 Fayldan savol yuklash (.txt)"), KeyboardButton(text="📢 Majburiy obuna")],
    [KeyboardButton(text="💾 Bazani olish (Backup)"), KeyboardButton(text="📥 Bazani tiklash")],
    [KeyboardButton(text="📢 E'lon yuborish"), KeyboardButton(text="🔙 Asosiy menyu")]
], resize_keyboard=True)

cancel_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="❌ Bekor qilish")]
], resize_keyboard=True)


# ==================== BEKOR QILISH HANDLERLARI ====================
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_action_msg(message: types.Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("🚫 Jarayon bekor qilindi. Admin panel:", reply_markup=admin_menu_kb)
    else:
        await message.answer("🚫 Jarayon bekor qilindi.", reply_markup=main_menu_kb(False))

@dp.callback_query(F.data == "cancel_action")
async def cancel_action_call(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    if is_admin(callback.from_user.id):
        await callback.message.answer("🚫 Jarayon bekor qilindi. Admin panel:", reply_markup=admin_menu_kb)
    await callback.answer()

@dp.callback_query(F.data == "check_subscription")
async def check_sub_callback(callback: types.CallbackQuery, state: FSMContext):
    unsubscribed = await get_unsubscribed_channels(callback.from_user.id)
    if unsubscribed:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)
    else:
        await callback.message.delete()
        user = get_user(callback.from_user.id)
        if not user:
            await callback.message.answer("✅ Obuna tasdiqlandi!\n\n👋 Ism va familiyangizni kiriting:")
            await state.set_state(RegState.full_name)
        else:
            is_adm = is_admin(callback.from_user.id)
            await callback.message.answer("✅ Obuna tasdiqlandi! Asosiy menyudasiz:", reply_markup=main_menu_kb(is_adm))
        await callback.answer()


# ==================== ASOSIY HANDLERLAR, PROFIL VA SERTIFIKAT ====================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    add_admin(ADMIN_TELEGRAM_ID)
    user = get_user(message.from_user.id)
    
    if not user and command.args and command.args.startswith("ref_"):
        try:
            possible_ref = int(command.args.split("_")[1])
            if possible_ref != message.from_user.id and get_user(possible_ref):
                await state.update_data(referred_by=possible_ref)
        except:
            pass

    unsubscribed = await get_unsubscribed_channels(message.from_user.id)
    if unsubscribed:
        return await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling!</b>",
            reply_markup=sub_check_kb(unsubscribed),
            parse_mode="HTML"
        )

    if not user:
        await message.answer("👋 Assalomu alaykum! Smart School turnir botiga xush kelibsiz.\n\nIsm va familiyangizni kiriting:")
        await state.set_state(RegState.full_name)
    else:
        is_adm = is_admin(message.from_user.id)
        await message.answer(f"Salom, <b>{user[0]}</b>! Asosiy menyudasiz:", reply_markup=main_menu_kb(is_adm), parse_mode="HTML")

@dp.message(RegState.full_name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("Maktabingiz raqamini faqat sonda kiriting (masalan: 15):")
    await state.set_state(RegState.school_num)

@dp.message(RegState.school_num)
async def reg_school(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Faqat raqam kiriting!")
    await state.update_data(school_num=int(message.text))
    await message.answer("Nechanchi sinfda o'qiysiz? (1 dan 11 gacha):")
    await state.set_state(RegState.grade)

@dp.message(RegState.grade)
async def reg_grade(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 11):
        return await message.answer("Iltimos, 1 dan 11 gacha bo'lgan sinf raqamini kiriting!")
    
    data = await state.get_data()
    ref_id = data.get('referred_by')
    register_user(message.from_user.id, data['full_name'], data['school_num'], int(message.text), ref_id)
    
    if ref_id:
        add_user_points(ref_id, 200)
        try:
            await bot.send_message(ref_id, f"🎉 Do'stingiz <b>{data['full_name']}</b> taklifingiz orqali qo'shildi! Sizga <b>+200 ball</b> berildi!", parse_mode="HTML")
        except:
            pass

    await state.clear()
    is_adm = is_admin(message.from_user.id)
    await message.answer("✅ Muvaffaqiyatli ro'yxatdan o'tdingiz! Boshlang'ich 1000 ball berildi.", reply_markup=main_menu_kb(is_adm))

@dp.message(F.text == "👤 Mening profilim")
async def profile_handler(message: types.Message):
    u = get_user(message.from_user.id)
    if u:
        refs = get_referrals_count(message.from_user.id)
        mistakes_cnt = get_mistakes_count(message.from_user.id)
        league = get_user_league(u[3])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📜 Sertifikatni yuklab olish (6000+ ball)", callback_data="download_my_cert")]
        ])
        await message.answer(
            f"👤 <b>Ism:</b> {u[0]}\n"
            f"🏫 <b>Maktab:</b> {u[1]}-maktab ({u[2]}-sinf)\n"
            f"🎖 <b>Daraja (Liga):</b> {league}\n"
            f"⭐ <b>Reyting Ball:</b> {u[3]}\n"
            f"❌ <b>Xato savollar soni:</b> {mistakes_cnt} ta\n"
            f"👥 <b>Taklif qilgan do'stlar:</b> {refs} ta", 
            reply_markup=kb,
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "download_my_cert")
async def download_cert_handler(callback: types.CallbackQuery):
    u = get_user(callback.from_user.id)
    if not u:
        return
    if u[3] < 6000:
        return await callback.answer(f"❌ Sertifikat olish uchun kamida 6000 ball (Oltin liga) kerak! Sizda hozir {u[3]} ball bor.", show_alert=True)
    
    await callback.answer("⏳ Sertifikat tayyorlanmoqda...")
    league_clean = get_user_league(u[3]).split(" ")[1]
    pdf_path = f"cert_{callback.from_user.id}.pdf"
    generate_certificate(u[0], u[1], u[2], league_clean, u[3], filename=pdf_path)
    
    doc = FSInputFile(pdf_path)
    await callback.message.answer_document(doc, caption=f"🏆 <b>Tabriklaymiz, {u[0]}!</b>\nSizning rasmiy Faxriy Sertifikatingiz tayyor!", parse_mode="HTML")
    if os.path.exists(pdf_path):
        os.remove(pdf_path)


# ==================== 3 XIL REYTING TIZIMI ====================
def rating_tabs_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Umumiy Top-10", callback_data="rate_global"),
         InlineKeyboardButton(text="🏫 Top Maktablar", callback_data="rate_schools")],
        [InlineKeyboardButton(text="🎓 Mening sinfim reytingi", callback_data="rate_my_grade")]
    ])

@dp.message(F.text == "🏆 Reyting")
async def rating_handler(message: types.Message):
    top = get_global_rating()
    text = "🌍 <b>Respublika bo'yicha Top-10 o'quvchi:</b>\n\n"
    for i, row in enumerate(top, 1):
        league_icon = get_user_league(row[3]).split(" ")[0]
        text += f"{i}. {league_icon} {row[0]} ({row[1]}-maktab, {row[2]}-sinf) — <b>{row[3]} ball</b>\n"
    await message.answer(text, reply_markup=rating_tabs_kb(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("rate_"))
async def switch_rating_tabs(callback: types.CallbackQuery):
    mode = callback.data.split("_")[1]
    if mode == "global":
        top = get_global_rating()
        text = "🌍 <b>Respublika bo'yicha Top-10 o'quvchi:</b>\n\n"
        for i, row in enumerate(top, 1):
            league_icon = get_user_league(row[3]).split(" ")[0]
            text += f"{i}. {league_icon} {row[0]} ({row[1]}-maktab, {row[2]}-sinf) — <b>{row[3]} ball</b>\n"
    elif mode == "schools":
        schools = get_schools_rating()
        text = "🏫 <b>Eng kuchli Top-10 maktablar:</b>\n\n"
        for i, row in enumerate(schools, 1):
            text += f"{i}. 🏛 <b>{row[0]}-maktab</b> ({row[1]} o'quvchi) — Jami: <b>{row[2]} ball</b>\n"
    else:
        u = get_user(callback.from_user.id)
        grade = u[2] if u else 1
        top_grade = get_grade_rating(grade)
        text = f"🎓 <b>{grade}-sinflar o'rtasida Top-10 o'quvchi:</b>\n\n"
        for i, row in enumerate(top_grade, 1):
            league_icon = get_user_league(row[2]).split(" ")[0]
            text += f"{i}. {league_icon} {row[0]} ({row[1]}-maktab) — <b>{row[2]} ball</b>\n"

    try:
        await callback.message.edit_text(text, reply_markup=rating_tabs_kb(), parse_mode="HTML")
    except:
        pass
    await callback.answer()


# ==================== KUNLIK BONUS VA REFERRAL ====================
@dp.message(F.text == "🎁 Kunlik bonus")
async def daily_bonus_handler(message: types.Message):
    success, remaining = claim_daily_bonus(message.from_user.id, bonus_amount=100)
    if success:
        u = get_user(message.from_user.id)
        await message.answer(f"🎉 <b>Tabriklaymiz!</b> Sizga kunlik <b>+100 ball</b> berildi!\n⭐ Joriy reytingingiz: <b>{u[3]} ball</b>", parse_mode="HTML")
    else:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await message.answer(f"⏳ Keyingi bonusni <b>{hours} soat {minutes} daqiqadan</b> keyin olishingiz mumkin.", parse_mode="HTML")

@dp.message(F.text == "👥 Do'stni taklif qilish")
async def referral_handler(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
    refs = get_referrals_count(message.from_user.id)
    await message.answer(
        f"👥 <b>Do'stlaringizni taklif qiling va har bir do'st uchun +200 ball oling!</b>\n\n"
        f"🔗 <b>Sizning shaxsiy havolangiz:</b>\n{ref_link}\n\n"
        f"📊 Taklif qilgan do'stlaringiz: <b>{refs} ta</b>",
        parse_mode="HTML"
    )


# ==================== XATOLAR USTIDA ISHLASH VA MASHG'ULOT ====================
@dp.message(F.text == "❌ Xatolar ustida ishlash")
async def mistakes_menu(message: types.Message):
    cnt = get_mistakes_count(message.from_user.id)
    if cnt == 0:
        return await message.answer("🎉 <b>Ajoyib! Sizda hozircha xato qilingan savollar yo'q!</b>", parse_mode="HTML")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🚀 Xatolarni tuzatishni boshlash ({cnt} ta)", callback_data="start_mistakes_review")]
    ])
    await message.answer(
        f"📚 Sizda oldingi o'yinlarda xato qilingan <b>{cnt} ta savol</b> saqlanib turibdi.\n"
        f"Ularni to'g'ri yechsangiz, xatolar ro'yxatidan o'chadi va har biriga <b>+5 ball</b> olasiz!",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "start_mistakes_review")
async def run_mistakes_review(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    questions = get_user_mistakes(user_id, limit=10)
    if not questions:
        return await callback.answer("Xato savollar qolmadi!", show_alert=True)
    
    await callback.message.edit_text("🧠 <b>Xatolar ustida ishlash boshlandi!</b>", parse_mode="HTML")
    await callback.answer()
    u = get_user(user_id)
    asyncio.create_task(run_duel_session(user_id, 0, u[2], None, custom_questions=questions, is_mistake_mode=True))

@dp.message(F.text == "🏋️ Mashg'ulot (Yolg'iz)")
async def practice_subjects(message: types.Message):
    subjects = get_subjects()
    if not subjects:
        return await message.answer("Hozircha fanlar qo'shilmagan.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=sub[1], callback_data=f"practice_sub_{sub[0]}")] for sub in subjects
    ])
    await message.answer("🏋️ <b>Mashg'ulot rejimi:</b>\n📚 Fanni tanlang:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("practice_sub_"))
async def start_practice_mode(callback: types.CallbackQuery):
    subject_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    user = get_user(user_id)
    await callback.message.edit_text(f"🚀 <b>{user[2]}-sinf</b> bo'yicha mashg'ulot boshlanmoqda!", parse_mode="HTML")
    await callback.answer()
    asyncio.create_task(run_duel_session(user_id, subject_id, user[2], None))


# ==================== TURNIR & MATCHMAKING ====================
@dp.message(F.text == "⚔️ Turnirda ishtirok etish")
async def turnir_subjects(message: types.Message):
    user = get_user(message.from_user.id)
    if user[3] < 50:
        return await message.answer("⚠️ <b>Duelga kirish uchun kamida 50 ball kerak!</b>", parse_mode="HTML")

    subjects = get_subjects()
    if not subjects:
        return await message.answer("Hozircha fanlar qo'shilmagan.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=sub[1], callback_data=f"select_subject_{sub[0]}")] for sub in subjects
    ])
    await message.answer("📚 Duel uchun fanni tanlang:", reply_markup=kb)

@dp.callback_query(F.data.startswith("select_subject_"))
async def subject_selected(callback: types.CallbackQuery):
    subject_id = int(callback.data.split("_")[2])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Raqib topish", callback_data=f"find_rival_{subject_id}")]
    ])
    await callback.message.edit_text("Fan tanlandi. Raqib qidirishni bosing:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("find_rival_"))
async def find_rival(callback: types.CallbackQuery):
    subject_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    user = get_user(user_id)
    grade = user[2]

    if user[3] < 50:
        return await callback.answer("Duel uchun kamida 50 ball kerak!", show_alert=True)

    if subject_id not in waiting_match_queue:
        waiting_match_queue[subject_id] = {}
    if grade not in waiting_match_queue[subject_id]:
        waiting_match_queue[subject_id][grade] = []

    queue = waiting_match_queue[subject_id][grade]
    if user_id in queue:
        return await callback.answer("Siz allaqachon navbatdasiz...", show_alert=True)

    if queue:
        rival_id = queue.pop(0)
        await callback.message.edit_text(f"⚔️ Raqib topildi! ({grade}-sinf, Duel boshlanmoqda...)")
        await bot.send_message(rival_id, f"⚔️ Raqib topildi! ({grade}-sinf, Duel boshlanmoqda...)")
        asyncio.create_task(run_duel_session(user_id, subject_id, grade, rival_id))
        asyncio.create_task(run_duel_session(rival_id, subject_id, grade, user_id))
    else:
        queue.append(user_id)
        await callback.message.edit_text(f"⏳ {grade}-sinf uchun raqib qidirilmoqda...")
        await asyncio.sleep(6)
        if user_id in queue:
            queue.remove(user_id)
            await callback.message.edit_text("😔 Raqib topilmadi. Yolg'iz rejimda sinov boshlanadi!")
            asyncio.create_task(run_duel_session(user_id, subject_id, grade, None))


# ==================== DUEL, QUIZ VA "50/50" YORDAMCHISI ====================
def build_question_kb(q_id, opt_a, opt_b, opt_c, opt_d, correct, include_5050=True):
    rows = [
        [InlineKeyboardButton(text=f"A) {opt_a}", callback_data=f"liveans_{q_id}_A_{correct}")],
        [InlineKeyboardButton(text=f"B) {opt_b}", callback_data=f"liveans_{q_id}_B_{correct}")],
        [InlineKeyboardButton(text=f"C) {opt_c}", callback_data=f"liveans_{q_id}_C_{correct}")],
        [InlineKeyboardButton(text=f"D) {opt_d}", callback_data=f"liveans_{q_id}_D_{correct}")]
    ]
    if include_5050:
        rows.append([InlineKeyboardButton(text="💡 50/50 Yordam (-30 ball)", callback_data=f"lifeline50_{q_id}_{correct}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data.startswith("lifeline50_"))
async def use_5050_lifeline(callback: types.CallbackQuery):
    _, q_id_str, correct = callback.data.split("_")
    q_id = int(q_id_str)
    user_id = callback.from_user.id

    u = get_user(user_id)
    if u[3] < 30:
        return await callback.answer("❌ 50/50 yordamini olish uchun kamida 30 ball kerak!", show_alert=True)

    add_user_points(user_id, -30)
    q = get_question_by_id(q_id)
    if not q:
        return

    _, _, _, opt_a, opt_b, opt_c, opt_d, _ = q
    options_map = {"A": opt_a, "B": opt_b, "C": opt_c, "D": opt_d}
    wrong_keys = [k for k in ["A", "B", "C", "D"] if k != correct]
    keep_wrong = random.choice(wrong_keys)
    remaining_keys = sorted([correct, keep_wrong])

    rows = [
        [InlineKeyboardButton(text=f"{k}) {options_map[k]}", callback_data=f"liveans_{q_id}_{k}_{correct}")]
        for k in remaining_keys
    ]
    await callback.answer("💡 2 ta xato variant olib tashlandi! (-30 ball)")
    try:
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except:
        pass

async def run_duel_session(user_id, subject_id, grade, rival_id=None, custom_questions=None, is_mistake_mode=False):
    questions = custom_questions if custom_questions else get_random_questions(subject_id, grade, limit=10)
    if not questions:
        await bot.send_message(user_id, f"Kechirasiz, bu fan va {grade}-sinf uchun hali savollar kiritilmagan!")
        return

    duel_detailed_stats[user_id] = []
    live_duel_sessions[user_id] = {
        "score": 0, 
        "rival_id": rival_id, 
        "point_val": 5 if is_mistake_mode else 10,
        "is_mistake_mode": is_mistake_mode
    }

    for i, q in enumerate(questions, 1):
        q_id, q_text, photo_id, opt_a, opt_b, opt_c, opt_d, correct = q
        my_sc = live_duel_sessions.get(user_id, {}).get("score", 0)
        riv_sc = live_duel_sessions.get(rival_id, {}).get("score", 0) if rival_id else 0

        scoreboard = ""
        if rival_id:
            scoreboard = (
                f"📊 <b>JONLI TABLO (Duel)</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🟢 Sizning ball: <b>{my_sc}</b>\n"
                f"🔴 Raqib ball: <b>{riv_sc}</b>\n"
                f"━━━━━━━━━━━━━━━\n\n"
            )

        kb = build_question_kb(q_id, opt_a, opt_b, opt_c, opt_d, correct, include_5050=True)
        full_caption = f"{scoreboard}<b>{i}-savol ({grade}-sinf):</b> ⏳ <i>45 sekunt</i>\n{q_text}"
        
        event = asyncio.Event()
        answered_events[user_id] = event

        if photo_id:
            msg = await bot.send_photo(user_id, photo=photo_id, caption=full_caption, reply_markup=kb, parse_mode="HTML")
        else:
            msg = await bot.send_message(user_id, full_caption, reply_markup=kb, parse_mode="HTML")
        
        try:
            await asyncio.wait_for(event.wait(), timeout=45.0)
        except asyncio.TimeoutError:
            add_mistake(user_id, q_id)
            duel_detailed_stats[user_id].append({
                "user_choice": "Belgilanmadi",
                "correct_choice": correct,
                "is_correct": False
            })
            try:
                if photo_id:
                    await bot.edit_message_caption(chat_id=user_id, message_id=msg.message_id, caption="⏰ Vaqt tugadi!")
                else:
                    await bot.edit_message_text("⏰ Vaqt tugadi!", chat_id=user_id, message_id=msg.message_id)
            except:
                pass

    final_score = live_duel_sessions.get(user_id, {}).get("score", 0)
    add_user_points(user_id, final_score)
    new_total_rating = get_user(user_id)[3]

    report = f"📊 <b>Batafsil o'yin statistikasi:</b>\n\n"
    for idx, item in enumerate(duel_detailed_stats.get(user_id, []), 1):
        status = "✅ To'g'ri" if item["is_correct"] else f"❌ Xato (Siz: {item['user_choice']}, To'g'ri: {item['correct_choice']})"
        report += f"<b>{idx}-savol:</b> {status}\n"
    
    report += f"\n🎯 <b>Shu o'yindagi ball:</b> +{final_score} ball"
    report += f"\n⭐ <b>Umumiy reytingingiz:</b> {new_total_rating} ball ({get_user_league(new_total_rating)})"
    await bot.send_message(user_id, report, parse_mode="HTML")

    if rival_id:
        duel_finished_scores[user_id] = final_score
        if rival_id in duel_finished_scores:
            rival_score = duel_finished_scores.pop(rival_id)
            duel_finished_scores.pop(user_id, None)

            if final_score > rival_score:
                add_user_points(user_id, 20)
                add_user_points(rival_id, -20)
                await bot.send_message(user_id, f"🏆 <b>DUEL G'OLIBI!</b>\nSiz ({final_score}) : ({rival_score}) Raqib\n🎁 G'alaba uchun <b>+20 ball</b>!", parse_mode="HTML")
                await bot.send_message(rival_id, f"😔 <b>Duelda yutqazdingiz.</b>\nSiz ({rival_score}) : ({final_score}) Raqib\n📉 Reytingdan <b>-20 ball</b>.", parse_mode="HTML")
            elif rival_score > final_score:
                add_user_points(rival_id, 20)
                add_user_points(user_id, -20)
                await bot.send_message(rival_id, f"🏆 <b>DUEL G'OLIBI!</b>\nSiz ({rival_score}) : ({final_score}) Raqib\n🎁 G'alaba uchun <b>+20 ball</b>!", parse_mode="HTML")
                await bot.send_message(user_id, f"😔 <b>Duelda yutqazdingiz.</b>\nSiz ({final_score}) : ({rival_score}) Raqib\n📉 Reytingdan <b>-20 ball</b>.", parse_mode="HTML")
            else:
                await bot.send_message(user_id, f"🤝 <b>DURRANG!</b> ({final_score} : {rival_score})", parse_mode="HTML")
                await bot.send_message(rival_id, f"🤝 <b>DURRANG!</b> ({rival_score} : {final_score})", parse_mode="HTML")
        else:
            await bot.send_message(user_id, "⏳ Raqibingiz savollarni tugatishini kutyapmiz...")

    duel_detailed_stats.pop(user_id, None)
    live_duel_sessions.pop(user_id, None)
    answered_events.pop(user_id, None)

@dp.callback_query(F.data.startswith("liveans_"))
async def live_answer_handler(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    q_id = int(data_parts[1])
    user_choice = data_parts[2]
    correct_choice = data_parts[3]
    user_id = callback.from_user.id

    if user_id not in live_duel_sessions:
        return await callback.answer("Bu savolning vaqti tugagan!", show_alert=True)

    is_correct = (user_choice == correct_choice)
    pts = live_duel_sessions[user_id].get("point_val", 10)

    if is_correct:
        live_duel_sessions[user_id]["score"] += pts
        remove_mistake(user_id, q_id)
        await callback.answer(f"✅ To'g'ri! +{pts} ball", show_alert=False)
    else:
        add_mistake(user_id, q_id)
        await callback.answer(f"❌ Xato! To'g'ri javob: {correct_choice}", show_alert=False)
    
    duel_detailed_stats.setdefault(user_id, []).append({
        "user_choice": user_choice,
        "correct_choice": correct_choice,
        "is_correct": is_correct
    })

    try:
        res_text = f"✅ <b>To'g'ri javob (+{pts} ball)!</b>" if is_correct else f"❌ <b>Xato! (To'g'ri javob: {correct_choice})</b>"
        if callback.message.photo:
            await callback.message.edit_caption(caption=res_text, parse_mode="HTML")
        else:
            await callback.message.edit_text(res_text, parse_mode="HTML")
    except:
        pass

    if user_id in answered_events:
        answered_events[user_id].set()


# ==================== PROMOKOD BILAN ULANISH ====================
@dp.message(F.text == "🤝 Promokod orqali ulanish")
async def promo_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Promokod kiritish", callback_data="promo_enter")],
        [InlineKeyboardButton(text="➕ Promokod yaratish", callback_data="promo_create")]
    ])
    await message.answer("Do'stingiz bilan promokod orqali ulanish:", reply_markup=kb)

@dp.callback_query(F.data == "promo_create")
async def promo_create_handler(callback: types.CallbackQuery):
    subjects = get_subjects()
    if not subjects:
        return await callback.answer("Hozircha fanlar yo'q!", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=sub[1], callback_data=f"mk_promo_{sub[0]}")] for sub in subjects
    ])
    await callback.message.edit_text("Qaysi fan bo'yicha promokod yaratmoqchisiz?", reply_markup=kb)

@dp.callback_query(F.data.startswith("mk_promo_"))
async def make_promo_code(callback: types.CallbackQuery):
    subject_id = int(callback.data.split("_")[2])
    code = create_promo(callback.from_user.id, subject_id)
    await callback.message.edit_text(f"✅ Promokod yaratildi!\n\n🔑 Kod: <code>{code}</code>\n\nBu kodni do'stingizga yuboring.", parse_mode="HTML")

@dp.callback_query(F.data == "promo_enter")
async def promo_enter_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("5 xonali promokodni kiriting:", reply_markup=cancel_kb)
    await state.set_state(PromoState.enter_code)
    await callback.answer()

@dp.message(PromoState.enter_code)
async def process_promo(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    promo = get_promo(code)
    if not promo or promo[2] != 'active':
        return await message.answer("❌ Bunday promokod topilmadi yoki ishlatilgan!")

    creator_id, subject_id, _ = promo
    if creator_id == message.from_user.id:
        return await message.answer("O'zingiz yaratgan kodga o'zingiz kira olmaysiz!")

    use_promo(code)
    await state.clear()
    
    user = get_user(message.from_user.id)
    is_adm = is_admin(message.from_user.id)
    await message.answer("🎉 Promokod ulandi! Duel boshlanmoqda...", reply_markup=main_menu_kb(is_adm))
    await bot.send_message(creator_id, "🎉 Do'stingiz promokod orqali ulandi! Duel boshlanmoqda...")

    asyncio.create_task(run_duel_session(message.from_user.id, subject_id, user[2], creator_id))
    asyncio.create_task(run_duel_session(creator_id, subject_id, user[2], message.from_user.id))


# ==================== ADMIN PANEL VA OMMAVIY (.TXT) SAVOL YUKLASH ====================
@dp.message(F.text == "👑 Admin Panel")
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("👑 Admin paneliga xush kelibsiz:", reply_markup=admin_menu_kb)

@dp.message(F.text == "🔙 Asosiy menyu")
async def back_menu(message: types.Message, state: FSMContext):
    await state.clear()
    is_adm = is_admin(message.from_user.id)
    await message.answer("Asosiy menyu:", reply_markup=main_menu_kb(is_adm))

# --- FAYLDAN OMMAVIY SAVOL YUKLASH (.TXT) ---
@dp.message(F.text == "📂 Fayldan savol yuklash (.txt)")
async def bulk_upload_start(message: types.Message):
    if not is_admin(message.from_user.id): return
    subjects = get_subjects()
    if not subjects:
        return await message.answer("Avval fan qo'shing!")
    rows = [[InlineKeyboardButton(text=sub[1], callback_data=f"bulk_sub_{sub[0]}")] for sub in subjects]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_action")])
    await message.answer("Ommaviy savol yuklash uchun fanni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("bulk_sub_"))
async def bulk_sub_chosen(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data.split("_")[2])
    await state.update_data(bulk_subject_id=subject_id)
    rows = [[InlineKeyboardButton(text=f"{i}-sinf", callback_data=f"bulk_grade_{i}")] for i in range(1, 12)]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_action")])
    await callback.message.edit_text("Qaysi sinf uchun yuklamoqchisiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()

@dp.callback_query(F.data.startswith("bulk_grade_"))
async def bulk_grade_chosen(callback: types.CallbackQuery, state: FSMContext):
    grade = int(callback.data.split("_")[2])
    await state.update_data(bulk_grade=grade)
    await callback.message.delete()
    await callback.message.answer(
        f"✅ <b>{grade}-sinf</b> tanlandi.\n\n"
        f"📂 Endi savollar yozilgan <b>.txt</b> faylni yuboring.\n"
        f"Har bir qator quyidagi formatda (`|` belgisi bilan ajratilgan) bo'lishi kerak:\n\n"
        f"<code>Savol matni | A variant | B variant | C variant | D variant | To'g'ri harf (A/B/C/D)</code>\n\n"
        f"<b>Misol:</b>\n"
        f"<code>2+2 nechiga teng? | 3 | 4 | 5 | 6 | B</code>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(AdminState.bulk_file)
    await callback.answer()

@dp.message(AdminState.bulk_file, F.document)
async def process_bulk_txt(message: types.Message, state: FSMContext):
    if not message.document.file_name.endswith(".txt"):
        return await message.answer("❌ Iltimos, faqat <b>.txt</b> formatidagi fayl yuboring!", parse_mode="HTML")
    
    data = await state.get_data()
    subject_id = data['bulk_subject_id']
    grade = data['bulk_grade']

    temp_path = f"temp_{message.from_user.id}.txt"
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, destination=temp_path)

    added_count = 0
    with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = [p.strip() for p in line.strip().split("|")]
            if len(parts) >= 6:
                q_text, a, b, c, d, corr = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5].upper()
                if corr in ["A", "B", "C", "D"]:
                    add_question(subject_id, grade, q_text, None, a, b, c, d, corr)
                    added_count += 1

    if os.path.exists(temp_path):
        os.remove(temp_path)

    await state.clear()
    await message.answer(f"🎉 Fayldan jami <b>{added_count} ta</b> savol muvaffaqiyatli bazaga qo'shildi!", reply_markup=admin_menu_kb, parse_mode="HTML")

# --- MAJBURIY OBUNA KANALLARINI BOSHQARISH ---
@dp.message(F.text == "📢 Majburiy obuna")
async def manage_channels(message: types.Message):
    if not is_admin(message.from_user.id): return
    channels = get_channels_db()
    text = "📢 <b>Majburiy obuna kanallari:</b>\n\n"
    rows = []
    if channels:
        for ch_id, chat_id, title, link in channels:
            text += f"• <a href='{link}'>{title}</a> (<code>{chat_id}</code>)\n"
            rows.append([InlineKeyboardButton(text=f"🗑 O'chirish: {title}", callback_data=f"del_ch_{ch_id}")])
    else:
        text += "<i>Hozircha hech qanday kanal ulanmagan.</i>\n"

    rows.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_new_channel")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML", disable_web_page_preview=True)

@dp.callback_query(F.data == "add_new_channel")
async def ask_new_channel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await callback.message.delete()
    await callback.message.answer(
        "📢 <b>Kanal ulash:</b>\n1. Botni kanalga Admin qiling.\n2. Kanal havolasini (<code>@kanal_nomi</code>) yuboring:",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(AdminState.add_channel)
    await callback.answer()

@dp.message(AdminState.add_channel)
async def save_new_channel(message: types.Message, state: FSMContext):
    raw_input = message.text.strip()
    chat_identifier = raw_input
    if "t.me/" in raw_input:
        parts = raw_input.split("t.me/")[-1].split("/")[0].split("?")[0]
        if not parts.startswith("+"):
            chat_identifier = f"@{parts}"
    elif not raw_input.startswith("@") and not raw_input.lstrip("-").isdigit():
        chat_identifier = f"@{raw_input}"

    try:
        chat = await bot.get_chat(chat_identifier)
        bot_member = await bot.get_chat_member(chat_id=chat.id, user_id=bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            return await message.answer("❌ Bot bu kanalda admin emas! Avval Admin qiling.", parse_mode="HTML")

        invite_link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or await bot.export_chat_invite_link(chat.id))
        add_channel_db(chat.id, chat.title, invite_link)
        await state.clear()
        await message.answer(f"✅ <b>«{chat.title}»</b> ulandi!", reply_markup=admin_menu_kb, parse_mode="HTML")
    except Exception:
        await message.answer("❌ Kanal topilmadi yoki bot u yerda admin emas!", parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_ch_"))
async def remove_channel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    delete_channel_db(int(callback.data.split("_")[2]))
    await callback.answer("✅ Kanal o'chirildi!")
    await callback.message.delete()
    await manage_channels(callback.message)

# --- FAN VA SAVOL QO'SHISH ---
@dp.message(F.text == "➕ Fan qo'shish")
async def admin_add_subj(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await message.answer("Yangi fan nomini kiriting:", reply_markup=cancel_kb)
    await state.set_state(AdminState.add_subject)

@dp.message(AdminState.add_subject)
async def save_subject(message: types.Message, state: FSMContext):
    add_subject(message.text.strip())
    await state.clear()
    await message.answer(f"✅ '{message.text.strip()}' fani qo'shildi!", reply_markup=admin_menu_kb)

@dp.message(F.text == "📝 Savol qo'shish")
async def admin_add_q(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    subjects = get_subjects()
    if not subjects:
        return await message.answer("Avval fan qo'shing!")
    rows = [[InlineKeyboardButton(text=sub[1], callback_data=f"q_sub_{sub[0]}")] for sub in subjects]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_action")])
    await message.answer("Qaysi fan bo'yicha savol qo'shmoqchisiz?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("q_sub_"))
async def q_subject_chosen(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(subject_id=int(callback.data.split("_")[2]))
    rows = [[InlineKeyboardButton(text=f"{i}-sinf", callback_data=f"q_grade_{i}")] for i in range(1, 12)]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_action")])
    await callback.message.edit_text("Bu savol <b>qaysi sinfga</b> tegishli?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("q_grade_"))
async def q_grade_chosen(callback: types.CallbackQuery, state: FSMContext):
    grade = int(callback.data.split("_")[2])
    await state.update_data(grade=grade)
    await callback.message.delete()
    await callback.message.answer(
        f"✅ <b>{grade}-sinf</b> tanlandi.\n📸 Savol matnini yozing yoki savol rasmini yuboring:",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(AdminState.q_content)
    await callback.answer()

@dp.message(AdminState.q_content)
async def q_content_entered(message: types.Message, state: FSMContext):
    if message.photo:
        photo_id = message.photo[-1].file_id
        q_text = message.caption if message.caption else "Rasmdagi savolni ishlang:"
        await state.update_data(photo_id=photo_id, q_text=q_text)
    elif message.text:
        await state.update_data(photo_id=None, q_text=message.text)
    else:
        return await message.answer("Iltimos, faqat matn yoki rasm yuboring!")

    await message.answer("Variantlarni 4 ta qatorda (A, B, C, D ketma-ketligida) kiriting:", reply_markup=cancel_kb)
    await state.set_state(AdminState.q_options)

@dp.message(AdminState.q_options)
async def q_options_entered(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Variantlarni matn ko'rinishida kiriting!")
    lines = [line.strip() for line in message.text.split("\n") if line.strip()]
    if len(lines) < 4:
        return await message.answer("Kamida 4 ta variantni alohida qatorlarda kiriting!")
    
    await state.update_data(opt_a=lines[0], opt_b=lines[1], opt_c=lines[2], opt_d=lines[3])
    await message.answer("To'g'ri javob harfini kiriting (A, B, C yoki D):", reply_markup=cancel_kb)
    await state.set_state(AdminState.q_correct)

@dp.message(AdminState.q_correct)
async def q_correct_entered(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Harf kiriting (A, B, C yoki D)!")
    correct = message.text.strip().upper()
    if correct not in ['A', 'B', 'C', 'D']:
        return await message.answer("Faqat A, B, C yoki D harfini yozing!")
    
    data = await state.get_data()
    add_question(data['subject_id'], data['grade'], data['q_text'], data['photo_id'], data['opt_a'], data['opt_b'], data['opt_c'], data['opt_d'], correct)
    await state.clear()
    await message.answer("✅ Savol muvaffaqiyatli bazaga qo'shildi!", reply_markup=admin_menu_kb)

# --- BACKUP VA RESTORE ---
@dp.message(F.text == "💾 Bazani olish (Backup)")
async def backup_database(message: types.Message):
    if not is_admin(message.from_user.id): return
    if os.path.exists(DB_NAME):
        await message.answer_document(document=FSInputFile(DB_NAME), caption="✅ <b>Ma'lumotlar bazasi nusxasi!</b>", parse_mode="HTML")
    else:
        await message.answer("Baza fayli topilmadi!")

@dp.message(F.text == "📥 Bazani tiklash")
async def ask_restore_db(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await message.answer("📂 Oldin saqlab olingan <b>.db</b> baza faylini yuboring:", reply_markup=cancel_kb, parse_mode="HTML")
    await state.set_state(AdminState.restore_db)

@dp.message(AdminState.restore_db, F.document)
async def process_restore_db(message: types.Message, state: FSMContext):
    if not message.document.file_name.endswith(".db"):
        return await message.answer("❌ Faqat <b>.db</b> formatidagi faylni yuboring!", parse_mode="HTML")
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, destination=DB_NAME)
    await state.clear()
    await message.answer("🎉 <b>Baza muvaffaqiyatli tiklandi!</b>", reply_markup=admin_menu_kb, parse_mode="HTML")

# --- E'LON YUBORISH ---
@dp.message(F.text == "📢 E'lon yuborish")
async def admin_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await message.answer("Barcha foydalanuvchilarga yuboriladigan e'lon matnini kiriting:", reply_markup=cancel_kb)
    await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def send_broadcast(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT telegram_id FROM users")
        users = cur.fetchall()

    success = 0
    for u in users:
        try:
            await bot.send_message(u[0], f"📢 <b>E'lon:</b>\n\n{text}", parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ E'lon {success} ta foydalanuvchiga yuborildi!", reply_markup=admin_menu_kb)


# ==================== RENDER UCHUN WEB SERVER VA ISHGA TUSHIRISH ====================
async def health_check(request):
    return web.Response(text="Smart School Bot is Live and Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render avtomatik ravishda PORT beradi, u orqali serverni bog'laymiz
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server {port}-portda ishga tushdi (Render Live holatda)...")

async def main():
    init_db()
    # 1. Render "In Progress" bo'lib qolmasligi uchun fonda port ochamiz
    await start_web_server()
    # 2. Eskirib qolgan xabarlarni o'tkazib yuborib, pollingni boshlaymiz
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

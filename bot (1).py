import asyncio
import logging
import os
import re
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Укажите токен в переменной окружения BOT_TOKEN на хостинге!")

ADMIN_ID = 8402707157
SUPPORT_URL = f"tg://user?id={ADMIN_ID}"
STAR_RATE = Decimal("1.40")
PACKAGES = [50, 100, 150, 200, 250, 300, 350]

PHOTOS = [
    "https://unlimbot.hb.ru-msk.vkcloud-storage.ru/uploads/0128ee6b6295495da55096a5fb2378c6ab02bafcd17b9823.jpg",
    "https://unlimbot.hb.ru-msk.vkcloud-storage.ru/uploads/c79913abe8f7482ab28080b7821a77a469a3d6ace50d1056.jpg",
    "https://unlimbot.hb.ru-msk.vkcloud-storage.ru/uploads/b5d4d9d5250f4b6686a1cd2bde42bcd353372e9db2914e98.jpg",
]

REQUISITES = (
    "Оплата через СБП\n"
    "Телефон: 89878343491\n"
    "Банк: Альфа-Банк (выбирайте именно его)\n"
    "Получатель: Иван С.\n"
    "В комментарии к переводу ничего не пишите!"
)

DB_PATH = os.environ.get("DB_PATH", "data/shop.sqlite3")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    subscribed INTEGER NOT NULL DEFAULT 0,
    promo TEXT
);
CREATE TABLE IF NOT EXISTS promos (
    code TEXT PRIMARY KEY,
    percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 99),
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    recipient TEXT NOT NULL,
    cents INTEGER NOT NULL,
    promo TEXT,
    percent INTEGER NOT NULL,
    status TEXT NOT NULL,
    receipt_id TEXT,
    receipt_type TEXT
);
""")
db.commit()

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN)
dp = Dispatcher()
broadcast_task = None


class Flow(StatesGroup):
    recipient = State()
    promo = State()
    create_code = State()
    create_percent = State()
    disable_code = State()
    broadcast = State()
    confirm_broadcast = State()


def execute(sql, args=()):
    cur = db.execute(sql, args)
    db.commit()
    return cur


def user(uid):
    execute("INSERT OR IGNORE INTO users(id) VALUES (?)", (uid,))
    return db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in rows
    ])


def menu(uid):
    subscribed = user(uid)["subscribed"]
    rows = [
        [("⭐ Купить Stars", "buy")],
        [("🎫 Ввести промокод", "promo"), ("Сбросить скидку", "reset_promo")],
        [("🔕 Отписаться" if subscribed else "🔔 Подписаться на рассылку", "subscribe")],
        [("💬 Поддержка", "support")],
    ]
    if uid == ADMIN_ID:
        rows.append([("🛠 Админ-панель", "admin")])
    return kb(*rows)


def admin_kb():
    return kb(
        [("📢 Рассылка", "a_broadcast")],
        [("➕ Создать промокод", "a_create")],
        [("📋 Промокоды", "a_list"), ("Отключить код", "a_disable")],
        [("🧾 Заказы на проверке", "a_orders")],
        [("🏠 Меню", "home")],
    )


def discount(uid):
    row = user(uid)
    promo = db.execute(
        "SELECT * FROM promos WHERE code=? AND active=1", (row["promo"],)
    ).fetchone()
    return (promo["code"], promo["percent"]) if promo else (None, 0)


def price(stars, percent):
    value = (
        Decimal(stars) * STAR_RATE * Decimal(100 - percent) / 100
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def money(cents):
    return f"{cents // 100}.{cents % 100:02d} ₽"


async def photo(target, index, text, markup=None):
    try:
        await target.answer_photo(PHOTOS[index], caption=text, reply_markup=markup)
    except TelegramAPIError:
        logging.warning("Не удалось отправить баннер %s", index + 1)
        await target.answer(text, reply_markup=markup)


async def home(target, uid):
    await photo(
        target, 0,
        "👋 Добро пожаловать!\n"
        "Telegram Stars — 1.40 ₽ за штуку.\n"
        "Минимальный заказ: 50 звёзд.\nВыберите действие:",
        menu(uid),
    )


async def packages(target, uid):
    code, percent = discount(uid)
    rows = [[(f"⭐ {n} — {money(price(n, percent))}", f"pkg:{n}")]
            for n in PACKAGES]
    rows.append([("🏠 Меню", "home")])
    label = f"Промокод: {code}, скидка {percent}%." if code else "Без промокода."
    await photo(target, 1, f"⭐ Выберите количество звёзд.\n{label}", kb(*rows))


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    user(message.from_user.id)
    await state.clear()
    await home(message, message.from_user.id)


@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ввод отменён. Для меню отправьте /start.")


@dp.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    await state.clear()
    await message.answer("🛠 Админ-панель", reply_markup=admin_kb())


@dp.callback_query()
async def callbacks(c, state: FSMContext):
    global broadcast_task
    if not c.message or c.message.chat.type != "private":
        await c.answer("Откройте личный чат с ботом.")
        return
    uid, data = c.from_user.id, c.data or ""
    if (data == "admin" or data.startswith(("a_", "decision:"))) and uid != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return
    await c.answer()
    user(uid)

    if data == "home":
        await state.clear()
        await home(c.message, uid)
    elif data == "buy":
        await state.clear()
        await packages(c.message, uid)
    elif data == "support":
        await c.message.answer(
            "💬 Техподдержка",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Написать", url=SUPPORT_URL)]]
            ),
        )
    elif data == "subscribe":
        execute("UPDATE users SET subscribed=1-subscribed WHERE id=?", (uid,))
        status_text = "Подписка включена." if user(uid)["subscribed"] else "Вы отписались."
        await c.message.answer(status_text, reply_markup=menu(uid))
    elif data == "promo":
        await state.clear()
        await state.set_state(Flow.promo)
        await c.message.answer("🎫 Введите промокод:\nДля отмены отправьте /cancel")
    elif data == "reset_promo":
        execute("UPDATE users SET promo=NULL WHERE id=?", (uid,))
        await c.message.answer("Промокод сброшен.")
    elif data.startswith("pkg:"):
        try:
            stars = int(data.split(":")[1])
        except ValueError:
            return
        if stars not in PACKAGES:
            return
        await state.clear()
        await state.update_data(stars=stars)
        await state.set_state(Flow.recipient)
        await photo(
            c.message, 2,
            f"Вы выбрали: **⭐ {stars} Stars**\n\n"
            "Кому отправить звёзды? Введите @username или нажмите кнопку «Себе»:",
            kb([("👤 Себе", "self")], [("🏠 Меню", "home")])
        )
    elif data == "self":
        if await state.get_state() != Flow.recipient.state:
            await c.message.answer("Сначала выберите пакет звёзд.")
            return
        if not c.from_user.username:
            await c.message.answer("Укажите username в настройках Telegram или введите @username получателя.")
            return
        await invoice(c.message, uid, "@" + c.from_user.username, state)
    elif data.startswith("cancel_order:"):
        try:
            oid = int(data.split(":")[1])
        except ValueError:
            return
        count = execute(
            "UPDATE orders SET status='cancelled' WHERE id=? AND user_id=? AND status='awaiting'",
            (oid, uid)
        ).rowcount
        await c.message.answer("Заказ отменён." if count else "Заказ уже нельзя отменить.")
    elif data == "admin":
        await state.clear()
        await c.message.answer("🛠 Админ-панель", reply_markup=admin_kb())
    elif data == "a_create":
        await state.clear()
        await state.set_state(Flow.create_code)
        await c.message.answer("➕ Введите название нового промокода (например: `SALE20`):")
    elif data == "a_disable":
        await state.clear()
        await state.set_state(Flow.disable_code)
        await c.message.answer("❌ Введите код промокода, который нужно отключить:")
    elif data == "a_list":
        rows = db.execute("SELECT * FROM promos ORDER BY code").fetchall()
        lines = [f"🏷 <code>{r['code']}</code> — скидка <b>{r['percent']}%</b> ({'активен' if r['active'] else 'отключен'})" for r in rows]
        for i in range(0, max(len(lines), 1), 30):
            chunk = "\n".join(lines[i:i+30]) if lines else "Промокодов пока нет."
            await c.message.answer(chunk, parse_mode="HTML")
    elif data == "a_orders":
        rows = db.execute("SELECT * FROM orders WHERE status='review' ORDER BY id DESC LIMIT 20").fetchall()
        if not rows:
            await c.message.answer("🧾 Нет заказов на проверке.")
        for row in rows:
            await send_review(row)
    elif data.startswith("decision:"):
        parts = data.split(":")
        if len(parts) != 3 or parts[1] not in ("done", "rejected") or not parts[2].isdigit():
            return
        status, oid = parts[1], int(parts[2])
        order = db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order or order["status"] != "review":
            await c.message.answer("Заказ уже обработан.")
            return
        execute("UPDATE orders SET status=? WHERE id=? AND status='review'", (status, oid))
        
        user_text = (
            f"⭐ **Ваши {order['stars']} Stars успешно отправлены!**\nСпасибо за покупку!"
            if status == "done"
            else f"❌ Заказ №{oid} отклонён администратором."
        )
        try:
            await bot.send_message(order["user_id"], user_text, parse_mode="Markdown")
            notice = "Клиент уведомлен."
        except TelegramAPIError:
            notice = "Не удалось уведомить клиента."
        
        await c.message.edit_reply_markup(reply_markup=None)
        await c.message.answer(f"Заказ №{oid} отмечен как {status}. {notice}")
    elif data == "a_broadcast":
        await state.clear()
        await state.set_state(Flow.broadcast)
        await c.message.answer("📢 Отправьте пост для рассылки (текст, фото или документ):")
    elif data == "a_send":
        if await state.get_state() != Flow.confirm_broadcast.state:
            await c.message.answer("Нет подготовленной рассылки.")
            return
        if broadcast_task and not broadcast_task.done():
            await c.message.answer("Рассылка уже выполняется.")
            return
        draft = await state.get_data()
        await state.clear()
        broadcast_task = asyncio.create_task(broadcast(draft["source"], draft["message_id"]))
        await c.message.answer("🚀 Рассылка запущена!")


@dp.message(Flow.promo)
async def apply_promo(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    row = db.execute("SELECT * FROM promos WHERE code=? AND active=1", (code,)).fetchone()
    if not row:
        await message.answer("❌ Неверный или отключенный промокод. Попробуйте еще раз или /cancel")
        return
    user(message.from_user.id)
    execute("UPDATE users SET promo=? WHERE id=?", (code, message.from_user.id))
    await state.clear()
    await message.answer(f"✅ Промокод активирован! Ваша скидка: <b>{row['percent']}%</b>", parse_mode="HTML", reply_markup=menu(message.from_user.id))


@dp.message(Flow.recipient)
async def recipient_msg(message: Message, state: FSMContext):
    name = (message.text or "").strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", name):
        await message.answer("⚠️ Введите корректный @username (без пробелов и спецсимволов).")
        return
    await invoice(message, message.from_user.id, "@" + name, state)


async def invoice(target, uid, recipient_name, state):
    data = await state.get_data()
    stars = data.get("stars")
    if stars not in PACKAGES:
        await state.clear()
        await target.answer("Ошибка сессии. Начните заново: /start")
        return
    
    code, percent = discount(uid)
    cents = price(stars, percent)
    
    oid = execute(
        "INSERT INTO orders(user_id,stars,recipient,cents,promo,percent,status) VALUES(?,?,?,?,?,?,'awaiting')",
        (uid, stars, recipient_name, cents, code, percent)
    ).lastrowid
    
    await state.clear()
    
    invoice_text = (
        f"🧾 **Счёт на оплату заказа №{oid}**\n\n"
        f"• Количество: **⭐ {stars} Stars**\n"
        f"• Получатель: **{recipient_name}**\n"
        f"• Промокод: `{code or 'нет'}` (скидка {percent}%)\n"
        f"• Сумма к оплате: **{money(cents)}**\n\n"
        f"{REQUISITES}\n\n"
        f"📸 **После перевода обязательно пришлите сюда скриншот или фото чека!**"
    )
    await target.answer(invoice_text, reply_markup=kb([("❌ Отменить заказ", f"cancel_order:{oid}")]), parse_mode="Markdown")


@dp.message(Flow.create_code)
async def create_code_name(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    code = (message.text or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,32}", code):
        await message.answer("❌ Неверный формат. Используйте от 3 до 32 символов (латиница, цифры, _).")
        return
    await state.update_data(code=code)
    await state.set_state(Flow.create_percent)
    await message.answer("🔢 Введите процент скидки (целое число от 1 до 99):")


@dp.message(Flow.create_percent)
async def create_code_percent(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 99):
        await message.answer("❌ Введите число от 1 до 99.")
        return
    code = (await state.get_data())["code"]
    percent = int(text)
    execute("INSERT OR REPLACE INTO promos(code,percent,active) VALUES(?,?,1)", (code, percent))
    await state.clear()
    await message.answer(f"✅ Промокод <code>{code}</code> со скидкой <b>{percent}%</b> успешно создан!", parse_mode="HTML", reply_markup=admin_kb())


@dp.message(Flow.disable_code)
async def disable_promo(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    code = (message.text or "").strip().upper()
    count = execute("UPDATE promos SET active=0 WHERE code=?", (code,)).rowcount
    await state.clear()
    await message.answer("✅ Промокод отключен." if count else "❌ Промокод не найден.", reply_markup=admin_kb())


@dp.message(Flow.broadcast)
async def broadcast_draft(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.media_group_id:
        await message.answer("⚠️ Альбомы не поддерживаются. Отправьте одно сообщение.")
        return
    preview = await bot.copy_message(ADMIN_ID, message.chat.id, message.message_id)
    await state.update_data(source=ADMIN_ID, message_id=preview.message_id)
    await state.set_state(Flow.confirm_broadcast)
    count = db.execute("SELECT COUNT(*) FROM users WHERE subscribed=1").fetchone()[0]
    await message.answer(f"👥 Получателей (подписаны): {count}\nОтправить рассылку?", reply_markup=kb([("✅ Отправить", "a_send")], [("❌ Отмена", "admin")]))


async def broadcast(source, message_id):
    success = failed = 0
    ids = [r[0] for r in db.execute("SELECT id FROM users WHERE subscribed=1").fetchall()]
    try:
        for uid in ids:
            try:
                await bot.copy_message(
                    uid, source, message_id,
                    reply_markup=kb([("🔕 Отписаться", "subscribe")])
                )
                success += 1
            except TelegramForbiddenError:
                execute("UPDATE users SET subscribed=0 WHERE id=?", (uid,))
                failed += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await bot.copy_message(uid, source, message_id, reply_markup=kb([("🔕 Отписаться", "subscribe")]))
                    success += 1
                except Exception:
                    failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
    finally:
        try:
            await bot.send_message(ADMIN_ID, f"📢 Рассылка завершена!\nУспешно: {success}\nОшибок/заблокировали: {failed}")
        except Exception:
            pass


async def send_review(order):
    oid = order["id"]
    text = (
        f"🔔 **Заказ №{oid} на проверку**\n"
        f"👤 Покупатель ID: `{order['user_id']}`\n"
        f"🎁 Получатель: **{order['recipient']}**\n"
        f"⭐ Звёзды: **{order['stars']} шт.**\n"
        f"🏷 Промокод: `{order['promo'] or 'нет'}` ({order['percent']}%)\n"
        f"💰 Сумма: **{money(order['cents'])}**\n\n"
        "Проверьте поступление средств в Альфа-Банке и нажмите кнопку:"
    )
    markup = kb([("✅ Выдано", f"decision:done:{oid}"), ("❌ Отклонить", f"decision:rejected:{oid}")])
    if order["receipt_type"] == "photo":
        await bot.send_photo(ADMIN_ID, photo=order["receipt_id"], caption=text, reply_markup=markup, parse_mode="Markdown")
    else:
        await bot.send_document(ADMIN_ID, document=order["receipt_id"], caption=text, reply_markup=markup, parse_mode="Markdown")


@dp.message(F.photo | F.document)
async def receive_receipt(message: Message):
    if message.chat.type != "private":
        return
    order = db.execute(
        "SELECT * FROM orders WHERE user_id=? AND status='awaiting' ORDER BY id DESC LIMIT 1",
        (message.from_user.id,)
    ).fetchone()
    if not order:
        await message.answer("⚠️ Сначала выберите пакет звёзд и сформируйте заказ через меню /start")
        return
    
    kind = "photo" if message.photo else "document"
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    
    execute(
        "UPDATE orders SET status='review', receipt_id=?, receipt_type=? WHERE id=? AND status='awaiting'",
        (file_id, kind, order["id"])
    )
    order = db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
    
    try:
        await send_review(order)
    except TelegramAPIError:
        pass
    
    await message.answer(
        f"✅ **Чек по заказу №{order['id']} принят!**\n\n"
        "Администратор проверяет оплату. Как только звёзды будут отправлены, бот пришлёт уведомление.",
        parse_mode="Markdown"
    )


@dp.message()
async def fallback_msg(message: Message):
    if message.chat.type == "private":
        await message.answer("Используйте меню или отправьте /start. Чтобы отменить текущее действие — /cancel")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

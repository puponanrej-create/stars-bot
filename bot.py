import asyncio
import logging
import os
import re
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

# Python 3.10+. Токен задаётся на хостинге, не в GitHub.
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN: 8863437103:AAG-tEst8iUbbiRD5UIB01dQC28H5-lVXvA
    raise RuntimeError('Укажите новый токен в переменной окружения BOT_TOKEN')
ADMIN_ID = 8402707157
SUPPORT_URL = f'tg://user?id={ADMIN_ID}'
STAR_RATE = Decimal('1.40')
PACKAGES = [50, 100, 150, 200, 250, 300, 350]
PHOTOS = [
    'https://unlimbot.hb.ru-msk.vkcloud-storage.ru/uploads/0128ee6b6295495da55096a5fb2378c6ab02bafcd17b9823.jpg',
    'https://unlimbot.hb.ru-msk.vkcloud-storage.ru/uploads/c79913abe8f7482ab28080b7821a77a469a3d6ace50d1056.jpg',
    'https://unlimbot.hb.ru-msk.vkcloud-storage.ru/uploads/b5d4d9d5250f4b6686a1cd2bde42bcd353372e9db2914e98.jpg',
]
REQUISITES = ('Оплата через СБП\nТелефон: 89878343491\n'
              'Банк: Альфа-Банк (выбирайте именно его)\nПолучатель: Иван С.\n'
              'В комментарии к переводу ничего не пишите!')
DB_PATH = os.environ.get('DB_PATH', 'data/shop.sqlite3')
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
db.execute('PRAGMA journal_mode=WAL')
db.executescript('''
CREATE TABLE IF NOT EXISTS users (
id INTEGER PRIMARY KEY, subscribed INTEGER NOT NULL DEFAULT 0,
promo TEXT);
CREATE TABLE IF NOT EXISTS promos (
code TEXT PRIMARY KEY, percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 99),
active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS orders (
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
stars INTEGER NOT NULL, recipient TEXT NOT NULL, cents INTEGER NOT NULL,
promo TEXT, percent INTEGER NOT NULL, status TEXT NOT NULL,
receipt_id TEXT, receipt_type TEXT);
''')
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
    execute('INSERT OR IGNORE INTO users(id) VALUES (?)', (uid,))
    return db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
        for row in rows])


def menu(uid):
    subscribed = user(uid)['subscribed']
    rows = [
        [('⭐ Купить Stars', 'buy')],
        [('🎫 Ввести промокод', 'promo'), ('Сбросить скидку', 'reset_promo')],
        [('🔕 Отписаться' if subscribed else '🔔 Подписаться на рассылку', 'subscribe')],
        [('💬 Поддержка', 'support')],
    ]
    if uid == ADMIN_ID:
        rows.append([('🛠 Админ-панель', 'admin')])
    return kb(*rows)


def admin_kb():
    return kb([('📢 Рассылка', 'a_broadcast')],
              [('➕ Создать промокод', 'a_create')],
              [('📋 Промокоды', 'a_list'), ('Отключить код', 'a_disable')],
              [('🧾 Заказы на проверке', 'a_orders')], [('🏠 Меню', 'home')])


def discount(uid):
    u = user(uid)
    row = db.execute('SELECT * FROM promos WHERE code=? AND active=1', (u['promo'],)).fetchone()
    return (row['code'], row['percent']) if row else (None, 0)


def price(stars, percent):
    rub = (Decimal(stars) * STAR_RATE * Decimal(100-percent) / 100).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)
    return int(rub * 100)


def money(cents):
    return f'{cents // 100}.{cents % 100:02d} ₽'


async def photo(target, index, text, markup=None):
    # При недоступности внешних картинок функциональность остаётся доступной.
    try:
        await target.answer_photo(PHOTOS[index], caption=text, reply_markup=markup)
    except TelegramAPIError:
        logging.warning('Не удалось отправить баннер %s', index + 1)
        await target.answer(text, reply_markup=markup)


async def home(target, uid):
    await photo(target, 0, '👋 Добро пожаловать!\nTelegram Stars — 1.40 ₽ за штуку.\n'
                'Минимальный заказ: 50 звёзд.\nВыберите действие:', menu(uid))


async def packages(target, uid):
    code, percent = discount(uid)
    rows = [[(f'⭐ {n} — {money(price(n, percent))}', f'pkg:{n}')] for n in PACKAGES]
    rows.append([('🏠 Меню', 'home')])
    await photo(target, 1, '⭐ Выберите количество звёзд.\n' +
                (f'Промокод: {code}, скидка {percent}%.' if code else 'Без промокода.'), kb(*rows))


@dp.message(CommandStart())
async def start(m, state: FSMContext):
    if m.chat.type != 'private':
        return
    user(m.from_user.id)
    await state.clear()
    await home(m, m.from_user.id)


@dp.message(Command('cancel'))
async def cancel(m, state: FSMContext):
    await state.clear()
    await m.answer('Ввод отменён. Уже созданные счета не отменены; используйте кнопку в счёте.')


@dp.message(Command('unsubscribe'))
async def unsubscribe(m):
    user(m.from_user.id)
    execute('UPDATE users SET subscribed=0 WHERE id=?', (m.from_user.id,))
    await m.answer('Вы отписались от рассылки.')


@dp.message(Command('admin'))
async def admin(m, state: FSMContext):
    if m.from_user.id != ADMIN_ID or m.chat.type != 'private':
        return
    await state.clear()
    await m.answer('🛠 Админ-панель', reply_markup=admin_kb())


@dp.callback_query()
async def callbacks(c, state: FSMContext):
    global broadcast_task
    if not c.message or c.message.chat.type != 'private':
        await c.answer('Откройте личный чат с ботом.')
        return
    uid, data = c.from_user.id, c.data or ''
    if (data == 'admin' or data.startswith(('a_', 'decision:'))) and uid != ADMIN_ID:
        await c.answer('Нет доступа', show_alert=True)
        return
    await c.answer()
    user(uid)
    if data == 'home':
        await state.clear()
        await home(c.message, uid)
    elif data == 'buy':
        await state.clear()
        await packages(c.message, uid)
    elif data == 'support':
        await c.message.answer('💬 Техподдержка', reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text='Написать', url=SUPPORT_URL)]]))
    elif data == 'subscribe':
        execute('UPDATE users SET subscribed=1-subscribed WHERE id=?', (uid,))
        await c.message.answer('Подписка включена.' if user(uid)['subscribed'] else 'Вы отписались.',
                               reply_markup=menu(uid))
    elif data == 'promo':
        await state.clear()
        await state.set_state(Flow.promo)
        await c.message.answer('Введите промокод. Отмена: /cancel\nСкидка применяется к новым счетам.')
    elif data == 'reset_promo':
        execute('UPDATE users SET promo=NULL WHERE id=?', (uid,))
        await c.message.answer('Промокод сброшен для следующих заказов.')
    elif data.startswith('pkg:'):
        try:
            stars = int(data.split(':')[1])
        except ValueError:
            return
        if stars not in PACKAGES:
            return
        await state.clear()
        await state.update_data(stars=stars)
        await state.set_state(Flow.recipient)
        await c.message.answer('Кому отправить звёзды? Введите @username или нажмите «Себе».',
                               reply_markup=kb([('👤 Себе', 'self')], [('🏠 Меню', 'home')]))
    elif data == 'self':
        if await state.get_state() != Flow.recipient.state:
            await c.message.answer('Сначала выберите пакет звёзд.')

i
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8863437103:AAG-tEst8iUbbiRD5UIB01dQC28H5-lVXvA"
ADMIN_ID = 8402707157
SUPPORT_URL = "tg://user?id=8402707157"

PAYMENT_REQUISITES = (
    "💳 **Оплата через СБП (Система быстрых платежей):**\n"
    "📱 **Номер телефона:** `89878343491`\n"
    "🏦 **Банк:** **Альфа-Банк** (строго выбирать Альфа-Банк!)\n"
    "👤 **Получатель:** Иван С.\n\n"
    "⚠️ В комментарии к переводу ничего не пишите!"
)

STAR_RATE = 1.4
STAR_PACKAGES = [50, 100, 150, 200, 250, 300, 350]
# ===================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class OrderState(StatesGroup):
    waiting_for_recipient_username = State()
    waiting_for_receipt = State()


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐️ Купить Stars", callback_data="buy_stars")],
            [InlineKeyboardButton(text="💬 Тех. поддержка", url=SUPPORT_URL)],
        ]
    )


def stars_choice_kb() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for stars in STAR_PACKAGES:
        price = round(stars * STAR_RATE, 1)
        row.append(InlineKeyboardButton(text=f"⭐️ {stars} шт. — {price}₽", callback_data=f"pkg_{stars}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def recipient_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Себе", callback_data="rec_self")],
            [InlineKeyboardButton(text="🎁 Другому человеку", callback_data="rec_other")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="main_menu")],
        ]
    )


def payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить заказ", callback_data="main_menu")]
        ]
    )


def admin_order_kb(user_id: int, stars: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выдано (Отправил)", callback_data=f"adm_ok_{user_id}_{stars}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_no_{user_id}")
            ]
        ]
    )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 **Добро пожаловать в сервис покупки Telegram Stars!**\n\n"
        "⚡️ У нас вы можете приобрести Telegram Звёзды по **самым выгодным и дешёвым ценам** — всего **1.4₽** за штуку!\n\n"
        "✅ Без лишних комиссий и задержек\n"
        "✅ Быстрая выдача на любой аккаунт\n"
        "✅ Минимальный заказ всего от 50 звёзд\n\n"
        "Для заказа выберите действие в меню ниже:"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="Markdown")


@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🏠 **Главное меню**\n\nВыберите нужный раздел:",
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )
    await call.answer()


@dp.callback_query(F.data == "buy_stars")
async def cb_buy_stars(call: CallbackQuery):
    text = (
        "⭐️ **Выберите количество Telegram Stars для покупки:**\n\n"
        f"🏷 Лучший курс: **1 Звезда = {STAR_RATE}₽**"
    )
    await call.message.edit_text(text, reply_markup=stars_choice_kb(), parse_mode="Markdown")
    await call.answer()


@dp.callback_query(F.data.startswith("pkg_"))
async def cb_choose_package(call: CallbackQuery, state: FSMContext):
    stars = int(call.data.split("_")[1])
    price = round(stars * STAR_RATE, 1)

    await state.update_data(stars=stars, price=price)

    text = (
        f"Вы выбрали: **⭐️ {stars} Stars**\n"
        f"Сумма к оплате: **{price} ₽**\n\n"
        "Кому отправить звёзды?"
    )
    await call.message.edit_text(text, reply_markup=recipient_kb(), parse_mode="Markdown")
    await call.answer()


@dp.callback_query(F.data == "rec_self")
async def cb_recipient_self(call: CallbackQuery, state: FSMContext):
    user_handle = f"@{call.from_user.username}" if call.from_user.username else f"ID: {call.from_user.id}"
    await state.update_data(recipient=user_handle)
    await show_payment_invoice(call.message, state)
    await call.answer()


@dp.callback_query(F.data == "rec_other")
async def cb_recipient_other(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.waiting_for_recipient_username)
    await call.message.edit_text(
        "✏️ Напишите `@username` человека, которому нужно отправить звёзды:\n"
        "*(Например: @durov)*",
        parse_mode="Markdown"
    )
    await call.answer()


@dp.message(OrderState.waiting_for_recipient_username)
async def msg_recipient_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username.startswith("@") and not username.isdigit():
        username = f"@{username}"

    await state.update_data(recipient=username)
    await show_payment_invoice(message, state)


async def show_payment_invoice(target: Message, state: FSMContext):
    data = await state.get_data()
    stars = data["stars"]
    price = data["price"]
    recipient = data["recipient"]

    await state.set_state(OrderState.waiting_for_receipt)

    text = (
        f"🧾 **Счёт на оплату заказа:**\n\n"
        f"• Количество: **⭐️ {stars} Stars**\n"
        f"• Получатель: **{recipient}**\n"
        f"• Сумма к оплате: **{price} ₽**\n\n"
        f"{PAYMENT_REQUISITES}\n\n"
        f"⏳ **Внимание:** На оплату отводится **15 минут**, затем заказ автоматически отменяется.\n\n"
        f"📸 **После перевода обязательно пришлите сюда скриншот или фото чека об оплате!**"
    )
    await target.answer(text, reply_markup=payment_kb(), parse_mode="Markdown")


@dp.message(OrderState.waiting_for_receipt, F.photo | F.document)
async def msg_receipt_received(message: Message, state: FSMContext):
    data = await state.get_data()
    stars = data.get("stars")
    price = data.get("price")
    recipient = data.get("recipient")
    buyer = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"

    await message.answer(
        "✅ **Чек принят на проверку!**\n\n"
        "Администратор проверяет перевод. Как только звёзды будут отправлены, бот сразу пришлёт уведомление.",
        parse_mode="Markdown"
    )
    await state.clear()

    admin_caption = (
        "🔔 **НОВЫЙ ЗАКАЗ НА ПРОВЕРКУ!**\n\n"
        f"👤 Покупатель: {buyer} (ID: `{message.from_user.id}`)\n"
        f"🎁 Получатель: **{recipient}**\n"
        f"⭐️ Звёзды: **{stars} шт.**\n"
        f"💰 Сумма: **{price} ₽**\n\n"
        "Проверьте поступление на Альфа-Банк и нажмите кнопку ниже:"
    )

    if message.photo:
        await bot.send_photo(
            chat_id=ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=admin_caption,
            reply_markup=admin_order_kb(message.from_user.id, stars),
            parse_mode="Markdown"
        )
    elif message.document:
        await bot.send_document(
            chat_id=ADMIN_ID,
            document=message.document.file_id,
            caption=admin_caption,
            reply_markup=admin_order_kb(message.from_user.id, stars),
            parse_mode="Markdown"
        )


@dp.message(OrderState.waiting_for_receipt)
async def msg_receipt_wrong_format(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте именно **скриншот или файл чека** об оплате!")


@dp.callback_query(F.data.startswith("adm_ok_"))
async def cb_admin_confirm(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет доступа!", show_alert=True)
        return

    parts = call.data.split("_")
    user_id = int(parts[2])
    stars = int(parts[3])

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"⭐️ **Ваши {stars} Stars успешно отправлены!**\n\nСпасибо за покупку! Ждём вас снова ❤️",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки пользователю {user_id}: {e}")

    await call.message.edit_caption(
        caption=call.message.caption + "\n\n✅ **ВЫДАНО: Звёзды отправлены клиенту!**",
        reply_markup=None,
        parse_mode="Markdown"
    )
    await call.answer("Клиент уведомлён!")


@dp.callback_query(F.data.startswith("adm_no_"))
async def cb_admin_decline(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет доступа!", show_alert=True)
        return

    user_id = int(call.data.split("_")[2])

    try:
        await bot.send_message(
            chat_id=user_id,
            text="❌ **Платёж не был найден или отклонён.**\nЕсли произошла ошибка, пожалуйста, обратитесь в тех. поддержку.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки пользователю {user_id}: {e}")

    await call.message.edit_caption(
        caption=call.message.caption + "\n\n❌ **ЗАКАЗ ОТКЛОНЁН!**",
        reply_markup=None,
        parse_mode="Markdown"
    )
    await call.answer("Заказ отклонён.")


async def main():
    print("Бот продажи Stars успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

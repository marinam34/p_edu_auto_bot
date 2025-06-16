from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from config import TELEGRAM_TOKEN
from qa_engine import get_answer, add_support_entry
import os


user_roles: dict[int, str] = {}
waiting_for_support: dict[int, bool] = {}
support_messages: dict[int, tuple] = {}

SUPPORT_CHAT_ID   = -1002633010449

BTN_CHANGE_ROLE  = "🔄 Сменить роль"
BTN_CALL_SUPPORT = "👨‍💻 Вызвать специалиста"
BTN_RESTART      = "🔄 Перезапустить бота"

def main_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_CHANGE_ROLE], [BTN_CALL_SUPPORT], [BTN_RESTART]],
        resize_keyboard=True
    )

def role_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Участник",      callback_data="role_participant")],
        [InlineKeyboardButton("Проктор",       callback_data="role_proctor")],
        [InlineKeyboardButton("Администратор", callback_data="role_admin")],
        [InlineKeyboardButton("Менеджер",      callback_data="role_manager")],
        [InlineKeyboardButton("Другое",        callback_data="role_other")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_roles.pop(uid, None)
    waiting_for_support.pop(uid, None)

    await update.message.reply_text(
        "Привет! Я бот ProctorEdu.\nПожалуйста, выберите вашу роль:",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text("Выберите роль:", reply_markup=role_keyboard())

async def cmd_change_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выберите новую роль:", reply_markup=role_keyboard())

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text

    if text == BTN_RESTART:
        return await cmd_start(update, context)
    if text == BTN_CHANGE_ROLE:
        return await cmd_change_role(update, context)
    if text == BTN_CALL_SUPPORT:
        waiting_for_support[uid] = True
        await update.message.reply_text("Напишите вопрос, я передам его специалисту.")
        return

    if uid not in user_roles:
        await update.message.reply_text("Сначала выберите роль:", reply_markup=role_keyboard())
        return

    if waiting_for_support.get(uid):
        role = user_roles.get(uid, "Другое")
        sent = await context.bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            text=f"Запрос от {update.effective_user.first_name} (ID {uid}, роль {role}):\n\n{text}"
        )
        support_messages[sent.message_id] = (uid, text)
        await update.message.reply_text("Ваш вопрос отправлен специалисту. Ожидайте ответа 🙌")
        return

    thinking = await update.message.reply_text("Думаю... 🤔")
    role = user_roles.get(uid, "Другое")
    answer = get_answer(text, role)
    await thinking.delete()

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Вызвать специалиста", callback_data="call_support")]])
    await update.message.reply_text(answer, reply_markup=kb)

async def callback_role_or_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid, data = update.effective_user.id, query.data

    if data.startswith("role_"):
        mapping = {
            "role_participant": "Участник",
            "role_proctor":     "Проктор",
            "role_admin":       "Администратор",
            "role_manager":     "Менеджер",
            "role_other":       "Другое",
        }
        user_roles[uid] = mapping.get(data, "Не указано")
        await query.message.reply_text(
            f"Роль установлена: {user_roles[uid]}\nЗадайте вопрос.",
            reply_markup=main_keyboard()
        )
        return

    if data == "call_support":
        waiting_for_support[uid] = True
        await query.message.reply_text("Опишите ваш вопрос для специалиста:")

async def cmd_reply_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Формат: /reply <ID> <текст>")
    try:
        tgt_uid = int(context.args[0])
        answer  = " ".join(context.args[1:])
        await context.bot.send_message(tgt_uid, f"🧑‍💻 Ответ специалиста:\n\n{answer}")
        waiting_for_support.pop(tgt_uid, None)
        await update.message.reply_text("✅ Ответ отправлен.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def handle_support_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(SUPPORT_CHAT_ID):
        return
    if not update.message.reply_to_message:
        return
    src_msg_id = update.message.reply_to_message.message_id
    if src_msg_id not in support_messages:
        return

    tgt_uid, question_text = support_messages[src_msg_id]
    answer_text = update.message.text

    try:
        await context.bot.send_message(tgt_uid, f"🧑‍💻 Ответ специалиста:\n\n{answer_text}")
        add_support_entry(question_text, answer_text)
        waiting_for_support.pop(tgt_uid, None)
        await update.message.reply_text("✅ Ответ отправлен пользователю.")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось переслать ответ: {e}")

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID этого чата: {update.effective_chat.id}")


app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start",  cmd_start))
app.add_handler(CommandHandler("role",   cmd_change_role))
app.add_handler(CommandHandler("chatid", cmd_chatid))
app.add_handler(CommandHandler("reply",  cmd_reply_support))

app.add_handler(CallbackQueryHandler(callback_role_or_support))
app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Chat(chat_id=SUPPORT_CHAT_ID),
        handle_support_chat
    )
)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question))

print("🤖 Бот запущен и готов к работе.")
app.run_polling()

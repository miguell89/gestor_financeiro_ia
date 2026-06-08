from pathlib import Path
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.handlers import TelegramNotLinked, attach_receipt_file_to_transaction, process_goal_command, process_link_command, process_receipt_photo, process_report_command, process_text_message, save_receipt_transaction
from config.settings import settings

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("gestor_financeiro_bot")


def is_allowed(update: Update):
    if not settings.TELEGRAM_ALLOWED_USER_ID:
        return True

    user = update.effective_user
    return user and str(user.id) == settings.TELEGRAM_ALLOWED_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Comando /start recebido de user_id=%s", update.effective_user.id if update.effective_user else None)
    if not is_allowed(update):
        await update.message.reply_text("Este bot esta restrito ao usuario autorizado.")
        return

    await update.message.reply_text("Oi! Sou seu assistente financeiro IA. Para usar seus dados, vincule sua conta com /vincular CODIGO.")


async def vincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Comando /vincular recebido de user_id=%s", update.effective_user.id if update.effective_user else None)
    if not is_allowed(update):
        await update.message.reply_text("Este bot esta restrito ao usuario autorizado.")
        return

    code = context.args[0] if context.args else ""
    await update.message.reply_text(process_link_command(code, update.effective_user))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Mensagem recebida de user_id=%s: %s", update.effective_user.id if update.effective_user else None, update.message.text)
    if not is_allowed(update):
        await update.message.reply_text("Este bot esta restrito ao usuario autorizado.")
        return

    try:
        goal_answer = process_goal_command(update.message.text, update.effective_user)
        if goal_answer:
            await update.message.reply_text(goal_answer)
            return

        report_answer = process_report_command(update.message.text, update.effective_user)
        if report_answer:
            if report_answer["type"] == "photo":
                with open(report_answer["path"], "rb") as photo:
                    await update.message.reply_photo(photo=photo, caption=report_answer.get("caption"))
                return
            if report_answer["type"] == "document":
                with open(report_answer["path"], "rb") as document:
                    await update.message.reply_document(document=document, caption=report_answer.get("caption"))
                return
            await update.message.reply_text(report_answer["text"])
            return

        answer = process_text_message(update.message.text, update.effective_user)
        await update.message.reply_text(answer)
    except TelegramNotLinked as exc:
        await update.message.reply_text(str(exc))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Foto recebida de user_id=%s", update.effective_user.id if update.effective_user else None)
    if not is_allowed(update):
        await update.message.reply_text("Este bot esta restrito ao usuario autorizado.")
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    Path("data/temp").mkdir(parents=True, exist_ok=True)
    path = f"data/temp/comprovante_{photo.file_unique_id}.jpg"
    await file.download_to_drive(path)

    try:
        message, receipt_data, user_id = process_receipt_photo(path, update.effective_user)
    except TelegramNotLinked as exc:
        await update.message.reply_text(str(exc))
        Path(path).unlink(missing_ok=True)
        return
    context.user_data["pending_receipt"] = receipt_data
    context.user_data["pending_receipt_user_id"] = user_id
    context.user_data["pending_receipt_path"] = path

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Sim, confirmar", callback_data="receipt_confirm")],
            [InlineKeyboardButton("Corrigir categoria", callback_data="receipt_fix_category")],
            [InlineKeyboardButton("Ignorar", callback_data="receipt_ignore")],
        ]
    )
    await update.message.reply_text(message, reply_markup=keyboard)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Documento recebido de user_id=%s", update.effective_user.id if update.effective_user else None)
    if not is_allowed(update):
        await update.message.reply_text("Este bot esta restrito ao usuario autorizado.")
        return

    document = update.message.document
    filename = document.file_name or f"documento_{document.file_unique_id}"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in {"pdf", "png", "jpg", "jpeg", "webp"}:
        await update.message.reply_text("Envie apenas imagem ou PDF como comprovante.")
        return

    file = await context.bot.get_file(document.file_id)
    Path("data/temp").mkdir(parents=True, exist_ok=True)
    path = f"data/temp/comprovante_{document.file_unique_id}.{extension}"
    await file.download_to_drive(path)

    try:
        message, receipt_data, user_id = process_receipt_photo(path, update.effective_user)
    except TelegramNotLinked as exc:
        await update.message.reply_text(str(exc))
        Path(path).unlink(missing_ok=True)
        return
    context.user_data["pending_receipt"] = receipt_data
    context.user_data["pending_receipt_user_id"] = user_id
    context.user_data["pending_receipt_path"] = path

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Sim, confirmar", callback_data="receipt_confirm")],
            [InlineKeyboardButton("Corrigir categoria", callback_data="receipt_fix_category")],
            [InlineKeyboardButton("Ignorar", callback_data="receipt_ignore")],
        ]
    )
    await update.message.reply_text(message, reply_markup=keyboard)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.callback_query.answer("Usuario nao autorizado.")
        return

    query = update.callback_query
    await query.answer()

    if query.data == "receipt_confirm":
        receipt_data = context.user_data.get("pending_receipt")
        if not receipt_data:
            await query.edit_message_text("Nao encontrei comprovante pendente para confirmar.")
            return

        user_id = context.user_data.get("pending_receipt_user_id")
        transaction_id = save_receipt_transaction(receipt_data, user_id)
        attach_receipt_file_to_transaction(context.user_data.get("pending_receipt_path"), user_id, transaction_id, receipt_data)
        context.user_data.pop("pending_receipt", None)
        context.user_data.pop("pending_receipt_user_id", None)
        context.user_data.pop("pending_receipt_path", None)
        await query.edit_message_text("Comprovante confirmado e lancamento salvo. Esse Pix nao escapou.")
        return

    if query.data == "receipt_fix_category":
        await query.edit_message_text("Me envie a categoria correta por mensagem. Nesta versao eu deixei o comprovante pendente para ajuste manual.")
        return

    if query.data == "receipt_ignore":
        path = context.user_data.get("pending_receipt_path")
        if path:
            Path(path).unlink(missing_ok=True)
        context.user_data.pop("pending_receipt", None)
        context.user_data.pop("pending_receipt_user_id", None)
        context.user_data.pop("pending_receipt_path", None)
        await query.edit_message_text("Comprovante ignorado. Nada foi salvo.")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Erro no bot. update=%s", update, exc_info=context.error)


def main():
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN no arquivo .env.")
    if settings.TELEGRAM_MODE != "polling":
        raise RuntimeError("TELEGRAM_MODE=webhook ainda nao esta habilitado. Use TELEGRAM_MODE=polling para o MVP no Render.")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vincular", vincular))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_error_handler(handle_error)
    logger.info("Bot iniciado. Username deve aparecer no Telegram como @GestorBott_bot")
    app.run_polling()


if __name__ == "__main__":
    main()

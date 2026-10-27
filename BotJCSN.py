import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==============================================================================
# CONFIGURACIÓN DE CREDENCIALES (variables de entorno, NUNCA en el código)
# ==============================================================================
# Local: se leen del archivo .env (ignorado por git).
# Nube: se configuran en el panel del servicio (Variables / Environment).
load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# ⚠️ Verifica en la documentación de Gemini que este nombre de modelo exista.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

faltantes = [n for n, v in (("GEMINI_API_KEY", GEMINI_API_KEY), ("TELEGRAM_TOKEN", TELEGRAM_TOKEN)) if not v]
if faltantes:
    sys.exit(f"❌ Faltan variables de entorno: {', '.join(faltantes)}")

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
# Evita que httpx imprima la URL (que contiene el token de Telegram) en los logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("bot")

client = genai.Client(api_key=GEMINI_API_KEY)

# Memoria de sesiones por id de usuario (se pierde si el servicio se reinicia)
sesiones_de_chat = {}

# ==============================================================================
# SECCIÓN DE PERSONALIZACIÓN DEL BOT
# ==============================================================================
SYSTEM_INSTRUCTION = """
Eres 'Astra', un asistente académico inteligente desarrollado para la materia de Sistemas Inteligentes.
Tu objetivo es responder de manera clara y con un toque de humor.
Si te preguntan por las actividades del laboratorio o entregas, indica amablemente que
deben consultar las indicaciones de la Dra. Aiblis Susej Herrera Palafox.
Usa formato Markdown con viñetas para explicaciones complejas.
"""

CONFIG_PERSONALIZADA = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    temperature=1,
    max_output_tokens=1100,
)

# ==============================================================================
# COMANDOS DE TELEGRAM
# ==============================================================================
async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "👋 *¡Hola! Soy Deadshot, tu Asistente Inteligente.*\n\n"
        "Estoy listo para ayudarte con tus consultas académicas e investigaciones.\n"
        "• Usa /help para ver la lista de comandos disponibles.\n"
        "• Usa /reset si deseas reiniciar el historial de nuestra conversación."
    )
    await update.message.reply_text(mensaje, parse_mode="Markdown")


async def comando_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ayuda = (
        "📌 *Menú de Ayuda:*\n\n"
        "• `/start` - Iniciar el servicio del bot.\n"
        "• `/help` - Desplegar esta lista de comandos.\n"
        "• `/reset` - Borrar la memoria de contexto del chat actual.\n"
        "• _Envía cualquier mensaje de texto_ para interactuar con Gemini."
    )
    await update.message.reply_text(ayuda, parse_mode="Markdown")


async def comando_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    id_usuario = update.effective_user.id
    if sesiones_de_chat.pop(id_usuario, None) is not None:
        await update.message.reply_text(
            "🧹 *Historial de conversación eliminado.* Tu próxima pregunta iniciará un nuevo chat.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("ℹ️ No tienes ninguna sesión conversacional activa en este momento.")


# ==============================================================================
# PROCESAMIENTO DE MENSAJES Y RESPUESTA
# ==============================================================================
async def responder_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    id_usuario = update.effective_user.id
    texto_recibido = update.message.text

    if id_usuario not in sesiones_de_chat:
        sesiones_de_chat[id_usuario] = client.chats.create(
            model=GEMINI_MODEL,
            config=CONFIG_PERSONALIZADA,
        )
    chat_actual = sesiones_de_chat[id_usuario]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # send_message es síncrono: se ejecuta en un hilo para no bloquear el bot
        respuesta = await asyncio.to_thread(chat_actual.send_message, texto_recibido)
        await update.message.reply_text(respuesta.text or "🤔 No pude generar una respuesta, intenta de nuevo.")
    except Exception as e:
        error_str = str(e)
        logger.error("Fallo al consultar Gemini: %s", error_str)
        if "503" in error_str or "UNAVAILABLE" in error_str:
            await update.message.reply_text("⚠️ El servidor de Gemini está momentáneamente saturado. Reintenta en unos momentos.")
        else:
            await update.message.reply_text("❌ Ocurrió un fallo en el procesamiento de la consulta.")


# ==============================================================================
# INICIALIZACIÓN DEL BOT
# ==============================================================================
def iniciar_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(CommandHandler("help", comando_help))
    app.add_handler(CommandHandler("reset", comando_reset))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), responder_mensaje))

    logger.info("✅ Bot ejecutándose. Escuchando peticiones...")
    app.run_polling()


if __name__ == "__main__":
    iniciar_bot()
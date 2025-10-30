# ===========================================================
# BOT DE TELEGRAM PARA EL SISTEMA SIAF - VERSIÓN PARA RENDER
# ===========================================================

import os
import json
import re
import logging
from collections import defaultdict
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import google.generativeai as genai

# ------------------------------------------------------------
# CONFIGURACIÓN (usando variables de entorno)
# ------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FAQ_ARCHIVO = os.getenv("FAQ_PATH", "faq.json")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Faltan variables de entorno: TELEGRAM_TOKEN o GEMINI_API_KEY.")

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Inicializar modelo de IA (global)
genai.configure(api_key=GEMINI_API_KEY)
modelo_ia = genai.GenerativeModel("gemini-2.5-flash-lite")

# Cargar FAQ
def cargar_faq():
    try:
        with open(FAQ_ARCHIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error al cargar FAQ: {e}")
        return {}

FAQ_GLOBAL = cargar_faq()

# ------------------------------------------------------------
# Estados de conversación
# ------------------------------------------------------------
ESTADO_INICIO = "inicio"
ESTADO_MENU = "menu"
ESTADO_CATEGORIA = "categoria"
ESTADO_DERIVACION_INICIAL = "derivacion_inicial"
ESTADO_DERIVACION_REESCRITURA = "derivacion_reescritura"
ESTADO_ESPERANDO_DETALLE = "esperando_detalle"

sesiones = defaultdict(dict)

# ------------------------------------------------------------
# FUNCIONES DE LÓGICA DEL BOT
# ------------------------------------------------------------

def encontrar_preguntas_similares(faq, consulta_usuario, umbral=1, max_sugerencias=10):
    palabras_usuario = set(re.findall(r"\w+", consulta_usuario.lower()))
    coincidencias = []
    for categoria, preguntas in faq.items():
        for pregunta in preguntas:
            palabras_pregunta = set(re.findall(r"\w+", pregunta.lower()))
            comunes = len(palabras_usuario & palabras_pregunta)
            if comunes >= umbral:
                coincidencias.append((comunes, categoria, pregunta))
    coincidencias.sort(key=lambda x: x[0], reverse=True)
    return coincidencias[:max_sugerencias]


def generar_respuesta_ia(pregunta_usuario, faq_dict):
    contexto_faq = ""
    for categoria, preguntas in faq_dict.items():
        contexto_faq += f"\n## {categoria}\n"
        for p, r in preguntas.items():
            contexto_faq += f"P: {p}\nR: {r}\n"

    prompt = (
        "Eres un asistente oficial del Sistema Integrado de Administración Financiera (SIAF) "
        "de la Provincia de Entre Ríos, gestionado por la Contaduría General. "
        "Responde la siguiente consulta utilizando **solo** la información del contexto proporcionado. "
        "Si el contexto no contiene la respuesta, indícalo claramente y sugiere contacto telefónico. "
        "No inventes información ni cites fuentes externas.\n\n"
        "=== CONTEXTO DEL SISTEMA (FAQ OFICIAL) ===\n"
        f"{contexto_faq}\n"
        "=== FIN DEL CONTEXTO ===\n\n"
        f"Consulta del usuario:\n{pregunta_usuario}\n\n"
        "Respuesta:"
    )

    try:
        respuesta = modelo_ia.generate_content(prompt)
        return respuesta.text or "⚠️ No se obtuvo respuesta del modelo."
    except Exception as e:
        return f"⚠️ Error al consultar la IA: {str(e)}"


# ------------------------------------------------------------
# MANEJADORES DE MENSAJES
# ------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        "🤖 Bienvenido al Asistente del SIAF\n"
        "=================================\n\n"
        "Por favor, indicá tu nombre:",
        reply_markup=ReplyKeyboardRemove(),
    )
    sesiones[user.id]["estado"] = ESTADO_INICIO


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    texto = update.message.text.strip()
    user_id = user.id

    if "estado" not in sesiones[user_id]:
        sesiones[user_id]["estado"] = ESTADO_INICIO
        await update.message.reply_text("Por favor, indicá tu nombre:")
        return

    estado = sesiones[user_id]["estado"]

    # --- Inicio ---
    if estado == ESTADO_INICIO:
        sesiones[user_id]["nombre"] = texto or "Usuario"
        sesiones[user_id]["estado"] = ESTADO_MENU
        await mostrar_menu(update, user_id)
        return

    # --- Menú principal ---
    if estado == ESTADO_MENU:
        if texto == "0":
            sesiones[user_id]["estado"] = ESTADO_DERIVACION_INICIAL
            await update.message.reply_text(
                f"{sesiones[user_id]['nombre']}, describí brevemente tu consulta:"
            )
            return
        try:
            idx = int(texto) - 1
            categorias = list(FAQ_GLOBAL.keys())
            if 0 <= idx < len(categorias):
                sesiones[user_id]["categoria_actual"] = categorias[idx]
                sesiones[user_id]["estado"] = ESTADO_CATEGORIA
                await mostrar_preguntas_categoria(update, user_id, categorias[idx])
                return
        except (ValueError, IndexError):
            pass
        await update.message.reply_text("❌ Opción inválida.")
        await mostrar_menu(update, user_id)
        return

    # --- Categoría seleccionada ---
    if estado == ESTADO_CATEGORIA:
        if texto == "0":
            sesiones[user_id]["estado"] = ESTADO_MENU
            await mostrar_menu(update, user_id)
            return
        try:
            idx = int(texto) - 1
            cat = sesiones[user_id]["categoria_actual"]
            preguntas = list(FAQ_GLOBAL[cat].keys())
            if 0 <= idx < len(preguntas):
                respuesta = FAQ_GLOBAL[cat][preguntas[idx]]
                await update.message.reply_text(f"✅ {respuesta}")
                await update.message.reply_text("¿Te sirvió esta respuesta? (Sí/No)")
                sesiones[user_id]["estado"] = "esperando_feedback"
                return
        except Exception:
            pass
        await update.message.reply_text("❌ Opción inválida.")
        await mostrar_preguntas_categoria(update, user_id, cat)
        return

    # --- Feedback ---
    if estado == "esperando_feedback":
        if texto.lower() in ["sí", "si", "s", "yes", "y"]:
            await update.message.reply_text(
                f"¡Genial, {sesiones[user_id]['nombre']}! 😊",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await update.message.reply_text("Lo lamento, veamos otras opciones.")
        sesiones[user_id]["estado"] = ESTADO_MENU
        await mostrar_menu(update, user_id)
        return

    # --- Derivaciones e IA ---
    if estado == ESTADO_DERIVACION_INICIAL:
        sesiones[user_id]["consulta_original"] = texto
        sugerencias = encontrar_preguntas_similares(FAQ_GLOBAL, texto)
        sesiones[user_id]["sugerencias_derivacion"] = sugerencias

        msg = "🔍 Posibles coincidencias:\n"
        for i, (_, _, p) in enumerate(sugerencias, 1):
            msg += f"{i}) {p}\n"
        msg += "\n0) Volver al menú principal\nA) Reformular mi consulta"
        await update.message.reply_text(msg)
        sesiones[user_id]["estado"] = "derivacion_opciones_inicial"
        return

    if estado == "derivacion_opciones_inicial":
        if texto == "0":
            sesiones[user_id]["estado"] = ESTADO_MENU
            await mostrar_menu(update, user_id)
            return
        elif texto.upper() == "A":
            sesiones[user_id]["estado"] = ESTADO_DERIVACION_REESCRITURA
            await update.message.reply_text("Por favor, reformulá tu consulta:")
            return
        elif texto.isdigit():
            idx = int(texto) - 1
            sugerencias = sesiones[user_id].get("sugerencias_derivacion", [])
            if 0 <= idx < len(sugerencias):
                _, cat, p = sugerencias[idx]
                respuesta = FAQ_GLOBAL[cat][p]
                await update.message.reply_text(f"✅ {respuesta}")
                await update.message.reply_text("¿Te sirvió esta respuesta? (Sí/No)")
                sesiones[user_id]["estado"] = "esperando_feedback"
                return

    if estado == ESTADO_DERIVACION_REESCRITURA:
        sesiones[user_id]["consulta_reescrita"] = texto
        await update.message.reply_text("⏳ Procesando tu consulta con IA...")
        respuesta = generar_respuesta_ia(texto, FAQ_GLOBAL)
        await update.message.reply_text(f"🤖 {respuesta}")
        sesiones[user_id]["estado"] = ESTADO_MENU
        await mostrar_menu(update, user_id)
        return


# ------------------------------------------------------------
# FUNCIONES DE APOYO
# ------------------------------------------------------------

async def mostrar_menu(update: Update, user_id: int):
    nombre = sesiones[user_id]["nombre"]
    msg = f"¡Hola, {nombre}! 👋\n\n📚 Categorías disponibles:\n"
    for i, cat in enumerate(FAQ_GLOBAL.keys(), 1):
        msg += f"{i}) {cat}\n"
    msg += "0) No encontré mi respuesta – describir consulta"
    await update.message.reply_text(msg)


async def mostrar_preguntas_categoria(update: Update, user_id: int, categoria: str):
    msg = f"❓ Preguntas en '{categoria}':\n"
    for i, preg in enumerate(FAQ_GLOBAL[categoria].keys(), 1):
        msg += f"{i}) {preg}\n"
    msg += "0) Volver al menú principal"
    await update.message.reply_text(msg)


# ------------------------------------------------------------
# EJECUCIÓN PRINCIPAL
# ------------------------------------------------------------

if __name__ == "__main__":
    if not FAQ_GLOBAL:
        print("❌ No se pudo cargar el FAQ. Verifica el archivo 'faq.json'.")
        exit(1)
    else:
        print("✅ FAQ cargado correctamente.")
        print("🚀 Iniciando bot en Render...")

    from telegram.ext import ApplicationBuilder  # aseguramos import correcto

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.run_polling()
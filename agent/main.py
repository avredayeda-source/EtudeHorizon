# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Meta, Twilio) gracias a la capa de providers.
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial
from agent.seguimiento import actualizar_seguimiento, relanzar_conversaciones_inactivas
from agent.providers import obtener_proveedor

load_dotenv()

# Configuración de logging según entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp (se configura en .env con WHATSAPP_PROVIDER)
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))


async def _bucle_relance():
    """Tâche de fond : relance périodique des conversations inachevées.
    Ne fait rien si RELANCE_ACTIVA != true (voir seguimiento.py)."""
    intervalo = int(os.getenv("RELANCE_INTERVALO_MIN", "30")) * 60
    while True:
        try:
            await relanzar_conversaciones_inactivas(proveedor)
        except Exception as e:
            logger.error(f"Error en bucle de relance: {e}")
        await asyncio.sleep(intervalo)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")

    # Tâche de fond de relance (activée seulement si RELANCE_ACTIVA=true)
    tarea_relance = asyncio.create_task(_bucle_relance())
    if os.getenv("RELANCE_ACTIVA", "false").lower() == "true":
        logger.info("Relance automatique ACTIVÉE")

    yield

    tarea_relance.cancel()


app = FastAPI(
    title="AgentKit — WhatsApp AI Agent",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {"status": "ok", "service": "agentkit"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (requerido por Meta Cloud API, no-op para otros)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Procesa el mensaje, genera respuesta con Claude y la envía de vuelta.
    """
    try:
        # Parsear webhook — el proveedor normaliza el formato
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            # Ignorar mensajes propios o totalmente vacíos (sin texto ni adjuntos)
            if msg.es_propio or (not msg.texto and not msg.media):
                continue

            # Si el cliente envió documentos (PDF/imágenes), guardarlos para el
            # conseiller y construir una nota para que Rosemonde acuse recibo.
            texto_para_brain = msg.texto
            if msg.media:
                from agent.tools import registrar_documentos_recibidos
                tipos = await registrar_documentos_recibidos(msg.telefono, msg.media)
                nota_doc = f"[Document reçu: {', '.join(tipos)}]"
                texto_para_brain = f"{msg.texto} {nota_doc}".strip() if msg.texto else nota_doc
                logger.info(f"Documento(s) de {msg.telefono}: {tipos}")

            logger.info(f"Mensaje de {msg.telefono}: {texto_para_brain}")

            # Obtener historial ANTES de guardar el mensaje actual
            # (brain.py agrega el mensaje actual, evitando duplicados)
            historial = await obtener_historial(msg.telefono)

            # Generar respuesta con Claude (con memoria del cliente para continuidad)
            respuesta = await generar_respuesta(texto_para_brain, historial, telefono=msg.telefono)

            # Guardar mensaje del usuario Y respuesta del agente en memoria
            await guardar_mensaje(msg.telefono, "user", texto_para_brain)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            # Suivi proactif : intención, hesitación, estado, resumen, actividad
            await actualizar_seguimiento(msg.telefono, texto_para_brain, respuesta)

            # Enviar respuesta por el buen canal (WhatsApp o Messenger)
            await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=getattr(msg, "canal", "whatsapp"))

            logger.info(f"Respuesta a {msg.telefono} ({getattr(msg, 'canal', 'whatsapp')}): {respuesta}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# agent/providers/messenger.py — Adaptador para Facebook Messenger
# Generado por AgentKit

"""
Conecta Rosemonde a Facebook Messenger (mensajes de una Página de Facebook).
No requiere número de teléfono ni verificación de empresa para probar.

Usa la Messenger Platform de Meta:
  - GET  /webhook  → verificación con hub.verify_token / hub.challenge
  - POST /webhook  → eventos de mensajes (object == "page")
  - envío vía Graph API: POST /me/messages con el Page Access Token
"""

import os
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorMessenger(ProveedorWhatsApp):
    """Proveedor para Facebook Messenger (Página de Facebook)."""

    def __init__(self):
        # Token de acceso de la Página (lo generas en la app de Meta → Messenger)
        self.page_access_token = os.getenv("MESSENGER_PAGE_ACCESS_TOKEN")
        # Verify token: reutiliza META_VERIFY_TOKEN si no hay uno específico
        self.verify_token = os.getenv("MESSENGER_VERIFY_TOKEN") or os.getenv(
            "META_VERIFY_TOKEN", "etudehorizon-verify"
        )
        self.api_version = "v21.0"

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (igual que WhatsApp Cloud API)."""
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token == self.verify_token:
            # Messenger espera el challenge como texto plano
            try:
                return int(challenge)
            except (TypeError, ValueError):
                return challenge
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload de Messenger (object == 'page')."""
        body = await request.json()
        mensajes = []

        if body.get("object") != "page":
            return []

        for entry in body.get("entry", []):
            for evento in entry.get("messaging", []):
                remitente = evento.get("sender", {}).get("id", "")
                mensaje = evento.get("message", {})

                # Ignorar echos (mensajes enviados por la propia página)
                if mensaje.get("is_echo"):
                    continue

                texto = mensaje.get("text", "")
                mensaje_id = mensaje.get("mid", "")

                # Adjuntos (imágenes, archivos)
                media = []
                for adj in mensaje.get("attachments", []) or []:
                    url = adj.get("payload", {}).get("url", "")
                    tipo = adj.get("type", "file")
                    if url:
                        media.append({"url": url, "tipo": tipo})

                if not texto and not media:
                    continue

                mensajes.append(MensajeEntrante(
                    telefono=remitente,   # PSID (id del usuario en Messenger)
                    texto=texto,
                    mensaje_id=mensaje_id,
                    es_propio=False,
                    media=media,
                ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje via Messenger Send API (telefono = PSID)."""
        if not self.page_access_token:
            logger.warning("MESSENGER_PAGE_ACCESS_TOKEN no configurado")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/me/messages"
        params = {"access_token": self.page_access_token}
        payload = {
            "recipient": {"id": telefono},
            "messaging_type": "RESPONSE",
            "message": {"text": mensaje},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, params=params, json=payload)
            if r.status_code != 200:
                logger.error(f"Error Messenger API: {r.status_code} — {r.text}")
            return r.status_code == 200

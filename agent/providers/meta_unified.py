# agent/providers/meta_unified.py — Adaptador unificado Meta (WhatsApp + Messenger)
# Generado por AgentKit

"""
UN SEUL webhook pour les DEUX canaux Meta :
  - WhatsApp Cloud API   (object == "whatsapp_business_account")
  - Facebook Messenger   (object == "page")

Rosemonde répond sur le bon canal automatiquement. Un seul déploiement Render,
une seule app Meta, un seul verify token.
"""

import os
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorMetaUnificado(ProveedorWhatsApp):
    """Gère WhatsApp Cloud API et Messenger dans le même webhook."""

    def __init__(self):
        # WhatsApp Cloud API
        self.wa_access_token = os.getenv("META_ACCESS_TOKEN")
        self.wa_phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        # Messenger (Page)
        self.page_access_token = os.getenv("MESSENGER_PAGE_ACCESS_TOKEN")
        # Verify token commun
        self.verify_token = os.getenv("META_VERIFY_TOKEN") or os.getenv(
            "MESSENGER_VERIFY_TOKEN", "etudehorizon-verify"
        )
        self.api_version = "v21.0"

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Vérification GET commune (WhatsApp + Messenger utilisent le même mécanisme)."""
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token == self.verify_token:
            try:
                return int(challenge)
            except (TypeError, ValueError):
                return challenge
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Détecte le canal via 'object' et parse en conséquence."""
        body = await request.json()
        obj = body.get("object")

        if obj == "whatsapp_business_account":
            return self._parsear_whatsapp(body)
        if obj == "page":
            return self._parsear_messenger(body)
        return []

    def _parsear_whatsapp(self, body: dict) -> list[MensajeEntrante]:
        mensajes = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    tipo = msg.get("type")
                    telefono = msg.get("from", "")
                    mid = msg.get("id", "")
                    if tipo == "text":
                        mensajes.append(MensajeEntrante(
                            telefono=telefono,
                            texto=msg.get("text", {}).get("body", ""),
                            mensaje_id=mid, es_propio=False, canal="whatsapp",
                        ))
                    elif tipo in ("document", "image", "audio", "video"):
                        media = msg.get(tipo, {})
                        mensajes.append(MensajeEntrante(
                            telefono=telefono, texto=media.get("caption", ""),
                            mensaje_id=mid, es_propio=False, canal="whatsapp",
                            media=[{"url": media.get("id", ""), "tipo": media.get("mime_type", tipo)}],
                        ))
        return mensajes

    def _parsear_messenger(self, body: dict) -> list[MensajeEntrante]:
        mensajes = []
        for entry in body.get("entry", []):
            for evento in entry.get("messaging", []):
                mensaje = evento.get("message", {})
                if mensaje.get("is_echo"):
                    continue
                remitente = evento.get("sender", {}).get("id", "")
                texto = mensaje.get("text", "")
                media = []
                for adj in mensaje.get("attachments", []) or []:
                    url = adj.get("payload", {}).get("url", "")
                    if url:
                        media.append({"url": url, "tipo": adj.get("type", "file")})
                if not texto and not media:
                    continue
                mensajes.append(MensajeEntrante(
                    telefono=remitente, texto=texto, mensaje_id=mensaje.get("mid", ""),
                    es_propio=False, canal="messenger", media=media,
                ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str, canal: str = "whatsapp") -> bool:
        """Envoie sur le bon canal selon 'canal'."""
        if canal == "messenger":
            return await self._enviar_messenger(telefono, mensaje)
        return await self._enviar_whatsapp(telefono, mensaje)

    async def _enviar_whatsapp(self, telefono: str, mensaje: str) -> bool:
        if not self.wa_access_token or not self.wa_phone_number_id:
            logger.warning("META_ACCESS_TOKEN/PHONE_NUMBER_ID manquants (WhatsApp)")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.wa_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.wa_access_token}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": telefono, "type": "text", "text": {"body": mensaje}}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error WhatsApp: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def _enviar_messenger(self, telefono: str, mensaje: str) -> bool:
        if not self.page_access_token:
            logger.warning("MESSENGER_PAGE_ACCESS_TOKEN manquant (Messenger)")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/me/messages"
        params = {"access_token": self.page_access_token}
        payload = {"recipient": {"id": telefono}, "messaging_type": "RESPONSE", "message": {"text": mensaje}}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, params=params, json=payload)
            if r.status_code != 200:
                logger.error(f"Error Messenger: {r.status_code} — {r.text}")
            return r.status_code == 200

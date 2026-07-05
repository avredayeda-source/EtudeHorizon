# agent/providers/multi.py — Proveedor MULTI-canal (Twilio + Meta)
# Generado por AgentKit

"""
UN SEUL webhook pour TOUS les canaux, sans entreprise officielle :
  - Twilio WhatsApp Sandbox  (form-encoded)  → WhatsApp SANS vérification Meta
  - Facebook Messenger        (JSON object=page)
  - WhatsApp Cloud API        (JSON object=whatsapp_business_account)

Détecte le canal via le Content-Type / le corps, et répond par le bon canal.
Idéal pour démarrer gratuitement : le Sandbox Twilio marche tout de suite.
"""

import logging
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorMulti(ProveedorWhatsApp):
    """Route les webhooks Twilio et Meta vers les bons adaptateurs."""

    def __init__(self):
        from agent.providers.twilio import ProveedorTwilio
        from agent.providers.meta_unified import ProveedorMetaUnificado
        self.twilio = ProveedorTwilio()
        self.meta = ProveedorMetaUnificado()

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Seul Meta fait une vérification GET (hub.challenge)."""
        return await self.meta.validar_webhook(request)

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Détecte Twilio (form) vs Meta (JSON) via le Content-Type."""
        ctype = request.headers.get("content-type", "").lower()

        if "application/json" in ctype:
            # Meta (Messenger ou WhatsApp Cloud) — le provider fixe canal lui-même
            return await self.meta.parsear_webhook(request)

        # Twilio Sandbox / WhatsApp (form-urlencoded)
        mensajes = await self.twilio.parsear_webhook(request)
        for m in mensajes:
            m.canal = "twilio"
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str, canal: str = "twilio") -> bool:
        """Répond par le canal d'origine."""
        if canal == "twilio":
            return await self.twilio.enviar_mensaje(telefono, mensaje)
        # canal "messenger" ou "whatsapp" → Meta
        return await self.meta.enviar_mensaje(telefono, mensaje, canal=canal)

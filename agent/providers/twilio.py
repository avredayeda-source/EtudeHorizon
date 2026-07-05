# agent/providers/twilio.py — Adaptador para Twilio WhatsApp
# Generado por AgentKit

import os
import logging
import base64
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorTwilio(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando Twilio."""

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.phone_number = os.getenv("TWILIO_PHONE_NUMBER")

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload form-encoded de Twilio (texto + documentos/imágenes)."""
        form = await request.form()
        texto = form.get("Body", "")
        telefono = form.get("From", "").replace("whatsapp:", "")
        mensaje_id = form.get("MessageSid", "")

        # Documentos/adjuntos: WhatsApp envía PDF, imágenes, etc. via Twilio.
        media = []
        try:
            num_media = int(form.get("NumMedia", "0"))
        except (TypeError, ValueError):
            num_media = 0
        for i in range(num_media):
            url = form.get(f"MediaUrl{i}", "")
            tipo = form.get(f"MediaContentType{i}", "")
            if url:
                media.append({"url": url, "tipo": tipo})

        # Ignorar mensajes totalmente vacíos (sin texto ni adjuntos)
        if not texto and not media:
            return []

        return [MensajeEntrante(
            telefono=telefono,
            texto=texto,
            mensaje_id=mensaje_id,
            es_propio=False,
            media=media,
        )]

    async def enviar_mensaje(self, telefono: str, mensaje: str, canal: str = "whatsapp") -> bool:
        """Envía mensaje via Twilio API."""
        if not all([self.account_sid, self.auth_token, self.phone_number]):
            logger.warning("Variables de Twilio no configuradas")
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}"}
        data = {
            "From": f"whatsapp:{self.phone_number}",
            "To": f"whatsapp:{telefono}",
            "Body": mensaje,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, data=data, headers=headers)
            if r.status_code != 201:
                logger.error(f"Error Twilio: {r.status_code} — {r.text}")
            return r.status_code == 201

    async def enviar_botones(self, telefono: str, texto: str, opciones: list[str],
                             content_sid: str | None = None) -> bool:
        """
        Envía "botones de acción".

        - Si TWILIO_CONTENT_SID (o content_sid) está configurado → envía botones
          interactivos reales de WhatsApp vía la Content API de Twilio.
        - Si no → fallback universal: mensaje de texto con opciones numeradas
          (funciona en el sandbox sin templates aprobados).

        NOTA producción: los botones tappables de WhatsApp requieren un Content
        template aprobado. Créalo en Twilio Console → Content Template Builder
        (tipo "Quick reply") y pon su SID en TWILIO_CONTENT_SID.
        """
        content_sid = content_sid or os.getenv("TWILIO_CONTENT_SID")

        # Camino con botones reales (Content API)
        if content_sid and all([self.account_sid, self.auth_token, self.phone_number]):
            import json
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
            auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
            headers = {"Authorization": f"Basic {auth}"}
            variables = {str(i + 1): op for i, op in enumerate(opciones)}
            data = {
                "From": f"whatsapp:{self.phone_number}",
                "To": f"whatsapp:{telefono}",
                "ContentSid": content_sid,
                "ContentVariables": json.dumps(variables),
            }
            async with httpx.AsyncClient() as client:
                r = await client.post(url, data=data, headers=headers)
                if r.status_code != 201:
                    logger.error(f"Error Twilio (botones): {r.status_code} — {r.text}")
                return r.status_code == 201

        # Fallback universal: opciones numeradas como texto
        from agent.tools import formatear_botones
        return await self.enviar_mensaje(telefono, formatear_botones(texto, opciones))

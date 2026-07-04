# agent/providers/base.py — Clase base para proveedores de WhatsApp
# Generado por AgentKit

"""
Define la interfaz común que todos los proveedores de WhatsApp deben implementar.
Esto permite cambiar de proveedor sin modificar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fastapi import Request


@dataclass
class MensajeEntrante:
    """Mensaje normalizado — mismo formato sin importar el proveedor."""
    telefono: str       # Número del remitente
    texto: str          # Contenido del mensaje
    mensaje_id: str     # ID único del mensaje
    es_propio: bool     # True si lo envió el agente (se ignora)
    # Documentos/adjuntos enviados por el cliente (PDF, imágenes...).
    # Cada item: {"url": "...", "tipo": "image/jpeg"}
    media: list[dict] = field(default_factory=list)


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje de texto. Retorna True si fue exitoso."""
        ...

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (solo Meta la requiere). Retorna respuesta o None."""
        return None

    async def enviar_botones(self, telefono: str, texto: str, opciones: list[str]) -> bool:
        """
        Envía botones de acción. Implementación por defecto: opciones numeradas
        como texto (fallback universal). Los proveedores pueden sobreescribir
        para usar botones interactivos nativos.
        """
        from agent.tools import formatear_botones
        return await self.enviar_mensaje(telefono, formatear_botones(texto, opciones))

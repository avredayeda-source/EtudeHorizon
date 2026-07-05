# agent/providers/__init__.py — Factory de proveedores
# Generado por AgentKit

"""
Selecciona el proveedor de WhatsApp según la variable WHATSAPP_PROVIDER en .env.
"""

import os
from agent.providers.base import ProveedorWhatsApp


def obtener_proveedor() -> ProveedorWhatsApp:
    """Retorna el proveedor de WhatsApp configurado en .env."""
    proveedor = os.getenv("WHATSAPP_PROVIDER", "").lower()

    if not proveedor:
        raise ValueError("WHATSAPP_PROVIDER no configurado en .env. Usa: meta o twilio")

    if proveedor == "meta":
        from agent.providers.meta import ProveedorMeta
        return ProveedorMeta()
    elif proveedor == "twilio":
        from agent.providers.twilio import ProveedorTwilio
        return ProveedorTwilio()
    elif proveedor == "messenger":
        from agent.providers.messenger import ProveedorMessenger
        return ProveedorMessenger()
    elif proveedor in ("meta_unified", "meta_unificado"):
        from agent.providers.meta_unified import ProveedorMetaUnificado
        return ProveedorMetaUnificado()
    elif proveedor in ("multi", "both", "todo"):
        from agent.providers.multi import ProveedorMulti
        return ProveedorMulti()
    else:
        raise ValueError(f"Proveedor no soportado: {proveedor}. Usa: meta, twilio, messenger, meta_unified o multi")

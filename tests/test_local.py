# tests/test_local.py — Simulador de chat en terminal
# Generado por AgentKit

"""
Prueba tu agente sin necesitar WhatsApp.
Simula una conversación en la terminal.
"""

import asyncio
import sys
import os

# Forzar UTF-8 en la consola (Windows usa cp1252 por defecto y falla con
# los acentos y emojis de Rosemonde). Evita el UnicodeEncodeError al arrancar.
for _stream in (sys.stdout, sys.stdin, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, limpiar_historial

TELEFONO_TEST = "test-local-001"


async def main():
    """Loop principal del chat de prueba."""
    await inicializar_db()

    print()
    print("=" * 55)
    print("   AgentKit — Test Local (Rosemonde / ÉtudeHorizon)")
    print("=" * 55)
    print()
    print("  Escribe mensajes como si fueras un cliente.")
    print("  Comandos especiales:")
    print("    'limpiar'  — borra el historial")
    print("    'doc'      — simula el envío de un documento (PDF)")
    print("    'salir'    — termina el test")
    print()
    print("-" * 55)
    print()

    while True:
        try:
            mensaje = input("Tu: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nTest finalizado.")
            break

        if not mensaje:
            continue

        if mensaje.lower() == "salir":
            print("\nTest finalizado.")
            break

        if mensaje.lower() == "limpiar":
            await limpiar_historial(TELEFONO_TEST)
            print("[Historial borrado]\n")
            continue

        # Simular el envío de un documento (como en WhatsApp real)
        if mensaje.lower().startswith("doc"):
            from agent.tools import registrar_documentos_recibidos
            media = [{"url": "https://example.com/diplome.pdf", "tipo": "application/pdf"}]
            tipos = await registrar_documentos_recibidos(TELEFONO_TEST, media)
            mensaje = f"[Document reçu: {', '.join(tipos)}]"
            print(f"[Tu as envoyé un document: {tipos}]")

        # Obtener historial ANTES de guardar (brain.py agrega el mensaje actual)
        historial = await obtener_historial(TELEFONO_TEST)

        # Generar respuesta (con memoria del cliente para continuidad)
        print("\nRosemonde: ", end="", flush=True)
        respuesta = await generar_respuesta(mensaje, historial, telefono=TELEFONO_TEST)
        print(respuesta)
        print()

        # Guardar mensaje del usuario y respuesta del agente
        await guardar_mensaje(TELEFONO_TEST, "user", mensaje)
        await guardar_mensaje(TELEFONO_TEST, "assistant", respuesta)

        # Suivi proactif (intención, hesitación, estado, resumen, actividad)
        from agent.seguimiento import actualizar_seguimiento
        await actualizar_seguimiento(TELEFONO_TEST, mensaje, respuesta)


if __name__ == "__main__":
    asyncio.run(main())

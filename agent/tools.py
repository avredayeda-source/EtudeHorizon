# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas del negocio ÉtudeHorizon.

Caso de uso principal: capturar y calificar leads + responder FAQ.
Funciones proactivas:
  - formatear_botones()          → propone opciones d'action (fallback universel)
  - agendar_cita()               → prise de rendez-vous / formulaire
  - buscar_en_knowledge()        → responde con la base de conocimiento
  - registrar_pregunta_sin_respuesta() → auto-apprentissage
  - guardar_perfil_lead() / obtener_perfil_lead() → mémoire du lead
"""

import os
import yaml
import logging
from datetime import datetime

logger = logging.getLogger("agentkit")

# Archivo donde se acumulan las preguntas sin respuesta (auto-apprentissage)
ARCHIVO_APRENDIZAJE = os.path.join("knowledge", "aprendizaje.md")


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio (Rosemonde: 24/7)."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "24h/24, 7j/7"),
        "esta_abierto": True,
    }


# ════════════════════════════════════════════════════════════
# BOUTONS / OPTIONS D'ACTION
# ════════════════════════════════════════════════════════════

def formatear_botones(texto: str, opciones: list[str]) -> str:
    """
    Formatea un mensaje con "botones de acción" como opciones numeradas.

    Es el fallback universal que funciona en el sandbox de Twilio sin templates.
    El proveedor (twilio.py) puede transformar esto en botones reales si hay
    Content templates configurados.

    Ejemplo:
        formatear_botones("Que veux-tu faire ?", ["Prendre RDV", "Voir les bourses"])
        →  "Que veux-tu faire ?\n\n1️⃣ Prendre RDV\n2️⃣ Voir les bourses\n\n
            (Réponds avec le numéro 😊)"
    """
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    lineas = [texto, ""]
    for i, opcion in enumerate(opciones[:9]):
        lineas.append(f"{emojis[i]} {opcion}")
    lineas.append("")
    lineas.append("(Réponds simplement avec le numéro 😊)")
    return "\n".join(lineas)


# ════════════════════════════════════════════════════════════
# PRISE DE RENDEZ-VOUS / FORMULAIRE
# ════════════════════════════════════════════════════════════

async def agendar_cita(telefono: str, nombre: str = "", fecha: str = "",
                       hora: str = "", motivo: str = "") -> dict:
    """
    Enregistre un rendez-vous / une demande de rappel dans la base.
    Marque le lead comme 'agendado'. Retourne un récap de la cita.
    """
    from agent.memory import async_session, Cita, PerfilLead
    from sqlalchemy import select
    from datetime import datetime as _dt

    async with async_session() as session:
        cita = Cita(
            telefono=telefono, nombre=nombre, fecha=fecha, hora=hora, motivo=motivo
        )
        session.add(cita)

        # Actualizar estado del lead
        result = await session.execute(
            select(PerfilLead).where(PerfilLead.telefono == telefono)
        )
        perfil = result.scalar_one_or_none()
        if perfil is None:
            perfil = PerfilLead(telefono=telefono, nombre=nombre)
            session.add(perfil)
        perfil.estado = "agendado"
        if nombre:
            perfil.nombre = nombre
        perfil.actualizado = _dt.utcnow()

        await session.commit()
        logger.info(f"[cita] RDV enregistré pour {telefono}: {fecha} {hora} — {motivo}")

    return {"ok": True, "telefono": telefono, "nombre": nombre,
            "fecha": fecha, "hora": hora, "motivo": motivo}


# ════════════════════════════════════════════════════════════
# BASE DE CONNAISSANCE
# ════════════════════════════════════════════════════════════

def buscar_en_knowledge(consulta: str) -> str:
    """Busca información relevante en los archivos de /knowledge."""
    resultados = []
    knowledge_dir = "knowledge"

    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."

    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or archivo == "aprendizaje.md" or not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información específica sobre eso en mis archivos."


# ════════════════════════════════════════════════════════════
# AUTO-APPRENTISSAGE
# ════════════════════════════════════════════════════════════

def registrar_pregunta_sin_respuesta(pregunta: str) -> None:
    """Guarda una pregunta que Rosemonde no supo responder en knowledge/aprendizaje.md."""
    try:
        os.makedirs("knowledge", exist_ok=True)
        existe = os.path.exists(ARCHIVO_APRENDIZAJE)
        with open(ARCHIVO_APRENDIZAJE, "a", encoding="utf-8") as f:
            if not existe:
                f.write("# Auto-apprentissage — Questions sans réponse\n\n")
                f.write("Rosemonde enregistre ici les questions qu'elle n'a pas su répondre.\n")
                f.write("Revois-les et enrichis /knowledge pour qu'elle s'améliore.\n\n")
                f.write("| Date | Question |\n| --- | --- |\n")
            fecha = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            pregunta_limpia = pregunta.replace("\n", " ").replace("|", "/")
            f.write(f"| {fecha} | {pregunta_limpia} |\n")
        logger.info(f"[auto-apprentissage] Pregunta registrada: {pregunta[:60]}")
    except IOError as e:
        logger.error(f"No se pudo registrar la pregunta sin respuesta: {e}")


# ════════════════════════════════════════════════════════════
# CAPTURA / CALIFICACIÓN DE LEADS
# ════════════════════════════════════════════════════════════

async def guardar_perfil_lead(telefono: str, **campos) -> None:
    """
    Guarda o actualiza el perfil de un lead.
    Campos: nombre, pais_visado, filiere, budget, documentos, intencion,
            estado, hesitacion, resumen, notas.
    """
    from sqlalchemy import select
    from agent.memory import async_session, PerfilLead
    from datetime import datetime as _dt

    campos_validos = {"nombre", "pais_visado", "filiere", "budget", "documentos",
                      "intencion", "estado", "hesitacion", "resumen", "notas"}
    campos = {k: v for k, v in campos.items() if k in campos_validos and v}

    async with async_session() as session:
        result = await session.execute(
            select(PerfilLead).where(PerfilLead.telefono == telefono)
        )
        perfil = result.scalar_one_or_none()

        if perfil is None:
            perfil = PerfilLead(telefono=telefono, **campos)
            session.add(perfil)
        else:
            for clave, valor in campos.items():
                setattr(perfil, clave, valor)
            perfil.actualizado = _dt.utcnow()

        await session.commit()
        logger.info(f"[lead] Perfil actualizado para {telefono}: {list(campos.keys())}")


async def registrar_documentos_recibidos(telefono: str, media: list[dict]) -> list[str]:
    """
    Guarda los documentos (PDF/imágenes) que el cliente envió por WhatsApp en el
    perfil del lead, para que el conseiller humano los revise. Retorna la lista
    de tipos recibidos (ej: ["application/pdf"]) para acusar recibo.
    """
    from sqlalchemy import select
    from agent.memory import async_session, PerfilLead
    from datetime import datetime as _dt

    if not media:
        return []

    tipos = [m.get("tipo", "fichier") for m in media]
    fecha = _dt.utcnow().strftime("%Y-%m-%d %H:%M")
    nuevas_entradas = [f"{fecha} | {m.get('tipo', '')} | {m.get('url', '')}" for m in media]

    async with async_session() as session:
        result = await session.execute(
            select(PerfilLead).where(PerfilLead.telefono == telefono)
        )
        perfil = result.scalar_one_or_none()
        if perfil is None:
            perfil = PerfilLead(telefono=telefono)
            session.add(perfil)

        existentes = perfil.documentos or ""
        perfil.documentos = (existentes + "\n" + "\n".join(nuevas_entradas)).strip()
        perfil.actualizado = _dt.utcnow()
        await session.commit()
        logger.info(f"[documentos] {len(media)} documento(s) guardado(s) para {telefono}")

    return tipos


async def obtener_perfil_lead(telefono: str) -> dict:
    """Recupera el perfil acumulado de un lead. Retorna {} si no existe."""
    from sqlalchemy import select
    from agent.memory import async_session, PerfilLead

    async with async_session() as session:
        result = await session.execute(
            select(PerfilLead).where(PerfilLead.telefono == telefono)
        )
        perfil = result.scalar_one_or_none()
        if perfil is None:
            return {}
        return {
            "nombre": perfil.nombre,
            "pais_visado": perfil.pais_visado,
            "filiere": perfil.filiere,
            "budget": perfil.budget,
            "documentos": perfil.documentos,
            "intencion": perfil.intencion,
            "estado": perfil.estado,
            "hesitacion": perfil.hesitacion,
            "resumen": perfil.resumen,
            "notas": perfil.notas,
        }

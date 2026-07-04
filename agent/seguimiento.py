# agent/seguimiento.py — Suivi proactif du lead
# Generado por AgentKit

"""
Fonctions proactives de Rosemonde :
  - detectar_hesitacion()        : détecte les signaux d'hésitation dans un message.
  - actualizar_seguimiento()     : après chaque échange, met à jour intention,
                                    hésitation, estado, activité, et résume au besoin.
  - resumir_conversacion()       : génère un résumé de la conversation (continuité).
  - contexto_para_prompt()       : bloc "mémoire du client" injecté dans le system prompt.
  - relanzar_conversaciones_inactivas() : relance les conversations inachevées.
"""

import os
import logging

logger = logging.getLogger("agentkit")

# Signaux d'hésitation (heuristique simple, en FR et EN)
SENALES_HESITACION = [
    "cher", "trop cher", "coûte", "budget", "je ne sais pas", "j'hésite", "hésite",
    "peur", "pas sûr", "pas sur", "compliqué", "difficile", "arnaque", "confiance",
    "réfléchir", "plus tard", "attendre", "risqué", "risque", "doute",
    "expensive", "too expensive", "not sure", "scam", "trust", "think about",
    "maybe later", "afraid", "worried",
]


def detectar_hesitacion(mensaje: str) -> str:
    """
    Détecte une hésitation dans le message du client.
    Retourne une courte étiquette (ex: "budget/coût") ou "" si rien détecté.
    """
    m = mensaje.lower()
    if any(s in m for s in ["cher", "coûte", "coute", "budget", "expensive", "prix", "argent", "money"]):
        return "budget / coût"
    if any(s in m for s in ["arnaque", "confiance", "scam", "trust", "sérieux", "serieux", "vrai", "réel", "reel"]):
        return "confiance / crédibilité"
    if any(s in m for s in ["peur", "afraid", "worried", "risque", "risqué", "risky", "seul", "loin"]):
        return "peur / risque"
    if any(s in m for s in ["plus tard", "attendre", "réfléchir", "reflechir", "maybe later", "think about", "pas maintenant"]):
        return "reporte / procrastination"
    if any(s in m for s in ["je ne sais pas", "pas sûr", "pas sur", "hésite", "not sure", "doute", "confus"]):
        return "indécision"
    return ""


def _clasificar_estado(perfil: dict, historial: list[dict]) -> str:
    """Determine el estado del lead a partir de sus datos y del historial."""
    if perfil.get("estado") in ("agendado", "capturado"):
        return perfil["estado"]
    # Si ya tenemos nombre + país + algún indicio de contacto → calificando/capturado
    tiene_nombre = bool(perfil.get("nombre"))
    tiene_pais = bool(perfil.get("pais_visado")) or bool(perfil.get("intencion"))
    if tiene_nombre and tiene_pais:
        return "calificando"
    if len(historial) <= 2:
        return "nuevo"
    return "calificando"


async def actualizar_seguimiento(telefono: str, mensaje_usuario: str, respuesta: str) -> None:
    """
    Se llama después de cada intercambio. Actualiza:
      - última actividad
      - hesitación detectada
      - estado del lead
      - resumen (cada cierto número de mensajes)
    """
    from agent.memory import marcar_actividad, contar_mensajes, obtener_historial
    from agent.tools import guardar_perfil_lead, obtener_perfil_lead

    # 1) Marcar actividad (y resetear relance)
    await marcar_actividad(telefono)

    # 2) Detectar hesitación
    hesitacion = detectar_hesitacion(mensaje_usuario)

    # 3) Recalcular estado
    perfil = await obtener_perfil_lead(telefono)
    historial = await obtener_historial(telefono)
    nuevo_estado = _clasificar_estado(perfil, historial)

    campos = {"estado": nuevo_estado}
    if hesitacion:
        campos["hesitacion"] = hesitacion
    await guardar_perfil_lead(telefono, **campos)

    # 4) Resumir la conversación cada 6 mensajes (continuité)
    total = await contar_mensajes(telefono)
    if total > 0 and total % 6 == 0:
        await resumir_conversacion(telefono)


async def resumir_conversacion(telefono: str) -> str:
    """
    Genera un resumen breve de la conversación y lo guarda en el perfil.
    Sirve para la continuidad: cuando el cliente vuelve, Rosemonde recuerda.
    """
    from agent.memory import obtener_historial
    from agent.tools import guardar_perfil_lead
    from agent.brain import client, MODELO

    historial = await obtener_historial(telefono, limite=40)
    if not historial:
        return ""

    conversacion = "\n".join(f"{m['role']}: {m['content']}" for m in historial)
    prompt_resumen = (
        "Résume en 3 à 5 puces courtes ce que l'on sait de ce prospect "
        "(prénom, pays visé, niveau, filière, budget/hésitations, prochaine étape). "
        "Sois factuel, pas de blabla.\n\n" + conversacion
    )

    try:
        resp = await client.messages.create(
            model=MODELO,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt_resumen}],
        )
        resumen = resp.content[0].text.strip()
        await guardar_perfil_lead(telefono, resumen=resumen)
        logger.info(f"[résumé] Conversation résumée pour {telefono}")
        return resumen
    except Exception as e:
        logger.error(f"Error al resumir conversación: {e}")
        return ""


def contexto_para_prompt(perfil: dict) -> str:
    """
    Construit le bloc "mémoire du client" injecté dans le system prompt.
    Donne à Rosemonde la continuité + de quoi être proactive.
    """
    if not perfil:
        return ""

    lineas = []
    if perfil.get("nombre"):
        lineas.append(f"- Prénom : {perfil['nombre']}")
    if perfil.get("pais_visado"):
        lineas.append(f"- Pays visé : {perfil['pais_visado']}")
    if perfil.get("intencion"):
        lineas.append(f"- Intention : {perfil['intencion']}")
    if perfil.get("filiere"):
        lineas.append(f"- Filière : {perfil['filiere']}")
    if perfil.get("budget"):
        lineas.append(f"- Budget évoqué : {perfil['budget']}")
    if perfil.get("hesitacion"):
        lineas.append(f"- Hésitation détectée : {perfil['hesitacion']} "
                      f"(rassure-le proactivement là-dessus)")
    if perfil.get("estado"):
        lineas.append(f"- Étape du lead : {perfil['estado']}")
    if perfil.get("resumen"):
        lineas.append(f"- Résumé des échanges précédents :\n{perfil['resumen']}")

    if not lineas:
        return ""

    return (
        "\n\n═══════════════════════════════════════════════════════════════\n"
        "MÉMOIRE DE CE CLIENT (utilise-la pour la continuité et la proactivité,\n"
        "ne redemande jamais une info déjà connue) :\n"
        + "\n".join(lineas)
    )


async def relanzar_conversaciones_inactivas(proveedor) -> int:
    """
    Relance les conversations inachevées (dans la fenêtre WhatsApp de 24h).

    ⚠️ Sécurité : ne s'exécute que si RELANCE_ACTIVA=true dans .env, pour ne pas
    envoyer de messages sortants sans ton accord. Après 24h de silence, Meta
    exige un template approuvé (freeform interdit) : cette relance vise donc la
    fenêtre 6h–24h.

    Retourne le nombre de relances envoyées.
    """
    if os.getenv("RELANCE_ACTIVA", "false").lower() != "true":
        return 0

    from agent.memory import obtener_conversaciones_inactivas, guardar_mensaje
    from agent.tools import guardar_perfil_lead

    horas_min = float(os.getenv("RELANCE_HORAS_MIN", "6"))
    horas_max = float(os.getenv("RELANCE_HORAS_MAX", "24"))

    candidatos = await obtener_conversaciones_inactivas(horas_min, horas_max, max_relances=1)
    enviados = 0

    for c in candidatos:
        nombre = c.get("nombre") or ""
        pais = c.get("pais_visado") or c.get("intencion") or "ton projet d'études"
        saludo = f"Coucou {nombre} 😊" if nombre else "Coucou 😊"
        mensaje = (
            f"{saludo} C'est Rosemonde d'ÉtudeHorizon. Je repensais à {pais} — "
            f"la promo *zéro frais d'agence* pour l'Inde court jusqu'au 31 juillet 2026. "
            f"Tu veux qu'on avance ensemble ? Dis-moi juste ton pays et je m'occupe du reste 🌍"
        )
        try:
            ok = await proveedor.enviar_mensaje(c["telefono"], mensaje)
            if ok:
                await guardar_mensaje(c["telefono"], "assistant", mensaje)
                await guardar_perfil_lead(c["telefono"], notas="relance envoyée")
                # marcar relance
                from agent.memory import async_session, PerfilLead
                from sqlalchemy import select
                async with async_session() as session:
                    res = await session.execute(
                        select(PerfilLead).where(PerfilLead.telefono == c["telefono"])
                    )
                    p = res.scalar_one_or_none()
                    if p:
                        p.relanzado = (p.relanzado or 0) + 1
                        await session.commit()
                enviados += 1
        except Exception as e:
            logger.error(f"Error al relanzar {c['telefono']}: {e}")

    if enviados:
        logger.info(f"[relance] {enviados} conversation(s) relancée(s)")
    return enviados

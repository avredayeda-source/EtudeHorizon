# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción).

Incluye:
  - Mensaje       : historial de la conversación.
  - PerfilLead    : hechos acumulados del cliente (auto-apprentissage + suivi
                    d'intention, hésitation, résumé, estado del lead).
  - Cita          : citas / rendez-vous agendados por Rosemonde.
"""

import os
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, select, Integer
from dotenv import load_dotenv

load_dotenv()

# Configuración de base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")

# Si es PostgreSQL en producción, ajustar el esquema de URL
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    """Modelo de mensaje en la base de datos."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" o "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PerfilLead(Base):
    """
    Perfil acumulado de cada lead (auto-apprentissage + suivi proactif).

    estado: nuevo | calificando | capturado | agendado | perdido
    """
    __tablename__ = "perfil_lead"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    pais_visado: Mapped[str] = mapped_column(String(80), default="")
    filiere: Mapped[str] = mapped_column(String(120), default="")
    budget: Mapped[str] = mapped_column(String(80), default="")
    documentos: Mapped[str] = mapped_column(Text, default="")   # lista separada por comas
    # --- Suivi d'intention / proactivité ---
    intencion: Mapped[str] = mapped_column(String(120), default="")   # ex: "estudiar en Inde"
    estado: Mapped[str] = mapped_column(String(30), default="nuevo")
    hesitacion: Mapped[str] = mapped_column(String(200), default="")  # dernière hésitation détectée
    resumen: Mapped[str] = mapped_column(Text, default="")            # résumé de la conversation
    notas: Mapped[str] = mapped_column(Text, default="")
    relanzado: Mapped[int] = mapped_column(Integer, default=0)        # nb de relances envoyées
    ultima_actividad: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Cita(Base):
    """Cita / rendez-vous agendado por Rosemonde."""
    __tablename__ = "citas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    fecha: Mapped[str] = mapped_column(String(40), default="")   # texto libre: "2026-07-10" o "lundi matin"
    hora: Mapped[str] = mapped_column(String(40), default="")
    motivo: Mapped[str] = mapped_column(Text, default="")
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def inicializar_db():
    """Crea las tablas si no existen y aplica una migración ligera (SQLite)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrar_columnas_faltantes)


def _migrar_columnas_faltantes(sync_conn):
    """
    Migración ligera para SQLite: agrega columnas nuevas a tablas existentes
    (create_all no altera tablas ya creadas). Evita tener que borrar la BD local
    al añadir campos. En PostgreSQL usa migraciones formales si lo necesitas.
    """
    from sqlalchemy import inspect, text

    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(sync_conn)
    tablas_existentes = inspector.get_table_names()

    tipos_sql = {
        "INTEGER": "INTEGER DEFAULT 0",
        "STRING": "VARCHAR",
        "TEXT": "TEXT",
        "DATETIME": "DATETIME",
    }

    for tabla in Base.metadata.tables.values():
        if tabla.name not in tablas_existentes:
            continue
        cols_actuales = {c["name"] for c in inspector.get_columns(tabla.name)}
        for columna in tabla.columns:
            if columna.name in cols_actuales:
                continue
            tipo = str(columna.type).split("(")[0].upper()
            tipo_sql = tipos_sql.get(tipo, "TEXT")
            sync_conn.execute(
                text(f'ALTER TABLE {tabla.name} ADD COLUMN {columna.name} {tipo_sql}')
            )


async def guardar_mensaje(telefono: str, role: str, content: str):
    """Guarda un mensaje en el historial de conversación."""
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.utcnow()
        )
        session.add(mensaje)
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """
    Recupera los últimos N mensajes de una conversación.

    Returns:
        Lista de diccionarios con role y content, en orden cronológico.
    """
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        result = await session.execute(query)
        mensajes = list(result.scalars().all())
        mensajes.reverse()  # los más recientes venían primero
        return [{"role": msg.role, "content": msg.content} for msg in mensajes]


async def contar_mensajes(telefono: str) -> int:
    """Cuenta cuántos mensajes tiene una conversación (para decidir cuándo resumir)."""
    async with async_session() as session:
        result = await session.execute(
            select(Mensaje).where(Mensaje.telefono == telefono)
        )
        return len(list(result.scalars().all()))


async def limpiar_historial(telefono: str):
    """Borra todo el historial de una conversación (mensajes + perfil + citas)."""
    async with async_session() as session:
        for modelo in (Mensaje, PerfilLead, Cita):
            result = await session.execute(
                select(modelo).where(modelo.telefono == telefono)
            )
            for fila in result.scalars().all():
                await session.delete(fila)
        await session.commit()


async def marcar_actividad(telefono: str):
    """Actualiza la marca de última actividad y resetea el contador de relance."""
    async with async_session() as session:
        result = await session.execute(
            select(PerfilLead).where(PerfilLead.telefono == telefono)
        )
        perfil = result.scalar_one_or_none()
        if perfil is None:
            perfil = PerfilLead(telefono=telefono)
            session.add(perfil)
        perfil.ultima_actividad = datetime.utcnow()
        perfil.relanzado = 0  # el cliente respondió → puede volver a relanzarse más tarde
        await session.commit()


async def obtener_conversaciones_inactivas(
    horas_min: float = 6.0, horas_max: float = 24.0, max_relances: int = 1
) -> list[dict]:
    """
    Devuelve leads inactivos candidatos a relance:
      - inactivos desde hace >= horas_min y <= horas_max (ventana WhatsApp de 24h)
      - que aún no fueron capturados/agendados
      - que no superaron max_relances
    """
    ahora = datetime.utcnow()
    limite_reciente = ahora - timedelta(hours=horas_min)
    limite_antiguo = ahora - timedelta(hours=horas_max)

    async with async_session() as session:
        result = await session.execute(select(PerfilLead))
        perfiles = list(result.scalars().all())

    candidatos = []
    for p in perfiles:
        if p.estado in ("capturado", "agendado", "perdido"):
            continue
        if p.relanzado >= max_relances:
            continue
        if p.ultima_actividad is None:
            continue
        if limite_antiguo <= p.ultima_actividad <= limite_reciente:
            candidatos.append({
                "telefono": p.telefono,
                "nombre": p.nombre,
                "pais_visado": p.pais_visado,
                "intencion": p.intencion,
            })
    return candidatos

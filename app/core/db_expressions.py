"""
Expressions SQLAlchemy compatibles SQLite et PostgreSQL.

Les fonctions retournent des expressions SQL, pas des valeurs Python.
Elles sont évaluées à l'exécution de la requête, pas à l'import du module.
"""

from sqlalchemy import Float, Integer, extract, func
from sqlalchemy.sql import cast

from app.core.config import settings


def duration_minutes_expr(start_col, end_col):
    """
    Durée en minutes entre deux colonnes DateTime.

    SQLite  : julianday arithmetic (pas d'intervalle natif)
    PostgreSQL : EXTRACT(EPOCH …) / 60
    """
    if settings.is_sqlite:
        return cast(
            (func.julianday(end_col) - func.julianday(start_col)) * 1440.0,
            Float,
        )
    return cast(
        extract("epoch", end_col - start_col) / 60.0,
        Float,
    )


def hour_of_day_expr(col):
    """
    Heure du jour (0–23) d'une colonne DateTime.

    SQLite  : CAST(strftime('%H', col) AS INTEGER)
    PostgreSQL : CAST(EXTRACT(hour FROM col) AS INTEGER)
    """
    if settings.is_sqlite:
        return cast(func.strftime("%H", col), Integer)
    return cast(extract("hour", col), Integer)

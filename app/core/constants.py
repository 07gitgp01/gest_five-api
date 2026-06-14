"""
Constantes partagées entre les services et repositories GestFive.
Centralise ce qui était dupliqué entre dashboard_service et admin_service.
"""

FR_MONTHS = [
    "",  # index 0 inutilisé — les mois SQLAlchemy sont 1-indexed
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def month_label(year: int, month: int) -> str:
    """Retourne 'Janvier 2026' pour (2026, 1)."""
    return f"{FR_MONTHS[month]} {year}"


def empty_month(year: int, month: int) -> dict:
    """Dict neutre pour un mois sans données dans un rapport de croissance."""
    return {
        "year": year,
        "month": month,
        "new_users": 0,
        "new_terrains": 0,
        "reservations": 0,
        "revenue": 0.0,
    }

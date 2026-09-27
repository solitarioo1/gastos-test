from datetime import date, datetime, timedelta, timezone

LIMA = timezone(timedelta(hours=-5))  # Perú no usa horario de verano


def ahora() -> datetime:
    return datetime.now(LIMA)


def hoy() -> date:
    return ahora().date()

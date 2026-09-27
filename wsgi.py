"""Punto de entrada para gunicorn en producción (Docker/VPS).

Uso local: sigue siendo `python app.py`. Esto es solo para el contenedor.
"""
from app import create_app

app = create_app()

"""
PREDICTA – Database Connection Module
Defaults to SQLite for local development (no PostgreSQL required).
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

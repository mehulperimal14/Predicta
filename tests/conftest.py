"""
Test configuration: must run before the backend is imported, because config.py reads
the environment at import time. Without this the API tests wrote into the developer's
backend/instance/predicta.db and backend/uploads/.
"""

import os
import secrets
import tempfile

os.environ["DATABASE_URL"] = "sqlite://"            # in-memory, one database per app instance
os.environ["SECRET_KEY"] = secrets.token_hex(32)     # keep backend/instance/ untouched
os.environ["UPLOAD_FOLDER"] = tempfile.mkdtemp(prefix="predicta-test-uploads-")
os.environ.setdefault("FLASK_ENV", "development")   # demo passwords for the login tests
os.environ["MQTT_ENABLED"] = "False"

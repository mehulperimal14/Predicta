"""
PREDICTA – Flask Backend Application Entry Point
Run: python app.py
"""

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO
import os, sys

# Ensure backend dir is in path
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from database import db

socketio = SocketIO()


def create_app(config_class=Config):
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    app = Flask(__name__, static_folder=frontend_dir, static_url_path="")
    app.config.from_object(config_class)

    # Ensure upload directory exists
    os.makedirs(app.config.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "uploads")), exist_ok=True)

    # Extensions
    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    JWTManager(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    # Register Blueprints
    from routes.auth_routes         import auth_bp
    from routes.sensor_routes       import sensor_bp
    from routes.prediction_routes   import prediction_bp
    from routes.alert_routes        import alert_bp
    from routes.analytics_routes    import analytics_bp
    from routes.report_routes       import report_bp
    from routes.ingestion_routes    import ingestion_bp
    from routes.notification_routes import notification_bp

    app.register_blueprint(auth_bp,         url_prefix="/api/auth")
    app.register_blueprint(sensor_bp,       url_prefix="/api/sensor")
    app.register_blueprint(prediction_bp,   url_prefix="/api/predict")
    app.register_blueprint(alert_bp,        url_prefix="/api/alerts")
    app.register_blueprint(analytics_bp,    url_prefix="/api/analytics")
    app.register_blueprint(report_bp,       url_prefix="/api/reports")
    app.register_blueprint(ingestion_bp,    url_prefix="/api/ingest")
    app.register_blueprint(notification_bp, url_prefix="/api/notifications")

    # Health-check route
    @app.route("/api/health")
    def api_health():
        return jsonify({
            "status": "PREDICTA 2.0 Online",
            "version": "2.0.0",
            "architecture": "AI-Powered Industrial Predictive Maintenance",
            "database": "connected"
        })

    # Serve Frontend UI
    @app.route("/")
    def serve_index():
        return app.send_static_file("index.html")

    @app.route("/<path:path>")
    def serve_static_files(path):
        if os.path.exists(os.path.join(frontend_dir, path)):
            return app.send_static_file(path)
        return app.send_static_file("index.html")

    # Create DB tables
    with app.app_context():
        db.create_all()
        _seed_default_data(app)

    return app



def _seed_default_data(app):
    """Create default admin user and machine if not exist."""
    from models import User, Machine
    from werkzeug.security import generate_password_hash

    if not User.query.filter_by(username="admin").first():
        db.session.add(User(
            username="admin",
            email="admin@predicta.local",
            password_hash=generate_password_hash("Predicta@2024"),
            role="admin",
            is_active=True
        ))

    if not User.query.filter_by(username="engineer").first():
        db.session.add(User(
            username="engineer",
            email="engineer@predicta.local",
            password_hash=generate_password_hash("Engineer@2024"),
            role="engineer",
            is_active=True
        ))

    if not User.query.filter_by(username="operator").first():
        db.session.add(User(
            username="operator",
            email="operator@predicta.local",
            password_hash=generate_password_hash("Operator@2024"),
            role="operator",
            is_active=True
        ))

    from models import Machine
    if not Machine.query.filter_by(device_id="MOTOR_01").first():
        db.session.add(Machine(
            device_id="MOTOR_01",
            name="Cooling Tower Pump Motor #1",
            location="Production Hall A",
            machine_type="induction_motor",
            rated_power=1.5,
            rated_current=3.5,
            rated_voltage=415,
            rated_rpm=1440,
        ))

    db.session.commit()
    print("[INIT] Database seeded: admin/Predicta@2024 | engineer/Engineer@2024 | operator/Operator@2024")


app = create_app()


if __name__ == "__main__":
    print("=" * 60)
    print("  PREDICTA Industrial Monitoring Backend")
    print("  API:       http://localhost:5000/api")
    print("  Dashboard: open frontend/index.html in browser")
    print("  Login:     admin / Predicta@2024")
    print("=" * 60)

    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

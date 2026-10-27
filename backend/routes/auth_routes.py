"""
PREDICTA – Authentication Routes
JWT-based login, token refresh, and role-based access control.
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt
)
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from database import db
from models import User

auth_bp = Blueprint("auth", __name__)

# Identity used for password-less public sessions (PUBLIC_ACCESS=true); not a database user.
VISITOR = "visitor"
VISITOR_PROFILE = {"username": "Visitor", "email": "", "role": "admin", "is_active": True, "public": True}


@auth_bp.route("/visitor", methods=["POST"])
def visitor_session():
    """
    POST /api/auth/visitor
    Open access: signs the caller in without a password as an admin "Visitor".
    Returns 403 when PUBLIC_ACCESS is disabled.
    """
    if not current_app.config.get("PUBLIC_ACCESS"):
        return jsonify({"error": "Public access is disabled. Please sign in."}), 403
    claims = {"role": VISITOR_PROFILE["role"], "email": ""}
    return jsonify({
        "access_token": create_access_token(identity=VISITOR, additional_claims=claims),
        "refresh_token": create_refresh_token(identity=VISITOR),
        "user": VISITOR_PROFILE,
    }), 200


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    POST /api/auth/login
    Body: { username, password }
    Returns: { access_token, refresh_token, user }
    """
    data = request.get_json()
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"error": "Username and password required"}), 400

    user = User.query.filter_by(username=data["username"]).first()
    if not user or not check_password_hash(user.password_hash, data["password"]):
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.is_active:
        return jsonify({"error": "Account disabled. Contact administrator."}), 403

    # Update last login
    user.last_login = datetime.utcnow()
    db.session.commit()

    additional_claims = {"role": user.role, "email": user.email}
    access_token  = create_access_token(identity=user.username, additional_claims=additional_claims)
    refresh_token = create_refresh_token(identity=user.username)

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict()
    }), 200


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    if identity == VISITOR:
        claims = {"role": VISITOR_PROFILE["role"], "email": ""}
        return jsonify({"access_token": create_access_token(identity=VISITOR, additional_claims=claims)}), 200
    user = User.query.filter_by(username=identity).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    claims = {"role": user.role, "email": user.email}
    token = create_access_token(identity=identity, additional_claims=claims)
    return jsonify({"access_token": token}), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    identity = get_jwt_identity()
    if identity == VISITOR:
        return jsonify(VISITOR_PROFILE), 200
    user = User.query.filter_by(username=identity).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user.to_dict()), 200


@auth_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    """Admin only: list all users."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    users = User.query.all()
    return jsonify([u.to_dict() for u in users]), 200


@auth_bp.route("/users", methods=["POST"])
@jwt_required()
def create_user():
    """Admin only: create new user."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json()
    required = ["username", "email", "password", "role"]
    if not all(data.get(f) for f in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already exists"}), 409

    if data["role"] not in ("admin", "engineer", "operator"):
        return jsonify({"error": "Role must be: admin, engineer, operator"}), 400

    user = User(
        username=data["username"],
        email=data["email"],
        password_hash=generate_password_hash(data["password"]),
        role=data["role"],
        is_active=True
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@auth_bp.route("/users/<int:user_id>", methods=["PATCH"])
@jwt_required()
def update_user(user_id):
    """Admin: update user (disable, change role, reset password)."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    user = User.query.get_or_404(user_id)
    data = request.get_json()

    if "is_active" in data:
        user.is_active = bool(data["is_active"])
    if "role" in data and data["role"] in ("admin", "engineer", "operator"):
        user.role = data["role"]
    if "password" in data:
        user.password_hash = generate_password_hash(data["password"])

    db.session.commit()
    return jsonify(user.to_dict()), 200

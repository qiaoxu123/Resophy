"""
Authentication routes: login, logout, session check.
"""

from __future__ import annotations

from flask import Flask, jsonify, request

from resophy.auth import authenticate, create_token, verify_token
from resophy.config import AppConfig


def register_auth_routes(app: Flask, *, cfg: AppConfig) -> None:

    @app.route("/api/auth/login", methods=["POST"])
    def api_auth_login():
        data = request.json or {}
        identification = (data.get("identification") or "").strip()
        password = data.get("password") or ""

        if not identification or not password:
            return jsonify({"success": False, "error": "Username and password are required"}), 400

        ok, user_info, err = authenticate(identification, password, cfg)
        if not ok:
            return jsonify({"success": False, "error": err}), 401

        token = create_token(user_info["id"], user_info["username"], cfg)

        return jsonify({
            "success": True,
            "token": token,
            "user": {
                "id": user_info["id"],
                "username": user_info["username"],
                "display_name": user_info.get("display_name", ""),
                "avatar_url": user_info.get("avatar_url"),
            },
        })

    @app.route("/api/auth/check", methods=["GET"])
    def api_auth_check():
        """Check whether the current token is valid and return user info."""
        token = _extract_token(request)
        if not token:
            return jsonify({"authenticated": False}), 401

        payload = verify_token(token, cfg)
        if not payload:
            return jsonify({"authenticated": False}), 401

        return jsonify({
            "authenticated": True,
            "user": {
                "id": payload["sub"],
                "username": payload.get("username", ""),
            },
        })

    @app.route("/api/auth/logout", methods=["POST"])
    def api_auth_logout():
        """Logout is client-side (discard token).  This endpoint exists for
        consistency and potential future server-side token revocation."""
        return jsonify({"success": True})


def _extract_token(req) -> str | None:
    """Extract JWT from Authorization header or query parameter."""
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return req.args.get("token")

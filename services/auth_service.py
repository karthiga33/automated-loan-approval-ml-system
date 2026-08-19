"""
Authentication & Authorization Service
JWT-based authentication for the Loan Approval API.
Free tier friendly - no external auth service needed.
"""
import hashlib
import hmac
import json
import time
import base64
import uuid
import os
from datetime import datetime, timedelta
from functools import wraps


# Simple JWT implementation (no external dependency needed for free tier)
JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "loan-approval-system-secret-change-in-prod")
JWT_EXPIRY_HOURS = 24


def generate_token(user_id: str, role: str = "applicant") -> str:
    """
    Generate a JWT token for authenticated users.
    
    Args:
        user_id: Unique user identifier
        role: User role ('applicant', 'admin', 'reviewer')
        
    Returns:
        JWT token string
    """
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": user_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time() + JWT_EXPIRY_HOURS * 3600),
        "jti": str(uuid.uuid4())
    }

    # Encode header and payload
    header_encoded = _base64url_encode(json.dumps(header))
    payload_encoded = _base64url_encode(json.dumps(payload))

    # Create signature
    message = f"{header_encoded}.{payload_encoded}"
    signature = hmac.new(
        JWT_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature_encoded = _base64url_encode_bytes(signature)

    return f"{header_encoded}.{payload_encoded}.{signature_encoded}"


def verify_token(token: str) -> dict:
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload dict or None if invalid
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_encoded, payload_encoded, signature_encoded = parts

        # Verify signature
        message = f"{header_encoded}.{payload_encoded}"
        expected_signature = hmac.new(
            JWT_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        expected_encoded = _base64url_encode_bytes(expected_signature)

        if not hmac.compare_digest(signature_encoded, expected_encoded):
            return None

        # Decode payload
        payload = json.loads(_base64url_decode(payload_encoded))

        # Check expiry
        if payload.get("exp", 0) < int(time.time()):
            return None

        return payload

    except Exception:
        return None


def generate_api_key() -> str:
    """Generate a random API key for service-to-service auth."""
    return f"lak_{uuid.uuid4().hex}"


def hash_password(password: str, salt: str = None) -> tuple:
    """
    Hash a password with salt for storage.
    
    Returns:
        (hashed_password, salt) tuple
    """
    if salt is None:
        salt = uuid.uuid4().hex
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        100000
    )
    return hashed.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against stored hash."""
    computed, _ = hash_password(password, salt)
    return hmac.compare_digest(computed, hashed)


def _base64url_encode(data: str) -> str:
    """Base64url encode a string."""
    return base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()


def _base64url_encode_bytes(data: bytes) -> str:
    """Base64url encode bytes."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _base64url_decode(data: str) -> str:
    """Base64url decode a string."""
    padding = 4 - len(data) % 4
    data += "=" * padding
    return base64.urlsafe_b64decode(data).decode()


# Rate limiting (in-memory, suitable for single instance)
_request_counts = {}


def check_rate_limit(client_id: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    """
    Check if client has exceeded rate limit.
    
    Args:
        client_id: Client identifier (IP or user_id)
        max_requests: Maximum requests per window
        window_seconds: Time window in seconds
        
    Returns:
        True if allowed, False if rate limited
    """
    now = time.time()
    window_start = now - window_seconds

    if client_id not in _request_counts:
        _request_counts[client_id] = []

    # Remove old entries
    _request_counts[client_id] = [
        t for t in _request_counts[client_id] if t > window_start
    ]

    # Check limit
    if len(_request_counts[client_id]) >= max_requests:
        return False

    # Record request
    _request_counts[client_id].append(now)
    return True


def require_auth(f):
    """
    Decorator to require authentication on Flask routes.
    
    Usage:
        @app.route('/protected')
        @require_auth
        def protected_route():
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request, jsonify

        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid authorization header"}), 401

        token = auth_header.split(" ")[1]
        payload = verify_token(token)

        if payload is None:
            return jsonify({"error": "Invalid or expired token"}), 401

        # Add user info to request context
        request.user_id = payload.get("user_id")
        request.user_role = payload.get("role")

        return f(*args, **kwargs)

    return decorated


def require_role(allowed_roles: list):
    """
    Decorator to require specific roles.
    
    Usage:
        @app.route('/admin')
        @require_auth
        @require_role(['admin'])
        def admin_route():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from flask import request, jsonify

            if not hasattr(request, "user_role"):
                return jsonify({"error": "Authentication required"}), 401

            if request.user_role not in allowed_roles:
                return jsonify({"error": "Insufficient permissions"}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator

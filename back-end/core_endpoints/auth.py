"""
Authentication Endpoints - user registration, login, logout, and token verification


KEY CONCEPTS:
- ADMIN_SECRET: Pre-shared secret used ONLY during registration to grant initial admin privileges.
  Once registered, admin status is managed by existing admins in admin.py.
  Returned password is generated (12+ chars with mixed case, digits, symbols) and sent to user once.
- Token Verification: check_token() is a FastAPI dependency that validates JWT tokens.
  Two-level verification: (1) JWT decode with role claim, (2) database query to confirm active session.
  Returns user data (username, user_id, role) for use in protected endpoints.


Functions:
- generate_password(): Creates random secure password for new registrations.
- register(): Create new user account. Admin privileges require correct ADMIN_SECRET.
- login(): Authenticate user, generate JWT token with role claim, create session record.
- logout(): Revoke user session token, marking it as inactive.
- check_token(): FastAPI dependency for token validation (JWT + database status check).


Database Operations:
- Passwords are hashed with bcrypt before storage (pwd_context)
- Tokens stored in login_sessions table for revocation tracking
- JWT tokens include role claim for fast authorization checks
- Token revocation prevents replay attacks even after JWT expiration time
"""

from models import RegisterRequest, LoginRequest, LogoutRequest
from services.database import (
    conn,
    insert_user,
    select_password,
    select_user_id,
    insert_session,
    revoke_session,
    check_session_status,
)
from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import pwd_context, SECRET_KEY, ADMIN_SECRET
import sqlite3
import string
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional


security = HTTPBearer()


async def get_optional_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
) -> Optional[str]:
    """
    Extract token from Authorization header if present.
    Token is optional - returns None if not provided.
    """
    if credentials:
        return credentials.credentials
    return None


def generate_password(length: int = 12) -> str:
    """
    Generate a random secure password with mixed character types.


    Args:
        length (int): Password length in characters. Defaults to 12.


    Returns:
        str: Random password containing lowercase, uppercase, digits, and special characters.


    Note:
        Used during user registration to create an initial password.
        Password includes: a-z, A-Z, 0-9, !@#$%^&*-_+=?
    """
    characters = (
        string.ascii_lowercase
        + string.ascii_uppercase
        + string.digits
        + "!@#$%^&*-_+=?"
    )

    password = "".join(secrets.choice(characters) for _ in range(length))
    return password


def register(
    user: RegisterRequest, token: Optional[str] = Depends(get_optional_token)
) -> dict:
    """
    Register a new user account in the system.

    Two-tier security:
    - First admin: Can be created with ADMIN_SECRET (no token needed)
    - Other users: Require admin token to create

    Args:
        user (RegisterRequest): Registration request containing full_name, username, is_admin flag, and optional admin_secret.
        credentials (HTTPAuthorizationCredentials): Bearer token from Authorization header (optional for first admin).


    Returns:
        dict: Contains username, generated password, admin status, and success message.


    Raises:
        HTTPException(401): If token is invalid or missing (when not first admin).
        HTTPException(403): If admin_secret invalid or caller not admin.
        HTTPException(400): If username already exists (duplicate).


    Process:
        1. Check if this is a request to create first admin (is_admin=True)
        2. If creating admin: validate ADMIN_SECRET (no token needed)
        3. If creating user: verify caller is admin using JWT token
        4. Generate random 12-character password, hash it, insert to database
        5. Return credentials to caller
    """
    cursor = conn.cursor()
    is_admin = False

    # Check if user wants admin privileges
    if user.is_admin:
        # Validate admin secret
        if user.admin_secret != ADMIN_SECRET:
            raise HTTPException(status_code=403, detail="Invalid admin secret")

        # Check if this is the FIRST admin being created
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        admin_count = cursor.fetchone()[0]

        # If no admins exist, allow creation with just the secret (no token needed)
        if admin_count > 0:
            # If admins already exist, require admin token
            if not token:
                raise HTTPException(status_code=401, detail="Token required when admins exist")

            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
                role = payload.get("role")

                if role != "admin":
                    raise HTTPException(
                        status_code=403, detail="Only administrators can register new admins"
                    )
            except JWTError:
                raise HTTPException(status_code=401, detail="Invalid admin token")

        is_admin = True

    else:
        # Creating a regular user - always requires admin token
        if not token:
            raise HTTPException(status_code=401, detail="Token required to register users")

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            role = payload.get("role")

            if role != "admin":
                raise HTTPException(
                    status_code=403, detail="Only administrators can register users"
                )
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid admin token")

    generated_password = generate_password(12)
    hashed_password = pwd_context.hash(generated_password)

    try:
        cursor.execute(
            insert_user, (user.full_name, user.username, hashed_password, is_admin)
        )
        conn.commit()
        return {
            "message": "User registered successfully",
            "username": user.username,
            "password": generated_password,
            "is_admin": is_admin,
        }
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="User already exists")
    finally:
        cursor.close()


def login(user: LoginRequest) -> dict:
    """
    Authenticate user and generate JWT access token.


    Args:
        user (LoginRequest): Login request containing username and password.


    Returns:
        dict: Contains access_token (JWT) and role ("admin" or "user").


    Raises:
        HTTPException(401): If username not found or password verification fails.


    Process:
        1. Look up user by username
        2. Verify provided password against bcrypt hash
        3. Fetch user_id and is_admin status from database
        4. Generate JWT token with claims:
           - sub: username
           - user_id: user identifier
           - role: "admin" or "user" (embedded in token for fast verification)
           - jti: unique token identifier
           - exp: expiration (24 hours from now)
        5. Store token in login_sessions table with 'active' status
        6. Return token and role to client


    Security:
        - Password never exposed in responses or logs
        - Token expires in 24 hours
        - Each token has unique jti for revocation tracking
    """
    cursor = conn.cursor()
    try:
        cursor.execute(select_password, (user.username,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        hashed_password = result[0]

        is_valid = pwd_context.verify(user.password, hashed_password)
        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        cursor.execute(select_user_id, (user.username,))
        user_id = cursor.fetchone()[0]

        # Fetch is_admin status from database
        cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        is_admin = cursor.fetchone()[0]

        # Generate token with role claim included
        token = jwt.encode(
            {
                "sub": user.username,
                "user_id": user_id,
                "role": "admin" if is_admin else "user",
                "jti": str(uuid.uuid4()),
                "exp": datetime.utcnow() + timedelta(hours=24),
            },
            SECRET_KEY,
        )

        cursor.execute(insert_session, (token, user_id))
        conn.commit()

        return {"access_token": token, "role": "admin" if is_admin else "user"}
    finally:
        cursor.close()


def logout(logout_request: LogoutRequest) -> dict:
    """
    Revoke user session token (logout).


    Args:
        logout_request (LogoutRequest): Logout request containing the token to revoke.


    Returns:
        dict: Success message confirming logout.


    Raises:
        HTTPException(400): If token is invalid, non-existent, or already revoked.


    Process:
        1. Look up token in login_sessions table
        2. Check current status (active or revoked)
        3. If valid and active, update status to 'revoked' in database
        4. Return success message


    Security:
        - Revoked tokens cannot be re-used for authentication
        - Token status checked in database (not just JWT expiration)
        - Prevents token replay attacks after logout
    """
    token = logout_request.token

    cursor = conn.cursor()
    try:
        cursor.execute(check_session_status, (token,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=400, detail="Invalid or non-existent token")

        status = result[0]

        if status == "revoked":
            raise HTTPException(status_code=400, detail="Token already revoked")

        cursor.execute(revoke_session, (token,))
        conn.commit()

        return {"message": "Logged out successfully"}
    finally:
        cursor.close()


def check_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    FastAPI dependency: validate JWT token and verify session status.


    Args:
        credentials (HTTPAuthorizationCredentials): Bearer token from Authorization header.


    Returns:
        dict: User data including username, user_id, role, and token.


    Raises:
        HTTPException(401): If token expired, invalid, malformed, or revoked in database.
        HTTPException(403): If token is found but marked as revoked.


    Process:
        1. Extract Bearer token from Authorization header
        2. Decode JWT token (validates signature and expiration)
        3. Query login_sessions table to check token status
        4. Reject if revoked, expired, or not found
        5. Return user data with token for use in protected endpoints


    Security:
        - Two-level verification prevents replay after logout
        - Database query confirms token hasn't been revoked (logout, reissue, etc.)
        - Role claim extracted from token (no second DB lookup needed)
        - Used as FastAPI dependency in all protected endpoints
    """
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401, detail="Token expired. Please log in again."
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    cursor = conn.cursor()
    try:
        cursor.execute(check_session_status, (token,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(
                status_code=401, detail="Invalid token. Please log in again."
            )

        if result[0] != "active":
            raise HTTPException(
                status_code=401, detail="Token has been revoked. Please log in again."
            )

        payload["token"] = token
        return payload
    finally:
        cursor.close()

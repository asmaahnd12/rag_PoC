"""
Admin API Endpoints - for managing users and permissions

KEY NOTES:
- SECRET_KEY: Master key for signing/verifying all JWT tokens. Required in .env.
- ADMIN_SECRET: One-time gatekeeper used during user registration to grant initial admin privileges.
  Only checked when a new user registers with is_admin=True flag. Admin status thereafter is managed
  by existing admins via the update_user_admin() endpoint.

Functions:
- verify_admin(): Validates JWT token has 'admin' role claim AND checks token is active in database (not revoked).
  Performs two-level validation for security against revoked/stolen tokens on every request.
- get_user(): Fetch info about a specific user or authenticated admin. Admin-only.
- list_all_users(): Retrieve all users in the system. Admin-only.
- update_user_admin(): Promote/demote users between admin and regular roles. Prevents self-demotion. Admin-only.
"""

from fastapi import HTTPException, Depends
from services.database import (
    conn,
    get_user_by_id,
    get_all_users,
    update_user_admin_status,
    update_username_by_id,
    select_user_id,
    check_session_status,
    delete_user_by_id,
    get_user_id_by_username,
    count_user_messages_in_range,
    get_assistant_sources_in_range,
    get_user_file_daily_stats,
)
from models import (
    UpdateUserAdminRequest,
    UpdateUsernameRequest,
    DeleteUserRequest,
    UserInfoResponse,
)
from core_endpoints.auth import check_token
from jose import jwt, JWTError
from config import SECRET_KEY
import sqlite3
import json
from datetime import datetime, timedelta


def verify_admin(token: str) -> int:
    """
    Verify that the token belongs to an active admin user.

    Performs two-level validation:
    1. Decodes JWT and verifies 'admin' role claim
    2. Checks login_sessions table to ensure token has NOT been revoked

    Returns the user_id if valid, raises HTTPException otherwise.

    Raises:
        HTTPException(401): If JWT is invalid or malformed
        HTTPException(403): If token is valid but user lacks admin role
        HTTPException(400): If token has been revoked (logged out)
    """
    try:
        # Step 1: Decode and validate JWT structure
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        role = payload.get("role")
        user_id = payload.get("user_id")

        if role != "admin":
            raise HTTPException(
                status_code=403, detail="Only administrators can perform this action"
            )

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Step 2: Verify token has not been revoked in database
        cursor = conn.cursor()
        try:
            cursor.execute(check_session_status, (token,))
            result = cursor.fetchone()

            if not result:
                # Token not found in sessions table (invalid or tampered)
                raise HTTPException(status_code=401, detail="Invalid token")

            status = result[0]
            if status == "revoked":
                # Token was logged out - cannot use anymore
                raise HTTPException(
                    status_code=400,
                    detail="Token has been revoked. Please log in again.",
                )

            return user_id
        finally:
            cursor.close()

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_user(token: str, username: str = None):
    """
    Get user information (admin only).
    If username is provided, returns info for that user.
    If no username is provided, returns info for the authenticated user.
    """
    admin_user_id = verify_admin(token)

    cursor = conn.cursor()
    try:
        if username:
            # Get info for specified user
            cursor.execute(select_user_id, (username,))
            result = cursor.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="User not found")
            target_user_id = result[0]
        else:
            # Get info for authenticated user
            target_user_id = admin_user_id

        cursor.execute(get_user_by_id, (target_user_id,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="User not found")

        user_id, full_name, username_result, is_admin = result
        return UserInfoResponse(
            id=user_id,
            full_name=full_name,
            username=username_result,
            is_admin=bool(is_admin),
        )
    finally:
        cursor.close()


def list_all_users(token: str) -> list:
    """
    List all users (admin only).
    """
    verify_admin(token)

    cursor = conn.cursor()
    try:
        cursor.execute(get_all_users)
        results = cursor.fetchall()

        users = [
            UserInfoResponse(
                id=row[0],
                full_name=row[1],
                username=row[2],
                is_admin=bool(row[3]),
            )
            for row in results
        ]
        return users
    finally:
        cursor.close()


def update_user_admin(request: UpdateUserAdminRequest):
    """
    Update a user's admin status (admin only).
    """
    admin_user_id = verify_admin(request.token)

    cursor = conn.cursor()
    try:
        # Get target user ID
        cursor.execute(select_user_id, (request.target_username,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Target user not found")

        target_user_id = result[0]

        # Prevent self-demotion
        if target_user_id == admin_user_id and not request.is_admin:
            raise HTTPException(
                status_code=400,
                detail="You cannot revoke your own administrator privileges",
            )

        # Update admin status
        cursor.execute(
            update_user_admin_status,
            (int(request.is_admin), target_user_id),
        )
        conn.commit()

        action = (
            "promoted to administrator"
            if request.is_admin
            else "demoted to regular user"
        )
        return {
            "message": f"User '{request.target_username}' {action}",
            "username": request.target_username,
            "is_admin": request.is_admin,
        }
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


def update_username(request: UpdateUsernameRequest) -> dict:
    """
    Update a user's username (admin only).
    """
    verify_admin(request.token)

    current_username = request.target_username.strip()
    new_username = request.new_username.strip()

    if not current_username or not new_username:
        raise HTTPException(status_code=400, detail="Usernames cannot be empty")

    if current_username == new_username:
        raise HTTPException(
            status_code=400, detail="New username must be different from current"
        )

    cursor = conn.cursor()
    try:
        cursor.execute(select_user_id, (current_username,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Target user not found")

        target_user_id = result[0]

        cursor.execute(select_user_id, (new_username,))
        if cursor.fetchone():
            raise HTTPException(status_code=409, detail="Username already in use")

        cursor.execute(update_username_by_id, (new_username, target_user_id))
        conn.commit()

        return {
            "message": "Username updated",
            "old_username": current_username,
            "new_username": new_username,
        }
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already in use")
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


def delete_user(request: DeleteUserRequest) -> dict:
    """
    Delete a user account (admin only).
    """
    admin_user_id = verify_admin(request.token)

    cursor = conn.cursor()
    try:
        cursor.execute(select_user_id, (request.target_username,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Target user not found")

        target_user_id = result[0]

        if target_user_id == admin_user_id:
            raise HTTPException(
                status_code=400,
                detail="You cannot delete your own administrator account",
            )

        cursor.execute(delete_user_by_id, (target_user_id,))
        conn.commit()

        return {
            "message": f"User '{request.target_username}' deleted",
            "username": request.target_username,
        }
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()


def _parse_date_param(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )
    return parsed


def _resolve_date_range(
    start_date: str | None, end_date: str | None
) -> tuple[datetime, datetime]:
    now = datetime.utcnow()

    if start_date and end_date:
        start_dt = _parse_date_param(start_date)
        end_dt = _parse_date_param(end_date) + timedelta(days=1)
    elif start_date:
        start_dt = _parse_date_param(start_date)
        end_dt = start_dt + timedelta(days=7)
    elif end_date:
        end_dt = _parse_date_param(end_date) + timedelta(days=1)
        start_dt = end_dt - timedelta(days=7)
    else:
        end_dt = now
        start_dt = now - timedelta(days=7)

    if end_dt <= start_dt:
        raise HTTPException(
            status_code=400, detail="End date must be after start date."
        )

    return start_dt, end_dt


def _normalize_file_type(value: str | None) -> str:
    if not value:
        return "unknown"
    cleaned = value.strip().lower()
    if cleaned.startswith("."):
        cleaned = cleaned[1:]
    if cleaned in {"text", "markdown", "md"}:
        return "txt"
    return cleaned or "unknown"


def _build_file_usage_summary(sources_rows: list[str]) -> dict:
    file_usage_map: dict[str, dict] = {}
    file_type_usage_counts: dict[str, int] = {}
    file_type_unique: dict[str, set] = {}

    for sources_json in sources_rows:
        if not sources_json:
            continue
        try:
            sources = json.loads(sources_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(sources, list):
            continue

        message_files: dict[str, dict] = {}
        for source in sources:
            if not isinstance(source, dict):
                continue
            filename = (source.get("filename") or "Document").strip()
            file_type = _normalize_file_type(source.get("file_type"))
            source_path = (source.get("source_path") or "").strip()
            key = source_path or filename

            if key not in message_files:
                message_files[key] = {
                    "filename": filename,
                    "file_type": file_type,
                    "source_path": source_path or None,
                }

        for key, meta in message_files.items():
            usage = file_usage_map.get(key)
            if usage is None:
                file_usage_map[key] = {
                    "filename": meta["filename"],
                    "file_type": meta["file_type"],
                    "source_path": meta["source_path"],
                    "uses": 1,
                }
            else:
                usage["uses"] += 1

            file_type_usage_counts[meta["file_type"]] = (
                file_type_usage_counts.get(meta["file_type"], 0) + 1
            )
            file_type_unique.setdefault(meta["file_type"], set()).add(key)

    file_type_unique_counts = {
        file_type: len(files) for file_type, files in file_type_unique.items()
    }
    file_usage_list = sorted(
        file_usage_map.values(),
        key=lambda item: (-item["uses"], item["filename"].lower()),
    )

    return {
        "file_usage": file_usage_list,
        "file_type_unique_counts": file_type_unique_counts,
        "file_type_usage_counts": file_type_usage_counts,
        "total_files_used": len(file_usage_map),
        "total_file_uses": sum(file_type_usage_counts.values()),
    }


def get_weekly_user_stats(
    username: str,
    start_date: str | None = None,
    end_date: str | None = None,
    user_data: dict = Depends(check_token),
) -> dict:
    if user_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    username_clean = username.strip()
    if not username_clean:
        raise HTTPException(status_code=400, detail="Username is required")

    user_id = get_user_id_by_username(username_clean)
    if user_id is None:
        raise HTTPException(status_code=404, detail="User not found")

    start_dt, end_dt = _resolve_date_range(start_date, end_date)
    start_ts = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_ts = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    request_count = count_user_messages_in_range(
        user_id, start_ts, end_ts, session_scope="active"
    )
    sources_rows = get_assistant_sources_in_range(
        user_id, start_ts, end_ts, session_scope="active"
    )
    active_summary = _build_file_usage_summary(sources_rows)

    request_count_deleted = count_user_messages_in_range(
        user_id, start_ts, end_ts, session_scope="deleted"
    )
    deleted_sources_rows = get_assistant_sources_in_range(
        user_id, start_ts, end_ts, session_scope="deleted"
    )
    deleted_summary = _build_file_usage_summary(deleted_sources_rows)

    end_date_out = (end_dt - timedelta(seconds=1)).date().isoformat()

    return {
        "username": username_clean,
        "start_date": start_dt.date().isoformat(),
        "end_date": end_date_out,
        "request_count": request_count,
        "total_files_used": active_summary["total_files_used"],
        "total_file_uses": active_summary["total_file_uses"],
        "file_type_unique_counts": active_summary["file_type_unique_counts"],
        "file_type_usage_counts": active_summary["file_type_usage_counts"],
        "file_usage": active_summary["file_usage"],
        "request_count_deleted": request_count_deleted,
        "total_files_used_deleted": deleted_summary["total_files_used"],
        "total_file_uses_deleted": deleted_summary["total_file_uses"],
        "file_type_unique_counts_deleted": deleted_summary["file_type_unique_counts"],
        "file_type_usage_counts_deleted": deleted_summary["file_type_usage_counts"],
        "file_usage_deleted": deleted_summary["file_usage"],
    }


def get_user_file_daily_trend(
    username: str,
    source_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    session_scope: str | None = None,
    user_data: dict = Depends(check_token),
) -> dict:
    """
    Get daily usage statistics for a specific file within a week.

    Returns:
        {
            "username": str,
            "filename": str,
            "start_date": str,
            "end_date": str,
            "session_scope": str,
            "daily_usage": {date: count, ...}  # 7 days of data
        }
    """
    if user_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    username_clean = username.strip()
    if not username_clean:
        raise HTTPException(status_code=400, detail="Username is required")

    source_path_clean = source_path.strip()
    if not source_path_clean:
        raise HTTPException(status_code=400, detail="Source path is required")

    user_id = get_user_id_by_username(username_clean)
    if user_id is None:
        raise HTTPException(status_code=404, detail="User not found")

    start_dt, end_dt = _resolve_date_range(start_date, end_date)
    start_ts = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_ts = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    scope = (session_scope or "active").lower()
    if scope not in {"active", "deleted", "all"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid session_scope. Use active, deleted, or all.",
        )

    # Get daily stats for this file
    daily_usage = get_user_file_daily_stats(
        user_id, source_path_clean, start_ts, end_ts, session_scope=scope
    )

    # Fill in missing days with 0
    current = start_dt
    filled_usage = {}
    while current < end_dt:
        date_key = current.date().isoformat()
        filled_usage[date_key] = daily_usage.get(date_key, 0)
        current += timedelta(days=1)

    end_date_out = (end_dt - timedelta(seconds=1)).date().isoformat()

    return {
        "username": username_clean,
        "filename": source_path_clean,
        "start_date": start_dt.date().isoformat(),
        "end_date": end_date_out,
        "session_scope": scope,
        "daily_usage": filled_usage,
    }

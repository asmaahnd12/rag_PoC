"""
Personalities API Endpoints

Rules:
- Admin-only for create / update / delete
- All authenticated users can list available personalities
- Max 5 personalities total
"""

from fastapi import Depends, HTTPException
from core_endpoints.auth import check_token
from models import (
    PersonalityCreateRequest,
    PersonalityUpdateRequest,
    PersonalityResponse,
)
from services.personalities_store import (
    STANDARD_PERSONALITY_ID,
    MAX_CUSTOM_PERSONALITIES,
    count_custom_personalities,
    create_personality,
    get_all_personalities,
    get_personality_by_id,
    update_personality,
    delete_personality,
)


def require_admin(user_data: dict = Depends(check_token)) -> dict:
    if user_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_data


def list_available_personalities(
    user_data: dict = Depends(check_token),
) -> list[PersonalityResponse]:
    """
    Read-only endpoint for all authenticated users.
    Used by the chat personality dropdown.
    """
    personalities = get_all_personalities()
    return [PersonalityResponse(**p) for p in personalities]


def add_personality(
    payload: PersonalityCreateRequest,
    user_data: dict = Depends(require_admin),
) -> PersonalityResponse:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Personality name cannot be empty.")

    if not payload.system_prompt.strip():
        raise HTTPException(status_code=400, detail="System prompt cannot be empty.")

    if count_custom_personalities() >= MAX_CUSTOM_PERSONALITIES:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum number of custom personalities reached ({MAX_CUSTOM_PERSONALITIES}).",
        )

    try:
        created = create_personality(
            name=payload.name.strip(),
            system_prompt=payload.system_prompt.strip(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PersonalityResponse(**created)

def edit_personality(
    id: int,
    payload: PersonalityUpdateRequest,
    user_data: dict = Depends(require_admin),
) -> PersonalityResponse:
    if payload.name is None and payload.system_prompt is None:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one field to update.",
        )

    if payload.name is not None and not payload.name.strip():
        raise HTTPException(status_code=400, detail="Personality name cannot be empty.")

    if payload.system_prompt is not None and not payload.system_prompt.strip():
        raise HTTPException(status_code=400, detail="System prompt cannot be empty.")

    try:
        updated = update_personality(
            personality_id=id,
            name=payload.name.strip() if payload.name is not None else None,
            system_prompt=payload.system_prompt.strip()
            if payload.system_prompt is not None
            else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if updated is None:
        raise HTTPException(status_code=404, detail="Personality not found.")

    return PersonalityResponse(**updated)


def remove_personality(
    id: int,
    user_data: dict = Depends(require_admin),
) -> dict:
    if id == STANDARD_PERSONALITY_ID:
        raise HTTPException(status_code=400, detail="The Standard personality cannot be deleted.")
    
    existing = get_personality_by_id(id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Personality not found.")

    try:
        deleted = delete_personality(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=404, detail="Personality not found.")

    return {
        "message": f"Personality {id} deleted successfully."
    }
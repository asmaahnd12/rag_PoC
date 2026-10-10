import json
import os
from typing import Optional

DATA_DIR = "data"
PERSONALITIES_FILE = os.path.join(DATA_DIR, "personalities.json")

STANDARD_PERSONALITY_ID = 0
MAX_CUSTOM_PERSONALITIES = 5


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _name_exists(data: list[dict], name: str, exclude_id: Optional[int] = None) -> bool:
    normalized = _normalize_name(name)
    for personality in data:
        current_id = personality.get("id")
        if exclude_id is not None and current_id == exclude_id:
            continue

        current_name = personality.get("name")
        if isinstance(current_name, str) and _normalize_name(current_name) == normalized:
            return True

    return False


def ensure_personalities_file() -> None:
    """
    Ensure the JSON file exists.
    The Standard personality (id=0) must already be defined in personalities.json.
    We do NOT hardcode its prompt here.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(PERSONALITIES_FILE):
        raise RuntimeError(
            f"{PERSONALITIES_FILE} not found. Create it manually with the Standard personality (id=0)."
        )

    data = load_personalities()

    if not isinstance(data, list):
        raise RuntimeError("personalities.json must contain a JSON array.")

    standard = next((p for p in data if p.get("id") == STANDARD_PERSONALITY_ID), None)
    if standard is None:
        raise RuntimeError(
            "Standard personality (id=0) is missing in personalities.json."
        )

    if not standard.get("name") or not standard.get("system_prompt"):
        raise RuntimeError(
            "Standard personality (id=0) must have both 'name' and 'system_prompt'."
        )


def load_personalities() -> list[dict]:
    with open(PERSONALITIES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("personalities.json must contain a JSON array")

    return data


def save_personalities(personalities: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PERSONALITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(personalities, f, ensure_ascii=False, indent=2)


def get_all_personalities() -> list[dict]:
    ensure_personalities_file()
    data = load_personalities()
    return sorted(data, key=lambda p: p["id"])


def get_personality_by_id(personality_id: int) -> Optional[dict]:
    ensure_personalities_file()
    data = load_personalities()
    for personality in data:
        if personality.get("id") == personality_id:
            return personality
    return None


def count_custom_personalities() -> int:
    ensure_personalities_file()
    data = load_personalities()
    return sum(1 for p in data if p.get("id") != STANDARD_PERSONALITY_ID)


def _get_next_custom_id(data: list[dict]) -> int:
    custom_ids = [
        p["id"]
        for p in data
        if isinstance(p.get("id"), int) and p["id"] > STANDARD_PERSONALITY_ID
    ]
    return (max(custom_ids) + 1) if custom_ids else 1


def create_personality(name: str, system_prompt: str) -> dict:
    ensure_personalities_file()
    data = load_personalities()

    if _name_exists(data, name):
        raise ValueError("A personality with this name already exists.")

    custom_count = sum(1 for p in data if p.get("id") != STANDARD_PERSONALITY_ID)
    if custom_count >= MAX_CUSTOM_PERSONALITIES:
        raise ValueError(
            f"Maximum number of custom personalities reached ({MAX_CUSTOM_PERSONALITIES})."
        )

    new_personality = {
        "id": _get_next_custom_id(data),
        "name": name,
        "system_prompt": system_prompt,
    }

    data.append(new_personality)
    save_personalities(data)
    return new_personality


def update_personality(
    personality_id: int,
    name: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> Optional[dict]:
    ensure_personalities_file()
    data = load_personalities()

    for personality in data:
        if personality.get("id") == personality_id:
            if name is not None:
                if _name_exists(data, name, exclude_id=personality_id):
                    raise ValueError("A personality with this name already exists.")
                personality["name"] = name
            if system_prompt is not None:
                personality["system_prompt"] = system_prompt

            save_personalities(data)
            return personality

    return None


def delete_personality(personality_id: int) -> bool:
    ensure_personalities_file()

    if personality_id == STANDARD_PERSONALITY_ID:
        raise ValueError("The Standard personality cannot be deleted.")

    data = load_personalities()
    new_data = [p for p in data if p.get("id") != personality_id]

    if len(new_data) == len(data):
        return False

    save_personalities(new_data)
    return True
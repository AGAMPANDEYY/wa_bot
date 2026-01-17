import uuid
from typing import Any, Dict, List, Optional, Tuple

import dateparser

from db import (
    add_reminder,
    get_preferences,
    latest_active_reminder,
    list_reminders,
    log_event,
    mark_done,
    search_archive,
    set_preference,
    update_reminder,
)


def parse_due_at(text: str, timezone: str) -> Tuple[Optional[str], Optional[int]]:
    settings = {
        "TIMEZONE": timezone,
        "RETURN_AS_TIMEZONE_AWARE": True,
    }
    parsed = dateparser.parse(text, settings=settings)
    if not parsed:
        return None, None
    return parsed.isoformat(), int(parsed.timestamp())


def create_reminder_tool(
    db_path: str,
    user_id: str,
    title: str,
    due_text: str,
    timezone: str,
    source_text: str,
) -> Dict[str, Any]:
    due_at, due_epoch = parse_due_at(due_text, timezone)
    reminder_id = str(uuid.uuid4())
    result = add_reminder(
        db_path,
        reminder_id,
        user_id,
        title,
        due_at,
        due_epoch,
        timezone,
        source_text,
    )
    log_event(
        db_path,
        user_id,
        "create_reminder",
        {"reminder_id": reminder_id, "title": title, "due_at": due_at},
    )
    return {
        "reminder_id": reminder_id,
        "title": title,
        "due_at": due_at,
        "timezone": timezone,
    }


def update_reminder_tool(
    db_path: str,
    user_id: str,
    reminder_id: str,
    due_text: str,
    timezone: str,
) -> Dict[str, Any]:
    due_at, due_epoch = parse_due_at(due_text, timezone)
    update_reminder(db_path, reminder_id, due_at, due_epoch, timezone)
    log_event(
        db_path,
        user_id,
        "update_reminder",
        {"reminder_id": reminder_id, "due_at": due_at},
    )
    return {"reminder_id": reminder_id, "due_at": due_at}


def mark_done_tool(db_path: str, user_id: str, reminder_id: str) -> Dict[str, Any]:
    mark_done(db_path, reminder_id)
    log_event(db_path, user_id, "mark_done", {"reminder_id": reminder_id})
    return {"reminder_id": reminder_id}


def list_reminders_tool(
    db_path: str, user_id: str, limit: int = 5
) -> List[Dict[str, Any]]:
    items = list_reminders(db_path, user_id, status="active", limit=limit)
    log_event(db_path, user_id, "list_reminders", {"count": len(items)})
    return items


def search_archive_tool(
    db_path: str, user_id: str, query_text: str, limit: int = 5
) -> List[Dict[str, Any]]:
    items = search_archive(db_path, user_id, query_text, limit=limit)
    log_event(db_path, user_id, "search_archive", {"count": len(items)})
    return items


def set_preference_tool(db_path: str, user_id: str, key: str, value: str) -> Dict[str, Any]:
    result = set_preference(db_path, user_id, key, value)
    log_event(db_path, user_id, "set_preference", result)
    return result


def get_preferences_tool(db_path: str, user_id: str) -> Dict[str, str]:
    prefs = get_preferences(db_path, user_id)
    log_event(db_path, user_id, "get_preferences", {"keys": list(prefs.keys())})
    return prefs


def resolve_reminder_id(db_path: str, user_id: str, ids: List[str]) -> Optional[str]:
    if ids:
        return ids[0]
    latest = latest_active_reminder(db_path, user_id)
    return latest["reminder_id"] if latest else None

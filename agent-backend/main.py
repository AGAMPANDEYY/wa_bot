import os
import json
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, Form, Header, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import anthropic
from mem0 import MemoryClient
import dateparser
from dateparser.search import search_dates
import hmac
import hashlib
import asyncio
import threading
import re
import html

from db import Database
from mem0_store import Mem0Store

from dotenv import load_dotenv

load_dotenv()

# Environment variables
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")
MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "512"))
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
DB_PATH = os.getenv("DB_PATH", "data.db")
CONVO_WINDOW = int(os.getenv("CONVO_WINDOW", "6"))
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_API_BASE = "https://slack.com/api"
SLACK_NOTIFY_ENABLED = os.getenv("SLACK_NOTIFY_ENABLED", "1").lower() in ("1", "true", "yes", "on")
SLACK_NOTIFY_INTERVAL_SECONDS = int(os.getenv("SLACK_NOTIFY_INTERVAL_SECONDS", "60"))
BACKGROUND_MEM0_WRITES = os.getenv("BACKGROUND_MEM0_WRITES", "1").lower() in ("1", "true", "yes", "on")
DEBUG_SYSTEM_PROMPT = os.getenv("DEBUG_SYSTEM_PROMPT", "0").lower() in ("1", "true", "yes", "on")
SYSTEM_PROMPT_LOG_PATH = os.getenv("SYSTEM_PROMPT_LOG_PATH", "")
MEM0_CONTEXT_TTL_SECONDS = int(os.getenv("MEM0_CONTEXT_TTL_SECONDS", "120"))
ARCHIVE_CRON_TOKEN = os.getenv("ARCHIVE_CRON_TOKEN", "")

# Initialize
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize DB lazily (don't fail if locked)
db = None
try:
    db = Database(DB_PATH)
except Exception as e:
    print(f"Warning: Database initialization failed: {e}")
    print("Running in Mem0-only mode")

mem0_store = Mem0Store()
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Store debug info per request
debug_context = {
    "mem0_queries": [],
    "tool_calls": [],
    "db_changes": [],
    "webhook_events": [],
    "behavior": [],
    "retrieved_memories": {}
}

pending_actions = {}
slack_event_cache = {}
slack_user_channels = {}
user_time_context = {}
mem0_context_cache = {}

def _get_cached_mem0_context(user_id: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    if db:
        try:
            row = db.get_mem0_cache(user_id)
            if row and row.get("updated_at"):
                if (now - row["updated_at"]) <= MEM0_CONTEXT_TTL_SECONDS:
                    payload = json.loads(row.get("payload") or "{}")
                    return payload
        except Exception:
            pass
    cached = mem0_context_cache.get(user_id)
    if not cached:
        return None
    if (now - cached["ts"]) > MEM0_CONTEXT_TTL_SECONDS:
        mem0_context_cache.pop(user_id, None)
        return None
    return cached["data"]

def _set_cached_mem0_context(user_id: str, data: Dict[str, Any]):
    mem0_context_cache[user_id] = {"ts": time.time(), "data": data}
    if db:
        try:
            db.set_mem0_cache(user_id, json.dumps(data))
        except Exception:
            pass

def _invalidate_mem0_context_cache(user_id: str):
    mem0_context_cache.pop(user_id, None)
    if db:
        try:
            db.set_mem0_cache(user_id, json.dumps({}))
        except Exception:
            pass

def sanitize_slack_text(text: str) -> str:
    """Normalize Slack markup into plain text for NLP parsing."""
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = re.sub(r"<@([A-Z0-9]+)>", r"@\1", cleaned)
    cleaned = re.sub(r"<#([A-Z0-9]+)\|([^>]+)>", r"#\2", cleaned)
    cleaned = re.sub(r"<([^>|]+)\|([^>]+)>", r"\2", cleaned)
    cleaned = re.sub(r"<([^>]+)>", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def _reminder_value(reminder: Any, key: str, index: Optional[int] = None):
    if isinstance(reminder, dict):
        return reminder.get(key)
    try:
        return reminder[key]
    except Exception:
        if index is not None:
            try:
                return reminder[index]
            except Exception:
                return None
        return None

def reset_debug_context():
    """Reset debug context for new request"""
    debug_context["mem0_queries"] = []
    debug_context["tool_calls"] = []
    debug_context["db_changes"] = []
    debug_context["behavior"] = []
    debug_context["retrieved_memories"] = {}

# Tool definitions for Claude
TOOLS = [
    {
        "name": "create_reminder",
        "description": "Create a new reminder with title, optional description, and due date/time. Parse natural language dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Reminder title"},
                "description": {"type": "string", "description": "Optional reminder description"},
                "due_str": {"type": "string", "description": "Natural language date/time (e.g., 'tomorrow 3pm', 'next Monday')"}
            },
            "required": ["title", "due_str"]
        }
    },
    {
        "name": "update_reminder",
        "description": "Update an existing reminder's title, description, or due date",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer", "description": "Reminder ID to update"},
                "title": {"type": "string", "description": "New title (optional)"},
                "description": {"type": "string", "description": "New description (optional)"},
                "due_str": {"type": "string", "description": "New due date in natural language (optional)"}
            },
            "required": ["reminder_id"]
        }
    },
    {
        "name": "mark_done",
        "description": "Mark a reminder as completed",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer", "description": "Reminder ID to mark as done"}
            },
            "required": ["reminder_id"]
        }
    },
    {
        "name": "snooze_reminder",
        "description": "Snooze a reminder to a new time",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer", "description": "Reminder ID to snooze"},
                "snooze_str": {"type": "string", "description": "Snooze duration or time (e.g., '30 minutes', 'tomorrow 9am')"}
            },
            "required": ["reminder_id", "snooze_str"]
        }
    },
    {
        "name": "list_reminders",
        "description": "List reminders. Use status='active' for upcoming, status='completed' for archived, status='all' for everything.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "completed", "all"], "description": "Filter by status"}
            }
        }
    },
    {
        "name": "search_reminders",
        "description": "Search reminders by keyword in title or description",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "delete_reminder",
        "description": "Delete a reminder permanently (use only when user explicitly requests deletion)",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer", "description": "Reminder ID to delete"}
            },
            "required": ["reminder_id"]
        }
    },
    {
        "name": "set_preference",
        "description": "Set or update user preferences (timezone, notification settings, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Preference key (e.g., 'timezone', 'default_reminder_time')"},
                "value": {"type": "string", "description": "Preference value"}
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "get_preferences",
        "description": "Get all user preferences",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_rescheduled_reminders",
        "description": "List active reminders that were rescheduled (snoozed or due date changed)",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "clarify_reminder",
        "description": "When multiple reminders match, ask user to clarify which one",
        "input_schema": {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of matching reminders"
                },
                "question": {"type": "string", "description": "Clarification question to ask user"}
            },
            "required": ["matches", "question"]
        }
    }
]

# Tool execution functions
def update_behavior_memory(user_id: str):
    stats = db.get_behavior_stats(user_id)
    if not stats:
        return None
    total_events = stats["create_count"] + stats["update_count"] + stats["snooze_count"] + stats["done_count"]
    if total_events == 0:
        return None
    summary = (
        "Behavior summary: "
        f"created {stats['create_count']} reminders, "
        f"updated {stats['update_count']} times, "
        f"snoozed {stats['snooze_count']} times (avg {stats['avg_snooze_minutes']} min), "
        f"completed {stats['done_count']} reminders (avg {stats['avg_complete_minutes']} min after creation)."
    )
    mem0_id = mem0_store.upsert_behavior_summary(
        summary,
        user_id=user_id,
        metadata={
            "create_count": stats["create_count"],
            "update_count": stats["update_count"],
            "snooze_count": stats["snooze_count"],
            "avg_snooze_minutes": stats["avg_snooze_minutes"],
            "done_count": stats["done_count"],
            "avg_complete_minutes": stats["avg_complete_minutes"],
        }
    )
    debug_context["behavior"].append({
        "summary": summary,
        "mem0_id": mem0_id
    })
    return mem0_id

def parse_datetime(date_str: str, timezone_str: str = DEFAULT_TIMEZONE) -> Optional[int]:
    """Parse natural language date to epoch timestamp"""
    settings = {
        "TIMEZONE": timezone_str,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
    }
    try:
        dt = dateparser.parse(date_str, settings=settings)
        if dt:
            return int(dt.timestamp())
    except Exception as e:
        debug_context["tool_calls"].append({"error": f"Date parse failed (tz): {str(e)}"})

    try:
        matches = search_dates(date_str, settings=settings)
        if matches:
            return int(matches[0][1].timestamp())
    except Exception as e:
        debug_context["tool_calls"].append({"error": f"Date search failed (tz): {str(e)}"})

    try:
        dt = dateparser.parse(date_str)
        if dt:
            return int(dt.timestamp())
    except Exception as e:
        debug_context["tool_calls"].append({"error": f"Date parse failed (fallback): {str(e)}"})

    try:
        matches = search_dates(date_str)
        if matches:
            return int(matches[0][1].timestamp())
    except Exception as e:
        debug_context["tool_calls"].append({"error": f"Date search failed (fallback): {str(e)}"})

    try:
        dt = datetime.fromisoformat(date_str)
        return int(dt.timestamp())
    except Exception:
        return None

def format_day_ordinal(day: int) -> str:
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"

def format_due_datetime(epoch: Optional[int]) -> str:
    if not epoch:
        return "N/A"
    dt = datetime.fromtimestamp(int(epoch))
    day = format_day_ordinal(dt.day)
    time_label = dt.strftime("%I:%M %p").lstrip("0")
    return f"{day} {dt.strftime('%b')}, {time_label}"

def message_mentions_time(text: str) -> bool:
    lowered = text.lower()
    time_words = [
        "am",
        "pm",
        "noon",
        "midnight",
        "morning",
        "afternoon",
        "evening",
        "min",
        "mins",
        "minute",
        "minutes",
        "hour",
        "hours",
    ]
    if any(word in lowered for word in time_words):
        return True
    return bool(
        any(char.isdigit() for char in text)
        and (":" in text or "am" in lowered or "pm" in lowered)
    )

def is_confirmation(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered in {"yes", "yep", "yeah", "y", "ok", "okay", "sure", "confirm", "correct", "that works"}

def is_rejection(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered in {"no", "nope", "nah", "cancel"}

def verify_slack_signature(signature: str, timestamp: str, body: bytes) -> bool:
    if not SLACK_SIGNING_SECRET:
        return False
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(
        SLACK_SIGNING_SECRET.encode("utf-8"),
        basestring,
        hashlib.sha256
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature or "")

def is_duplicate_slack_event(event_id: str, ttl_seconds: int = 300) -> bool:
    now = int(time.time())
    if not event_id:
        return False
    last_seen = slack_event_cache.get(event_id)
    if last_seen and now - last_seen < ttl_seconds:
        return True
    slack_event_cache[event_id] = now
    # Prune old entries
    stale = [eid for eid, ts in slack_event_cache.items() if now - ts > ttl_seconds]
    for eid in stale:
        slack_event_cache.pop(eid, None)
    return False

def run_in_background(target, *args, **kwargs):
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()

def background_update_behavior(user_id: str):
    try:
        update_behavior_memory(user_id)
        _invalidate_mem0_context_cache(user_id)
    except Exception:
        pass

def background_upsert_active(reminder_id: int, user_id: str, text: str, metadata: Dict[str, Any]):
    try:
        mem0_id = mem0_store.upsert_active_reminder(text, user_id=user_id, metadata=metadata)
        if mem0_id:
            db.update_reminder_mem0_id(reminder_id, user_id, mem0_id)
        _invalidate_mem0_context_cache(user_id)
    except Exception:
        pass

def background_upsert_archived(reminder_id: int, user_id: str, text: str, metadata: Dict[str, Any], active_mem0_id: Optional[str]):
    try:
        if active_mem0_id:
            mem0_store.delete_memory(active_mem0_id)
        mem0_id = mem0_store.upsert_archived_reminder(text, user_id=user_id, metadata=metadata)
        if mem0_id:
            db.update_reminder_mem0_id(reminder_id, user_id, mem0_id)
        _invalidate_mem0_context_cache(user_id)
    except Exception:
        pass

def background_upsert_preference(user_id: str, text: str, metadata: Dict[str, Any]):
    try:
        mem0_store.upsert_preference(text, user_id=user_id, metadata=metadata)
        _invalidate_mem0_context_cache(user_id)
    except Exception:
        pass

def build_slack_reminder_blocks(title: str, due_label: str, reminder_id: int) -> List[Dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*\nDue {due_label}"}
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done"},
                    "style": "primary",
                    "action_id": "reminder_done",
                    "value": str(reminder_id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Snooze 10m"},
                    "action_id": "reminder_snooze_10m",
                    "value": str(reminder_id),
                },
            ],
        },
    ]

def send_slack_due_notifications(user_id: str = None) -> int:
    if not db or not SLACK_BOT_TOKEN:
        return 0

    targets = {}
    if user_id:
        channel = slack_user_channels.get(user_id)
        if channel:
            targets[user_id] = channel
    else:
        targets = dict(slack_user_channels)

    sent = 0
    for slack_user_id, channel in targets.items():
        due_soon = db.get_due_soon_reminders(slack_user_id, int(time.time()), lead_time_seconds=600)
        for reminder in due_soon:
            reminder_id = reminder["id"]
            due_at = reminder["due_at_epoch"]
            title = reminder["title"]
            due_label = datetime.fromtimestamp(due_at).strftime("%b %d %I:%M %p")
            blocks = build_slack_reminder_blocks(title, due_label, reminder_id)
            try:
                import requests
                requests.post(
                    f"{SLACK_API_BASE}/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json={"channel": channel, "text": f"Reminder: {title}", "blocks": blocks},
                    timeout=10,
                )
                db.mark_reminder_notified(reminder_id, slack_user_id, int(time.time()))
                sent += 1
            except Exception:
                pass

    return sent

def parse_selection_index(text: str) -> Optional[int]:
    lowered = text.strip().lower()
    if lowered in {"first", "1", "one"}:
        return 0
    if lowered in {"second", "2", "two"}:
        return 1
    if lowered in {"third", "3", "three"}:
        return 2
    return None

def infer_category(title: str, description: str = "") -> str:
    text = f"{title} {description}".lower()
    if any(word in text for word in ["mom", "dad", "family", "parent", "sister", "brother"]):
        return "family"
    if any(word in text for word in ["meeting", "call", "client", "deck", "review", "office", "report"]):
        return "work"
    if any(word in text for word in ["doctor", "dentist", "med", "health", "appointment", "therapy"]):
        return "health"
    if any(word in text for word in ["bill", "rent", "payment", "invoice", "tax", "bank"]):
        return "finance"
    return "personal"

def normalize_title(text: str) -> str:
    cleaned = "".join(ch.lower() for ch in text if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.split())

def find_existing_active_reminder(user_id: str, title: str):
    if not db:
        return None
    try:
        reminders = db.list_active_reminders(user_id)
    except Exception:
        return None
    target = normalize_title(title)
    matches = []
    for r in reminders:
        existing_title = _reminder_value(r, "title", 2) or ""
        if normalize_title(existing_title) == target:
            matches.append(r)
    if not matches:
        return None
    # Prefer most recently updated
    matches.sort(key=lambda r: _reminder_value(r, "updated_at", 8) or 0, reverse=True)
    return matches[0]

def _mem0_time_key_to_category(key: str) -> Optional[str]:
    if not key:
        return None
    normalized = key.strip().lower()
    if normalized in {"default_time", "default_reminder_time", "reminder_time"}:
        return "default"
    for prefix in ("reminder_time:", "reminder_time_", "default_time:"):
        if normalized.startswith(prefix):
            return normalized.replace(prefix, "").strip() or None
    return None

def get_mem0_time_preferences(user_id: str) -> Dict[str, str]:
    """Read time preferences from Mem0 user_prefs."""
    try:
        memories = mem0_store.get_all_memories(
            user_id=user_id,
            categories=[mem0_store.CAT_USER_PREFS]
        )
    except Exception:
        return {}
    prefs: Dict[str, str] = {}
    for mem in memories:
        metadata = mem.get("metadata", {}) or {}
        key = metadata.get("pref_key")
        value = metadata.get("pref_value")
        if not key or not value:
            continue
        category = _mem0_time_key_to_category(key)
        if category:
            prefs[category] = str(value).strip()
    return prefs

def get_common_times_by_category(user_id: str) -> Dict[str, str]:
    mem0_times = get_mem0_time_preferences(user_id)
    if not db:
        return mem0_times
    try:
        rows = db.list_reminder_times_by_category(user_id)
    except Exception:
        return mem0_times
    buckets = {}
    for row in rows:
        category = row["category"] if isinstance(row, dict) else row[0]
        due_at_epoch = row["due_at_epoch"] if isinstance(row, dict) else row[1]
        if not category or not due_at_epoch:
            continue
        dt = datetime.fromtimestamp(int(due_at_epoch))
        key = f"{dt.hour:02d}:{dt.minute:02d}"
        buckets.setdefault(category, {})
        buckets[category][key] = buckets[category].get(key, 0) + 1
    common = dict(mem0_times)
    for category, times in buckets.items():
        if category in common:
            continue
        common_time = max(times.items(), key=lambda item: item[1])[0]
        common[category] = common_time
    return common

def format_time_12h(time_24h: str) -> str:
    try:
        hour_str, minute_str = time_24h.split(":")
        dt = datetime.now().replace(hour=int(hour_str), minute=int(minute_str), second=0, microsecond=0)
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_24h

def execute_create_reminder(
    user_id: str,
    title: str,
    due_str: str,
    description: str = "",
    allow_unconfirmed: bool = False,
) -> Dict[str, Any]:
    """Create a new reminder"""
    if not allow_unconfirmed:
        context = user_time_context.get(user_id, {})
        if context and not context.get("has_time"):
            category = infer_category(title, description)
            common_times = get_common_times_by_category(user_id)
            suggested_time = common_times.get(category)
            pending_actions[user_id] = {
                "type": "confirm_time",
                "title": title,
                "description": description,
                "due_str": due_str,
                "category": category,
                "suggested_time": suggested_time,
            }
            if suggested_time:
                prompt = (
                    f"I usually schedule {category} reminders at "
                    f"{format_time_12h(suggested_time)}. Would you like me to use that time?"
                )
            else:
                prompt = "What time should I set this reminder for?"
            return {
                "success": False,
                "error": "Time confirmation needed",
                "pending": pending_actions[user_id],
                "prompt": prompt,
            }
    due_epoch = parse_datetime(due_str)
    if not due_epoch:
        return {"success": False, "error": "Could not parse date"}

    existing = find_existing_active_reminder(user_id, title)
    if existing:
        reminder_id = _reminder_value(existing, "id", 0)
        result = execute_update_reminder(
            user_id=user_id,
            reminder_id=reminder_id,
            due_str=due_str
        )
        if result.get("success"):
            result["message"] = f"Updated reminder '{title}' to {due_str}"
        return result

    category = infer_category(title, description)
    reminder_id = db.create_reminder(user_id, title, description, due_epoch, category=category)
    db.record_behavior_create(user_id)
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_update_behavior, user_id)
    else:
        update_behavior_memory(user_id)

    mem0_text = f"Reminder: {title}. Due: {due_str}. Description: {description}"
    metadata = {
        "reminder_id": reminder_id,
        "title": title,
        "description": description,
        "due_at_epoch": due_epoch,
        "status": "active",
        "reschedule_count": 0,
        "category": category
    }
    mem0_id = None
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_upsert_active, reminder_id, user_id, mem0_text, metadata)
    else:
        mem0_id = mem0_store.upsert_active_reminder(
            mem0_text,
            user_id=user_id,
            metadata=metadata
        )
        if mem0_id:
            db.update_reminder_mem0_id(reminder_id, user_id, mem0_id)
        _invalidate_mem0_context_cache(user_id)

    debug_context["db_changes"].append({
        "action": "create_reminder",
        "reminder_id": reminder_id,
        "mem0_id": mem0_id
    })

    return {
        "success": True,
        "due_epoch": due_epoch,
        "message": f"Reminder '{title}' created for {due_str}"
    }

def execute_update_reminder(user_id: str, reminder_id: int, title: str = None, description: str = None, due_str: str = None) -> Dict[str, Any]:
    """Update an existing reminder"""
    reminder = db.get_reminder(reminder_id, user_id)
    if not reminder:
        return {"success": False, "error": f"Reminder {reminder_id} not found"}

    updates = {}
    rescheduled = False
    if title:
        updates["title"] = title
    if description is not None:
        updates["description"] = description
    if title or description is not None:
        current_title = title or _reminder_value(reminder, "title", 2) or ""
        current_desc = description if description is not None else _reminder_value(reminder, "description", 3) or ""
        updates["category"] = infer_category(current_title, current_desc)
    if due_str:
        due_epoch = parse_datetime(due_str)
        if not due_epoch:
            pending_actions[user_id] = {
                "type": "update_due",
                "reminder_id": reminder_id,
                "due_str": due_str,
                "title": _reminder_value(reminder, "title", 2),
            }
            return {"success": False, "error": "Could not parse date", "pending": pending_actions[user_id]}
        updates["due_at_epoch"] = due_epoch
        rescheduled = True

    db.update_reminder(reminder_id, user_id, rescheduled=rescheduled, **updates)
    db.record_behavior_update(user_id)
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_update_behavior, user_id)
    else:
        update_behavior_memory(user_id)

    new_title = title or _reminder_value(reminder, "title", 2)
    new_desc = description if description is not None else _reminder_value(reminder, "description", 3)
    new_due_epoch = updates.get("due_at_epoch", _reminder_value(reminder, "due_at_epoch", 4))
    due_formatted = datetime.fromtimestamp(new_due_epoch).strftime("%Y-%m-%d %H:%M")
    current_reschedule_count = _reminder_value(reminder, "reschedule_count", 10) or 0
    reschedule_count = current_reschedule_count + 1 if rescheduled else current_reschedule_count
    last_rescheduled_at_epoch = int(time.time()) if rescheduled else _reminder_value(reminder, "last_rescheduled_at", 11)

    mem0_text = f"Reminder: {new_title}. Due: {due_formatted}. Description: {new_desc}"
    metadata = {
        "reminder_id": reminder_id,
        "title": new_title,
        "description": new_desc,
        "due_at_epoch": new_due_epoch,
        "status": "active",
        "reschedule_count": reschedule_count,
        "last_rescheduled_at_epoch": last_rescheduled_at_epoch,
        "category": updates.get("category", _reminder_value(reminder, "category", 6))
    }
    mem0_id = None
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_upsert_active, reminder_id, user_id, mem0_text, metadata)
    else:
        mem0_id = mem0_store.upsert_active_reminder(
            mem0_text,
            user_id=user_id,
            metadata=metadata
        )
        if mem0_id:
            db.update_reminder_mem0_id(reminder_id, user_id, mem0_id)
        _invalidate_mem0_context_cache(user_id)

    debug_context["db_changes"].append({
        "action": "update_reminder",
        "reminder_id": reminder_id,
        "mem0_id": mem0_id,
        "updates": updates
    })

    return {"success": True, "message": f"Reminder '{new_title}' updated"}


def execute_mark_done(user_id: str, reminder_id: int) -> Dict[str, Any]:
    """Mark reminder as completed"""
    reminder = db.get_reminder(reminder_id, user_id)
    if not reminder:
        return {"success": False, "error": f"Reminder {reminder_id} not found"}

    db.mark_reminder_done(reminder_id, user_id)
    created_at = _reminder_value(reminder, "created_at", 6)
    minutes_to_complete = max(0, int((time.time() - created_at) / 60))
    db.record_behavior_done(user_id, minutes_to_complete)
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_update_behavior, user_id)
    else:
        update_behavior_memory(user_id)

    title = _reminder_value(reminder, "title", 2)
    description = _reminder_value(reminder, "description", 3)
    category = _reminder_value(reminder, "category", 6)
    due_at_epoch = _reminder_value(reminder, "due_at_epoch", 4)
    due_formatted = datetime.fromtimestamp(due_at_epoch).strftime("%Y-%m-%d %H:%M") if due_at_epoch else "N/A"
    reschedule_count = _reminder_value(reminder, "reschedule_count", 10) or 0
    last_rescheduled_at_epoch = _reminder_value(reminder, "last_rescheduled_at", 11)
    mem0_text = f"Completed reminder: {title}. Due: {due_formatted}. Description: {description}"
    mem0_active_id = _reminder_value(reminder, "mem0_memory_id", 7)
    metadata = {
        "reminder_id": reminder_id,
        "title": title,
        "description": description,
        "due_at_epoch": due_at_epoch,
        "status": "completed",
        "reschedule_count": reschedule_count,
        "last_rescheduled_at_epoch": last_rescheduled_at_epoch,
        "category": category
    }
    mem0_id = None
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_upsert_archived, reminder_id, user_id, mem0_text, metadata, mem0_active_id)
    else:
        if mem0_active_id:
            mem0_store.delete_memory(mem0_active_id)
        mem0_id = mem0_store.upsert_archived_reminder(
            mem0_text,
            user_id=user_id,
            metadata=metadata
        )
        if mem0_id:
            db.update_reminder_mem0_id(reminder_id, user_id, mem0_id)
        _invalidate_mem0_context_cache(user_id)

    debug_context["db_changes"].append({
        "action": "mark_done",
        "reminder_id": reminder_id,
        "mem0_id": mem0_id
    })

    return {"success": True, "message": f"Reminder '{title}' marked as done"}


def execute_snooze_reminder(user_id: str, reminder_id: int, snooze_str: str) -> Dict[str, Any]:
    """Snooze a reminder"""
    reminder = db.get_reminder(reminder_id, user_id)
    if not reminder:
        return {"success": False, "error": f"Reminder {reminder_id} not found"}

    new_due = parse_datetime(snooze_str)
    if not new_due:
        return {"success": False, "error": "Could not parse snooze time"}

    db.update_reminder(reminder_id, user_id, due_at_epoch=new_due, rescheduled=True)
    old_due = _reminder_value(reminder, "due_at_epoch", 4)
    delta_minutes = max(0, int((new_due - old_due) / 60))
    db.record_behavior_snooze(user_id, delta_minutes)
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_update_behavior, user_id)
    else:
        update_behavior_memory(user_id)

    title = _reminder_value(reminder, "title", 2)
    description = _reminder_value(reminder, "description", 3)
    category = _reminder_value(reminder, "category", 6)
    due_formatted = datetime.fromtimestamp(new_due).strftime("%Y-%m-%d %H:%M")
    current_reschedule_count = _reminder_value(reminder, "reschedule_count", 10) or 0
    reschedule_count = current_reschedule_count + 1
    last_rescheduled_at_epoch = int(time.time())
    mem0_text = f"Reminder: {title}. Due: {due_formatted}. Description: {description}"
    metadata = {
        "reminder_id": reminder_id,
        "title": title,
        "description": description,
        "due_at_epoch": new_due,
        "status": "active",
        "reschedule_count": reschedule_count,
        "last_rescheduled_at_epoch": last_rescheduled_at_epoch,
        "category": category
    }
    mem0_id = None
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_upsert_active, reminder_id, user_id, mem0_text, metadata)
    else:
        mem0_id = mem0_store.upsert_active_reminder(
            mem0_text,
            user_id=user_id,
            metadata=metadata
        )
        if mem0_id:
            db.update_reminder_mem0_id(reminder_id, user_id, mem0_id)

    debug_context["db_changes"].append({
        "action": "snooze_reminder",
        "reminder_id": reminder_id,
        "new_due": new_due,
        "mem0_id": mem0_id
    })

    return {"success": True, "message": f"Reminder snoozed to {snooze_str}"}


def execute_list_reminders(user_id: str, status: str = "active") -> Dict[str, Any]:
    """List reminders by status using DB as source of truth."""
    formatted: List[Dict[str, Any]] = []
    try:
        if status == "active":
            reminders = db.list_active_reminders(user_id)
        elif status == "completed":
            reminders = db.list_completed_reminders(user_id)
        elif status == "rescheduled":
            reminders = db.list_rescheduled_reminders(user_id)
        else:
            reminders = db.list_all_reminders(user_id)

        for r in reminders:
            due_epoch = _reminder_value(r, "due_at_epoch", 4)
            formatted.append({
                "id": _reminder_value(r, "id", 0),
                "title": _reminder_value(r, "title", 2),
                "description": _reminder_value(r, "description", 3),
                "due_at_epoch": due_epoch,
                "due_at": format_due_datetime(due_epoch),
                "status": _reminder_value(r, "status", 5),
                "category": _reminder_value(r, "category", 6),
                "reschedule_count": _reminder_value(r, "reschedule_count", 10),
                "last_rescheduled_at": _reminder_value(r, "last_rescheduled_at", 11),
            })
    except Exception:
        pass  # DB might be unavailable temporarily
    
    def build_summary(items: List[Dict[str, Any]]) -> str:
        if not items:
            return "No reminders found."
        grouped = {"active": [], "completed": [], "other": []}
        for item in items:
            state = item.get("status", "active")
            if state not in grouped:
                grouped["other"].append(item)
            else:
                grouped[state].append(item)
        total = len(items)
        def format_group(title: str, entries: List[Dict[str, Any]]) -> str:
            if not entries:
                return ""
            counts = {}
            for entry in entries:
                key = (entry.get("title", "").strip(), entry.get("due_at", ""))
                counts[key] = counts.get(key, 0) + 1
            lines = [f"{title} ({len(entries)})"]
            for (title_text, due_at), count in counts.items():
                suffix = f" ×{count}" if count > 1 else ""
                due = f" — {due_at}" if due_at else ""
                lines.append(f"• {title_text}{due}{suffix}")
            return "\n".join(lines)
        rescheduled = [item for item in grouped["active"] if item.get("reschedule_count", 0)]
        upcoming = [item for item in grouped["active"] if not item.get("reschedule_count", 0)]
        sections = [
            format_group("Snoozed/Rescheduled", rescheduled),
            format_group("Upcoming", upcoming),
            format_group("Archived", grouped["completed"]),
            format_group("Other", grouped["other"]),
        ]
        header = f"Here’s your reminders overview ({total} total)"
        body = "\n\n".join(section for section in sections if section)
        if not body:
            return header
        return f"{header}\n\n{body}"

    summary = build_summary(formatted)
    return {"success": True, "reminders": formatted, "count": len(formatted), "summary": summary}

def execute_search_reminders(user_id: str, query: str) -> Dict[str, Any]:
    """Search reminders"""
    reminders = db.search_reminders(user_id, query)
    
    formatted = []
    for r in reminders:
        formatted.append({
            "id": _reminder_value(r, "id", 0),
            "title": _reminder_value(r, "title", 2),
            "description": _reminder_value(r, "description", 3),
            "due_at": format_due_datetime(_reminder_value(r, "due_at_epoch", 4)),
            "status": _reminder_value(r, "status", 5),
            "category": _reminder_value(r, "category", 6)
        })
    
    return {"success": True, "reminders": formatted, "count": len(formatted)}

def execute_delete_reminder(user_id: str, reminder_id: int) -> Dict[str, Any]:
    """Delete a reminder permanently"""
    reminder = db.get_reminder(reminder_id, user_id)
    if not reminder:
        return {"success": False, "error": f"Reminder {reminder_id} not found"}

    mem0_id = _reminder_value(reminder, "mem0_memory_id", 7)
    db.delete_reminder(reminder_id, user_id)
    if mem0_id:
        mem0_store.delete_memory(mem0_id)

    debug_context["db_changes"].append({
        "action": "delete_reminder",
        "reminder_id": reminder_id
    })

    return {"success": True, "message": f"Reminder {reminder_id} deleted"}


def execute_set_preference(user_id: str, key: str, value: str) -> Dict[str, Any]:
    """Set user preference - Mem0 only"""
    
    # Update Mem0
    mem0_text = f"User preference: {key} = {value}"
    mem0_id = None
    if BACKGROUND_MEM0_WRITES:
        run_in_background(background_upsert_preference, user_id, mem0_text, {"pref_key": key, "pref_value": value})
    else:
        mem0_id = mem0_store.upsert_preference(
            mem0_text,
            metadata={"pref_key": key, "pref_value": value}
        )
        _invalidate_mem0_context_cache(user_id)
    
    debug_context["db_changes"].append({
        "action": "set_preference",
        "key": key,
        "value": value,
        "mem0_id": mem0_id
    })
    
    return {"success": True, "message": f"Preference '{key}' set to '{value}'"}

def execute_get_preferences(user_id: str) -> Dict[str, Any]:
    """Get all preferences - Mem0 only"""
    
    # Get from Mem0
    memories = mem0_store.get_all_memories(
        user_id=user_id,
        categories=[mem0_store.CAT_USER_PREFS]
    )
    
    prefs = {}
    for mem in memories:
        metadata = mem.get("metadata", {})
        key = metadata.get("pref_key")
        value = metadata.get("pref_value")
        if key:
            prefs[key] = value
    
    return {"success": True, "preferences": prefs}

def execute_clarify_reminder(user_id: str, matches: List[Dict[str, Any]], question: str) -> Dict[str, Any]:
    """Store clarify context and return a question for the user"""
    pending_actions[user_id] = {
        "type": "clarify_reminder",
        "matches": matches,
        "question": question
    }
    return {"success": True, "question": question, "matches": matches}

def execute_list_rescheduled_reminders(user_id: str) -> Dict[str, Any]:
    """List active reminders that have been rescheduled at least once"""
    memories = mem0_store.get_rescheduled_active_reminders(user_id=user_id, limit=50)
    formatted = []
    for mem in memories:
        metadata = mem.get("metadata", {})
        formatted.append({
            "id": metadata.get("reminder_id", mem.get("id")),
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "due_at": format_due_datetime(metadata.get("due_at_epoch")),
            "status": metadata.get("status", "active"),
            "reschedule_count": metadata.get("reschedule_count", 0),
            "last_rescheduled_at_epoch": metadata.get("last_rescheduled_at_epoch")
        })

    if not formatted and db:
        try:
            reminders = db.list_rescheduled_reminders(user_id)
            for r in reminders:
                formatted.append({
                    "id": _reminder_value(r, "id", 0),
                    "title": _reminder_value(r, "title", 2),
                    "description": _reminder_value(r, "description", 3),
                    "due_at": format_due_datetime(_reminder_value(r, "due_at_epoch", 4)),
                    "status": _reminder_value(r, "status", 5),
                    "reschedule_count": _reminder_value(r, "reschedule_count", 10) or 0,
                    "last_rescheduled_at_epoch": _reminder_value(r, "last_rescheduled_at", 11)
                })
        except:
            pass

    return {"success": True, "reminders": formatted, "count": len(formatted)}

# Tool router
TOOL_EXECUTORS = {
    "create_reminder": execute_create_reminder,
    "update_reminder": execute_update_reminder,
    "mark_done": execute_mark_done,
    "snooze_reminder": execute_snooze_reminder,
    "list_reminders": execute_list_reminders,
    "search_reminders": execute_search_reminders,
    "delete_reminder": execute_delete_reminder,
    "set_preference": execute_set_preference,
    "get_preferences": execute_get_preferences,
    "list_rescheduled_reminders": execute_list_rescheduled_reminders,
    "clarify_reminder": execute_clarify_reminder
}

def execute_tool(tool_name: str, tool_input: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Execute a tool and return result"""
    debug_context["tool_calls"].append({
        "tool": tool_name,
        "input": tool_input,
        "timestamp": time.time()
    })
    
    executor = TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    
    try:
        result = executor(user_id=user_id, **tool_input)
        debug_context["tool_calls"][-1]["result"] = result
        return result
    except Exception as e:
        error_result = {"success": False, "error": str(e)}
        debug_context["tool_calls"][-1]["result"] = error_result
        return error_result

def should_skip_mem0_prefetch(user_message: str) -> bool:
    text = user_message.lower()
    if any(word in text for word in ["list", "show", "search", "find", "what reminders", "all reminders"]):
        return True
    return any(
        word in text
        for word in [
            "remind me",
            "set a reminder",
            "create reminder",
            "create a reminder",
            "schedule",
            "snooze",
            "reschedule",
            "postpone",
            "shift",
            "move",
            "update",
            "change",
            "done",
            "complete",
            "mark done",
        ]
    )

def is_create_intent(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in [
            "remind me",
            "set a reminder",
            "create reminder",
            "create a reminder",
            "schedule",
        ]
    )

def is_list_intent(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in [
            "list reminders",
            "list all reminders",
            "list my reminders",
            "all my reminders",
            "reminders i have",
            "my reminders",
            "show reminders",
            "show my reminders",
            "tell me about my reminders",
            "tell me about all my reminders",
            "what reminders",
            "what are my reminders",
            "what's coming up",
            "what is coming up",
            "upcoming reminders",
            "reminders list",
        ]
    )

def is_search_intent(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in [
            "find reminder",
            "search reminders",
            "search reminder",
            "look for reminder",
        ]
    )

def get_mem0_context(user_message: str, user_id: str = "default_user", skip_mem0: bool = False) -> Dict[str, Any]:
    """Retrieve relevant context from Mem0 - optimized with better search"""

    if skip_mem0:
        mem0_context = {
            "active_reminders": [],
            "rescheduled_active_reminders": [],
            "preferences": [],
            "behavior": [],
            "conversation_history": []
        }
        debug_context["retrieved_memories"] = mem0_context
        return mem0_context

    cached = _get_cached_mem0_context(user_id)
    if cached:
        debug_context["retrieved_memories"] = cached
        return cached

    # Personalization only: preferences, behavior, and conversation hints.
    behavior_memories = mem0_store.search_behavior("behavior_summary", user_id, limit=3)
    debug_context["mem0_queries"].append({
        "query": "behavior_summary",
        "category": "user_behavior",
        "results_count": len(behavior_memories)
    })

    pref_memories = mem0_store.search_preferences(user_message, user_id, limit=5)
    debug_context["mem0_queries"].append({
        "query": user_message,
        "category": "user_prefs",
        "results_count": len(pref_memories)
    })

    mem0_context = {
        "active_reminders": [],
        "rescheduled_active_reminders": [],
        "preferences": pref_memories,
        "behavior": behavior_memories,
        "conversation_history": []
    }
    debug_context["retrieved_memories"] = mem0_context
    _set_cached_mem0_context(user_id, mem0_context)
    return mem0_context

async def run_agentic_loop(user_message: str, user_id: str = "default_user") -> str:
    """Main agentic loop with Claude"""

    has_time = message_mentions_time(user_message)
    user_time_context[user_id] = {"has_time": has_time}
    pending = pending_actions.get(user_id)
    if pending and pending.get("type") == "update_due":
        if is_confirmation(user_message):
            result = execute_update_reminder(
                user_id=user_id,
                reminder_id=pending["reminder_id"],
                due_str=pending["due_str"]
            )
            pending_actions.pop(user_id, None)
            if result.get("success"):
                return result.get("message", "Reminder updated.")
            return result.get("error", "Sorry, I couldn't update that reminder.")

    if pending and pending.get("type") == "clarify_reminder":
        selection = parse_selection_index(user_message)
        if selection is not None:
            matches = pending.get("matches", [])
            if 0 <= selection < len(matches):
                chosen = matches[selection]
                pending_actions.pop(user_id, None)
                reminder_id = chosen.get("id") or chosen.get("reminder_id")
                if reminder_id:
                    if message_mentions_time(user_message):
                        result = execute_update_reminder(
                            user_id=user_id,
                            reminder_id=reminder_id,
                            due_str=user_message
                        )
                        return result.get("message", "Reminder updated.")
                    return f"Which time should I set for '{chosen.get('title', 'that reminder')}'?"
        if is_rejection(user_message):
            pending_actions.pop(user_id, None)
            return "Okay. Which reminder should I update instead?"
        return pending.get("question", "Which reminder should I update?")
    if pending and pending.get("type") == "confirm_time":
        lowered = user_message.strip().lower()
        if lowered in {"yes", "y", "sure", "ok", "okay", "use it", "go ahead"}:
            suggested_time = pending.get("suggested_time")
            if not suggested_time:
                return "What time should I set it for?"
            pending_actions.pop(user_id, None)
            result = execute_create_reminder(
                user_id=user_id,
                title=pending["title"],
                due_str=f"{pending['due_str']} {suggested_time}",
                description=pending.get("description", ""),
                allow_unconfirmed=True,
            )
            return result.get("message", "Reminder created.")
        if lowered in {"no", "nope", "nah"}:
            return "What time should I set it for?"
        if message_mentions_time(user_message):
            pending_actions.pop(user_id, None)
            result = execute_create_reminder(
                user_id=user_id,
                title=pending["title"],
                due_str=user_message,
                description=pending.get("description", ""),
                allow_unconfirmed=True,
            )
            return result.get("message", "Reminder created.")
        return "What time should I set it for?"
        if is_rejection(user_message) and not message_mentions_time(user_message):
            pending_actions.pop(user_id, None)
            return "Okay. What time should I set it for?"
        if message_mentions_time(user_message):
            result = execute_update_reminder(
                user_id=user_id,
                reminder_id=pending["reminder_id"],
                due_str=user_message
            )
            pending_actions.pop(user_id, None)
            if result.get("success"):
                return result.get("message", "Reminder updated.")
            return result.get("error", "Sorry, I couldn't update that reminder.")
    
    # Get Mem0 context
    skip_mem0 = should_skip_mem0_prefetch(user_message)
    mem0_context = get_mem0_context(user_message, user_id, skip_mem0=skip_mem0)

    common_times = get_common_times_by_category(user_id)
    
    category_guess = infer_category(user_message, "")

    conversation_history = []
    if db:
        try:
            conversation_history = db.get_recent_conversation(user_id, limit=CONVO_WINDOW)
            mem0_context["conversation_history"] = [
                {"role": row["role"], "content": row["content"]}
                for row in conversation_history
            ]
        except Exception:
            pass

    if db:
        try:
            db.add_conversation_message(user_id, "user", user_message)
        except Exception:
            pass

    # Try to get DB reminders, but don't fail if DB is locked
    db_reminders = []
    db_rescheduled = []
    if db:
        try:
            db_reminders = db.list_active_reminders(user_id)
            db_rescheduled = db.list_rescheduled_reminders(user_id)
        except Exception as e:
            debug_context["db_changes"].append({
                "action": "db_read_failed",
                "error": str(e),
                "note": "Using Mem0 as primary source"
            })
    else:
        debug_context["db_changes"].append({
            "action": "db_unavailable",
            "note": "Running in Mem0-only mode"
        })
    
    # Build system prompt
    system_prompt = f"""You are a proactive, friendly reminder companion in Slack. You help users stay organized while learning their habits and preferences over time.

## PERSONALITY & TONE
- Be conversational, supportive, and concise
- Use natural language (avoid robotic responses)
- Celebrate completions and encourage productivity
- Match the user's communication style (formal/casual)
- Proactively suggest improvements based on patterns

## CURRENT CONTEXT
**Active Reminders:**
{json.dumps([{
    'id': _reminder_value(r, "id", 0),
    'title': _reminder_value(r, "title", 2),
    'description': _reminder_value(r, "description", 3),
    'due_at': format_due_datetime(_reminder_value(r, "due_at_epoch", 4)),
    'status': _reminder_value(r, "status", 5),
    'category': _reminder_value(r, "category", 6)
} for r in db_reminders], indent=2) if db_reminders else "No active reminders"}

**Rescheduled Active Reminders:**
{json.dumps([{
    'id': _reminder_value(r, "id", 0),
    'title': _reminder_value(r, "title", 2),
    'description': _reminder_value(r, "description", 3),
    'due_at': format_due_datetime(_reminder_value(r, "due_at_epoch", 4)),
    'status': _reminder_value(r, "status", 5),
    'category': _reminder_value(r, "category", 6),
    'reschedule_count': _reminder_value(r, "reschedule_count", 10)
} for r in db_rescheduled], indent=2) if db_rescheduled else "No rescheduled reminders"}

**User Patterns:**
- Preferences: {json.dumps(mem0_context['preferences'], indent=2)}
- Behavior: {json.dumps(mem0_context['behavior'], indent=2)}
- Recent context: {json.dumps(mem0_context['conversation_history'][-3:], indent=2)}

**Time Context:**
- Current: {datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")}
- Timezone: {DEFAULT_TIMEZONE}
- Suggested times: {json.dumps(common_times, indent=2)}

## CORE BEHAVIORS
1. Natural language first: parse "tomorrow at 3", "next Monday", "in 2 hours" automatically
2. Smart defaults: if no time given, suggest category-appropriate time from user patterns/common times, then confirm
3. Clarify ambiguity: use clarify_reminder tool when multiple matches exist
4. Proactive insights: notice patterns and suggest improvements when appropriate
5. DB is ground truth: always use DB-backed tools for reminder status/times; Mem0 is context only
6. Clean responses: use tool summaries verbatim; never expose internal IDs or storage details
7. Respect user intent: only delete when explicitly requested
8. Accept short-term reminders (minutes) without refusing; never scold the user.
9. Never change or round user-provided times; preserve exact minutes/hours. If unclear, ask a brief clarification.
10. If the user asks for archived/completed reminders, call list_reminders with status="completed".

## RESPONSE GUIDELINES
- Confirmations: "Got it! I'll remind you about {{title}} on {{date}}"
- Lists: always call list_reminders and return its formatted summary verbatim with no extra text.
- Errors: be helpful, not apologetic ("Let me help you fix that...")
- Follow-ups: suggest related actions when relevant

Keep it human, helpful, and focused on the user's goals."""

    if DEBUG_SYSTEM_PROMPT:
        try:
            print("=== SYSTEM PROMPT START ===")
            print(system_prompt)
            print("=== SYSTEM PROMPT END ===")
            if SYSTEM_PROMPT_LOG_PATH:
                with open(SYSTEM_PROMPT_LOG_PATH, "a", encoding="utf-8") as log_file:
                    log_file.write("=== SYSTEM PROMPT START ===\n")
                    log_file.write(system_prompt)
                    log_file.write("\n=== SYSTEM PROMPT END ===\n")
        except Exception:
            pass

    # Initialize message history
    messages = [{"role": "user", "content": user_message}]
    
    # Agentic loop
    max_iterations = 10
    iteration = 0
    last_list_summary = None
    
    while iteration < max_iterations:
        iteration += 1
        
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            tools=TOOLS,
            system=system_prompt,
            messages=messages
        )
        
        # Check stop reason
        if response.stop_reason == "end_turn":
            # Extract final text response
            final_text = ""
            for block in response.content:
                if block.type == "text":
                    final_text += block.text

            if last_list_summary:
                final_text = last_list_summary

            if db:
                try:
                    db.add_conversation_message(user_id, "assistant", final_text)
                except Exception:
                    pass
            
            # Store conversation in Mem0
            if BACKGROUND_MEM0_WRITES:
                run_in_background(
                    mem0_store.add_conversation,
                    f"User: {user_message}\nAssistant: {final_text}",
                    user_id
                )
            else:
                mem0_store.add_conversation(
                    f"User: {user_message}\nAssistant: {final_text}",
                    user_id
                )

            return final_text
        
        elif response.stop_reason == "tool_use":
            # Add assistant's response to messages
            messages.append({"role": "assistant", "content": response.content})
            
            # Execute all tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    
                    # Execute tool
                    result = execute_tool(tool_name, tool_input, user_id)
                    if tool_name == "list_reminders" and isinstance(result, dict):
                        summary = result.get("summary")
                        if summary:
                            last_list_summary = summary
                    if tool_name == "create_reminder" and isinstance(result, dict):
                        pending = result.get("pending", {})
                        if pending.get("type") == "confirm_time":
                            prompt = result.get("prompt")
                            if prompt:
                                if db:
                                    try:
                                        db.add_conversation_message(user_id, "assistant", prompt)
                                    except Exception:
                                        pass
                                if BACKGROUND_MEM0_WRITES:
                                    run_in_background(
                                        mem0_store.add_conversation,
                                        f"User: {user_message}\nAssistant: {prompt}",
                                        user_id
                                    )
                                else:
                                    mem0_store.add_conversation(
                                        f"User: {user_message}\nAssistant: {prompt}",
                                        user_id
                                    )
                                return prompt
                    
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
            
            # Add tool results to messages
            messages.append({"role": "user", "content": tool_results})
        
        else:
            # Unexpected stop reason
            return f"Unexpected stop reason: {response.stop_reason}"
    
    return "Maximum iterations reached. Please try again."

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render home page"""
    reset_debug_context()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "messages": [],
        "debug": debug_context,
        "user_id": "default_user"
    })

@app.post("/chat")
async def chat(message: str = Form(...), user_id: str = Form("default_user")):
    """Handle chat message"""
    reset_debug_context()
    
    start_time = time.time()
    response_text = await run_agentic_loop(message, user_id)
    elapsed = time.time() - start_time
    
    return JSONResponse({
        "success": True,
        "message": message,
        "response": response_text,
        "elapsed": elapsed,
        "debug": debug_context
    })

@app.post("/slack/events")
async def slack_events(
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
    background_tasks: BackgroundTasks = None,
):
    body = await request.body()
    if not verify_slack_signature(x_slack_signature, x_slack_request_timestamp, body):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    payload = await request.json()
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge")})

    if payload.get("type") == "event_callback":
        event_id = payload.get("event_id")
        if is_duplicate_slack_event(event_id):
            return JSONResponse({"ok": True})
        event = payload.get("event", {})
        if event.get("type") == "message" and not event.get("bot_id"):
            user_id = event.get("user", "default_user")
            channel = event.get("channel")
            raw_text = event.get("text", "")
            text = sanitize_slack_text(raw_text)
            if user_id and channel:
                slack_user_channels[user_id] = channel
            if text and channel:
                async def handle_slack_message():
                    response_text = await run_agentic_loop(text, user_id=user_id)
                    if SLACK_BOT_TOKEN:
                        try:
                            import requests
                            resp = requests.post(
                                f"{SLACK_API_BASE}/chat.postMessage",
                                headers={
                                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                                    "Content-Type": "application/json; charset=utf-8",
                                },
                                json={"channel": channel, "text": response_text},
                                timeout=10,
                            )
                            debug_context["webhook_events"].append({
                                "type": "slack_post_message",
                                "channel": channel,
                                "ok": resp.ok,
                                "status": resp.status_code,
                                "body": resp.text,
                            })
                            print(f"Slack postMessage status={resp.status_code} ok={resp.ok} body={resp.text}")
                        except Exception:
                            debug_context["webhook_events"].append({
                                "type": "slack_post_message_error",
                                "error": "request_failed"
                            })
                            print("Slack postMessage error=request_failed")
                    else:
                        debug_context["webhook_events"].append({
                            "type": "slack_post_message_error",
                            "error": "missing_bot_token"
                        })
                        print("Slack postMessage error=missing_bot_token")
                if background_tasks is not None:
                    background_tasks.add_task(handle_slack_message)
                else:
                    await handle_slack_message()
    return JSONResponse({"ok": True})

@app.post("/slack/commands")
async def slack_commands(
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
):
    body = await request.body()
    if not verify_slack_signature(x_slack_signature, x_slack_request_timestamp, body):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    form = await request.form()
    user_id = form.get("user_id", "default_user")
    channel_id = form.get("channel_id")
    text = form.get("text", "")

    response_text = await run_agentic_loop(text, user_id=user_id)
    return JSONResponse({
        "response_type": "in_channel",
        "text": response_text
    })

@app.post("/slack/interactions")
async def slack_interactions(
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
    background_tasks: BackgroundTasks = None,
):
    body = await request.body()
    if not verify_slack_signature(x_slack_signature, x_slack_request_timestamp, body):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))
    actions = payload.get("actions", [])
    user = payload.get("user", {})
    user_id = user.get("id", "default_user")
    response_url = payload.get("response_url")

    if not actions:
        return JSONResponse({"ok": True})

    action = actions[0]
    action_id = action.get("action_id")
    reminder_id = int(action.get("value", "0") or 0)

    async def handle_interaction():
        if reminder_id and action_id == "reminder_done":
            result = execute_mark_done(user_id=user_id, reminder_id=reminder_id)
            message = result.get("message", "Marked as done.")
        elif reminder_id and action_id == "reminder_snooze_10m":
            result = execute_snooze_reminder(user_id=user_id, reminder_id=reminder_id, snooze_str="10 minutes")
            message = result.get("message", "Snoozed for 10 minutes.")
        else:
            message = "Action not recognized."

        if response_url:
            try:
                import requests
                requests.post(
                    response_url,
                    json={
                        "replace_original": True,
                        "text": message
                    },
                    timeout=10,
                )
            except Exception:
                pass

    if background_tasks is not None:
        background_tasks.add_task(handle_interaction)
    else:
        await handle_interaction()

    return JSONResponse({"ok": True})

@app.get("/slack/notify_due")
async def slack_notify_due(user_id: str = None):
    """Send due reminders to Slack DM channels (if known)."""
    if not db or not SLACK_BOT_TOKEN:
        return JSONResponse({"success": False, "error": "Slack or DB not configured"})

    sent = send_slack_due_notifications(user_id=user_id)
    return JSONResponse({"success": True, "sent": sent})

@app.on_event("startup")
async def start_slack_notification_loop():
    if not SLACK_NOTIFY_ENABLED:
        return

    async def loop():
        while True:
            try:
                send_slack_due_notifications()
            except Exception:
                pass
            await asyncio.sleep(SLACK_NOTIFY_INTERVAL_SECONDS)

    asyncio.create_task(loop())

@app.post("/action/done")
async def action_done(reminder_id: int = Form(...), user_id: str = Form("default_user")):
    """Mark reminder done directly from UI"""
    reset_debug_context()
    result = execute_mark_done(user_id=user_id, reminder_id=reminder_id)
    return JSONResponse({"success": result.get("success", False), "result": result, "debug": debug_context})

@app.post("/action/snooze")
async def action_snooze(
    reminder_id: int = Form(...),
    snooze_str: str = Form(...),
    user_id: str = Form("default_user")
):
    """Snooze reminder directly from UI"""
    reset_debug_context()
    result = execute_snooze_reminder(user_id=user_id, reminder_id=reminder_id, snooze_str=snooze_str)
    return JSONResponse({"success": result.get("success", False), "result": result, "debug": debug_context})


@app.get("/notifications")
async def notifications(user_id: str = "default_user"):
    """Return reminders due within the next 10 minutes"""
    now_epoch = int(time.time())
    due_soon = db.get_due_soon_reminders(user_id, now_epoch, lead_time_seconds=600)
    items = []
    for reminder in due_soon:
        reminder_id = reminder["id"]
        due_at = reminder["due_at_epoch"]
        minutes_left = max(0, int((due_at - now_epoch) / 60))
        items.append({
            "reminder_id": reminder_id,
            "title": reminder["title"],
            "due_at_epoch": due_at,
            "due_label": datetime.fromtimestamp(due_at).strftime("%b %d %I:%M %p"),
            "minutes_left": minutes_left
        })
        db.mark_reminder_notified(reminder_id, user_id, now_epoch)

    return JSONResponse({"success": True, "notifications": items})


@app.post("/cron/archive_overdue")
async def archive_overdue(request: Request):
    token = request.headers.get("x-cron-token", "")
    if ARCHIVE_CRON_TOKEN and token != ARCHIVE_CRON_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not db:
        return JSONResponse({"error": "db_unavailable"}, status_code=503)
    now_epoch = int(time.time())
    try:
        updated = db.archive_overdue_reminders(now_epoch)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"success": True, "archived": updated}

@app.get("/memories")
async def memories(user_id: str = "default_user"):
    """Return all memories for a user by category"""
    active = mem0_store.get_all_memories(user_id=user_id, categories=[mem0_store.CAT_REMINDER_ACTIVE])
    archived = mem0_store.get_all_memories(user_id=user_id, categories=[mem0_store.CAT_REMINDER_ARCHIVED])
    prefs = mem0_store.get_all_memories(user_id=user_id, categories=[mem0_store.CAT_USER_PREFS])
    behavior = mem0_store.get_all_memories(user_id=user_id, categories=[mem0_store.CAT_USER_BEHAVIOR])
    convo = mem0_store.get_all_memories(user_id=user_id, categories=[mem0_store.CAT_CONVERSATION])
    return JSONResponse({
        "success": True,
        "all_memories": {
            "active": active,
            "archived": archived,
            "preferences": prefs,
            "behavior": behavior,
            "conversation": convo
        }
    })



@app.post("/webhook/mem0")
async def mem0_webhook(request: Request):
    """Handle Mem0 webhooks"""
    payload = await request.json()
    
    debug_context["webhook_events"].append({
        "timestamp": time.time(),
        "event": payload
    })
    
    # Log to audit
    db.log_audit(payload.get("user_id", ""), "mem0_webhook", json.dumps(payload))
    
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
Probe Mem0 add/get to debug empty responses.
Run with: python mem0_debug_probe.py
"""

import os
import json
import uuid
from datetime import datetime, timezone

from mem0 import MemoryClient
from dotenv import load_dotenv

load_dotenv()

def main():
    client = MemoryClient(
        api_key=os.getenv("MEM0_API_KEY"),
        org_id=os.getenv("MEM0_ORG_ID"),
        project_id=os.getenv("MEM0_PROJECT_ID"),
    )

    user_id = f"debug_user_{uuid.uuid4().hex[:8]}"
    message = f"Mem0 debug probe at {datetime.now(timezone.utc).isoformat()}"

    print("=== MEM0 DEBUG PROBE ===")
    print("User ID:", user_id)
    print("Message:", message)

    add_payload = {
        "messages": [{"role": "user", "content": message}],
        "user_id": user_id,
        "metadata": {"probe": True, "mem0_category": "debug_probe"},
        "categories": ["debug_probe"],
        "async_mode": False,
        "version": "v2",
    }
    print("\nAdd payload:")
    print(json.dumps(add_payload, indent=2))

    try:
        add_result = client.add(**add_payload)
        print("\nAdd raw response:")
        print(add_result)
    except Exception as exc:
        print("\nAdd exception:", repr(exc))
        return

    filters = {
        "AND": [
            {"user_id": user_id}
        ]
    }
    print("\nGet-all filters (user_id only):")
    print(json.dumps(filters, indent=2))

    try:
        get_result = client.get_all(filters=filters, version="v2")
        print("\nGet-all raw response (user_id only):")
        print(get_result)
    except Exception as exc:
        print("\nGet-all exception (user_id only):", repr(exc))

    try:
        search_result = client.search(
            query="Mem0 debug probe",
            user_id=user_id,
            limit=5
        )
        print("\nSearch raw response (no categories):")
        print(search_result)
    except Exception as exc:
        print("\nSearch exception (no categories):", repr(exc))

if __name__ == "__main__":
    main()

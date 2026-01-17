"""
Scenario-driven test runner for the reminder agent.
Run with: python test_scenarios.py
"""

import asyncio
import copy
import json
import os
import time
import uuid
from datetime import datetime, timezone

from main import run_agentic_loop, reset_debug_context, debug_context

TEST_USER_ID = f"test_user_{uuid.uuid4().hex[:8]}"

SCENARIOS = [
    {
        "category": "simple",
        "name": "Create reminder",
        "steps": [
            "i have a call tomorrow 2pm"
        ],
    },
    {
        "category": "reschedule",
        "name": "Reschedule reminder",
        "steps": [
            "i have a call tomorrow 2pm",
            "wait shift that call to 4pm tomorrow"
        ],
    },
    {
        "category": "ambiguity",
        "name": "Ambiguous update",
        "steps": [
            "remind me about meeting A tomorrow at 2pm",
            "remind me about meeting B tomorrow at 3pm",
            "move my meeting to 4pm"
        ],
    },
    {
        "category": "preferences",
        "name": "Set preference then create",
        "steps": [
            "set my timezone to America/New_York",
            "remind me to pay rent tomorrow at 9am"
        ],
    },
    {
        "category": "list-search",
        "name": "List and search",
        "steps": [
            "what are my reminders?",
            "find my rent reminder"
        ],
    },
    {
        "category": "done-flow",
        "name": "Mark done",
        "steps": [
            "remind me to buy milk tomorrow at 10am",
            "mark the milk reminder as done",
            "list completed reminders"
        ],
    },
    {
        "category": "rescheduled-filter",
        "name": "List rescheduled reminders",
        "steps": [
            "list rescheduled reminders"
        ],
    },
]

def extract_scores(retrieved_memories):
    scores = []
    if not isinstance(retrieved_memories, dict):
        return scores
    for key, memories in retrieved_memories.items():
        if not isinstance(memories, list):
            continue
        for mem in memories:
            if isinstance(mem, dict) and "score" in mem:
                scores.append({
                    "group": key,
                    "id": mem.get("id"),
                    "score": mem.get("score"),
                    "memory": mem.get("memory"),
                })
    return scores

async def run_scenario(scenario):
    steps_report = []
    for step in scenario["steps"]:
        reset_debug_context()
        started = time.time()
        response = await run_agentic_loop(step, user_id=TEST_USER_ID)
        elapsed = time.time() - started

        step_debug = copy.deepcopy(debug_context)
        step_report = {
            "prompt": step,
            "response": response,
            "elapsed_seconds": round(elapsed, 2),
            "mem0_queries": step_debug.get("mem0_queries", []),
            "tool_calls": step_debug.get("tool_calls", []),
            "db_changes": step_debug.get("db_changes", []),
            "retrieved_memories": step_debug.get("retrieved_memories", {}),
            "scores": extract_scores(step_debug.get("retrieved_memories", {})),
        }
        steps_report.append(step_report)
    return steps_report

async def run_all_scenarios():
    report = {
        "run_id": uuid.uuid4().hex,
        "user_id": TEST_USER_ID,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": [],
    }

    for scenario in SCENARIOS:
        steps_report = await run_scenario(scenario)
        report["scenarios"].append({
            "category": scenario["category"],
            "name": scenario["name"],
            "steps": steps_report,
        })

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report

def write_report(report):
    os.makedirs("test_reports", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join("test_reports", f"report_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return path

def print_summary(report, report_path):
    print("\n=== SCENARIO TEST SUMMARY ===")
    print(f"Report: {report_path}")
    print(f"User ID: {report['user_id']}")
    print(f"Scenarios: {len(report['scenarios'])}")
    for scenario in report["scenarios"]:
        print(f"- {scenario['category']}: {scenario['name']} ({len(scenario['steps'])} steps)")
        for step in scenario["steps"]:
            elapsed = step["elapsed_seconds"]
            prompt = step["prompt"]
            print(f"  * {elapsed}s: {prompt}")
    print("=== END SUMMARY ===\n")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    report_data = asyncio.run(run_all_scenarios())
    report_path = write_report(report_data)
    print_summary(report_data, report_path)

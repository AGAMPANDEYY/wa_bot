"""
Integration tests for the agentic reminder system
Run with: python test_system.py
"""

import os
import json
import asyncio
import uuid
from datetime import datetime, timedelta
from db import Database
from mem0_store import Mem0Store
from main import run_agentic_loop, reset_debug_context

# Test configuration
TEST_USER_ID = "test_user_123"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def print_test(name):
    print(f"\n{Colors.BLUE}▶ Testing: {name}{Colors.RESET}")

def print_success(message):
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")

def print_error(message):
    print(f"{Colors.RED}✗ {message}{Colors.RESET}")

async def test_create_reminder():
    """Test creating a reminder with natural language"""
    print_test("Create Reminder")
    
    reset_debug_context()
    response = await run_agentic_loop(
        "Remind me to call John tomorrow at 3pm",
        user_id=TEST_USER_ID
    )
    
    if "created" in response.lower() or "reminder" in response.lower():
        print_success(f"Response: {response}")
        return True
    else:
        print_error(f"Unexpected response: {response}")
        return False

async def test_list_reminders():
    """Test listing reminders"""
    print_test("List Reminders")
    
    reset_debug_context()
    response = await run_agentic_loop(
        "What are my reminders?",
        user_id=TEST_USER_ID
    )
    
    if "reminder" in response.lower():
        print_success(f"Response: {response}")
        return True
    else:
        print_error(f"Unexpected response: {response}")
        return False

async def test_update_reminder():
    """Test updating a reminder"""
    print_test("Update Reminder")
    
    # First create a reminder
    await run_agentic_loop(
        "Remind me about team meeting tomorrow at 2pm",
        user_id=TEST_USER_ID
    )
    
    # Then update it
    reset_debug_context()
    response = await run_agentic_loop(
        "Move my team meeting to 4pm",
        user_id=TEST_USER_ID
    )
    
    if "updated" in response.lower() or "moved" in response.lower():
        print_success(f"Response: {response}")
        return True
    else:
        print_error(f"Unexpected response: {response}")
        return False

async def test_mark_done():
    """Test marking reminder as done"""
    print_test("Mark Reminder Done")
    
    # Create a reminder
    await run_agentic_loop(
        "Remind me to buy groceries today at 5pm",
        user_id=TEST_USER_ID
    )
    
    # Mark it done
    reset_debug_context()
    response = await run_agentic_loop(
        "Mark the groceries reminder as done",
        user_id=TEST_USER_ID
    )
    
    if "done" in response.lower() or "completed" in response.lower():
        print_success(f"Response: {response}")
        return True
    else:
        print_error(f"Unexpected response: {response}")
        return False

async def test_search_reminders():
    """Test searching reminders"""
    print_test("Search Reminders")
    
    # Create some reminders
    await run_agentic_loop(
        "Remind me to call dentist tomorrow",
        user_id=TEST_USER_ID
    )
    
    # Search
    reset_debug_context()
    response = await run_agentic_loop(
        "Find my dentist reminder",
        user_id=TEST_USER_ID
    )
    
    if "dentist" in response.lower():
        print_success(f"Response: {response}")
        return True
    else:
        print_error(f"Unexpected response: {response}")
        return False

async def test_set_preference():
    """Test setting user preference"""
    print_test("Set Preference")
    
    reset_debug_context()
    response = await run_agentic_loop(
        "Set my timezone to America/New_York",
        user_id=TEST_USER_ID
    )
    
    if "timezone" in response.lower() and "set" in response.lower():
        print_success(f"Response: {response}")
        return True
    else:
        print_error(f"Unexpected response: {response}")
        return False

async def test_mem0_context():
    """Test that Mem0 context is being used"""
    print_test("Mem0 Context Retrieval")
    
    # Create a reminder
    await run_agentic_loop(
        "Remind me about doctor appointment next Monday at 10am",
        user_id=TEST_USER_ID
    )
    
    # Query about it without being specific
    reset_debug_context()
    response = await run_agentic_loop(
        "When is my doctor appointment?",
        user_id=TEST_USER_ID
    )
    
    if "monday" in response.lower() and "10" in response.lower():
        print_success("Mem0 context successfully retrieved")
        return True
    else:
        print_error("Mem0 context not used effectively")
        return False

async def test_date_parsing():
    """Test natural language date parsing"""
    print_test("Date Parsing")
    
    test_cases = [
        "tomorrow at 3pm",
        "next Monday",
        "in 2 hours",
        "Friday at noon"
    ]
    
    all_passed = True
    for date_str in test_cases:
        reset_debug_context()
        response = await run_agentic_loop(
            f"Remind me to test {date_str}",
            user_id=TEST_USER_ID
        )
        
        if "created" in response.lower() or "reminder" in response.lower():
            print_success(f"Parsed: {date_str}")
        else:
            print_error(f"Failed to parse: {date_str}")
            all_passed = False
    
    return all_passed

async def test_clarification():
    """Test clarification when multiple matches exist"""
    print_test("Clarification Logic")
    
    # Create multiple similar reminders
    await run_agentic_loop(
        "Remind me about meeting A tomorrow at 2pm",
        user_id=TEST_USER_ID
    )
    await run_agentic_loop(
        "Remind me about meeting B tomorrow at 3pm",
        user_id=TEST_USER_ID
    )
    
    # Try to update ambiguously
    reset_debug_context()
    response = await run_agentic_loop(
        "Move my meeting to 4pm",
        user_id=TEST_USER_ID
    )
    
    if "which" in response.lower() or "clarify" in response.lower():
        print_success("Clarification requested appropriately")
        return True
    else:
        print_error("Should have requested clarification")
        return False

def test_db_operations():
    """Test database operations"""
    print_test("Database Operations")
    
    # Use a separate test database with unique name
    import uuid
    test_db_path = f"test_data_{uuid.uuid4().hex[:8]}.db"
    
    # Remove if exists
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except:
            pass
    
    db = None
    try:
        db = Database(test_db_path)
        
        # Create reminder
        reminder_id = db.create_reminder(
            TEST_USER_ID,
            "Test reminder",
            "Test description",
            int((datetime.now() + timedelta(days=1)).timestamp())
        )
        print_success(f"Created reminder: {reminder_id}")
        
        # Update reminder
        db.update_reminder(reminder_id, TEST_USER_ID, title="Updated reminder")
        reminder = db.get_reminder(reminder_id, TEST_USER_ID)
        assert reminder["title"] == "Updated reminder"
        print_success("Updated reminder")
        
        # Mark done
        db.mark_reminder_done(reminder_id, TEST_USER_ID)
        reminder = db.get_reminder(reminder_id, TEST_USER_ID)
        assert reminder["status"] == "completed"
        print_success("Marked reminder done")
        
        # Set preference
        db.set_preference(TEST_USER_ID, "test_key", "test_value")
        value = db.get_preference(TEST_USER_ID, "test_key")
        assert value == "test_value"
        print_success("Set preference")
        
        return True
        
    except Exception as e:
        print_error(f"Database test failed: {e}")
        return False
        
    finally:
        # Ensure database is closed
        if db:
            try:
                # Close any open connections
                conn = db.get_conn()
                conn.close()
            except:
                pass
        
        # Clean up
        import time
        time.sleep(0.1)  # Brief pause to ensure file is released
        
        try:
            if os.path.exists(test_db_path):
                os.remove(test_db_path)
            if os.path.exists(f"{test_db_path}-wal"):
                os.remove(f"{test_db_path}-wal")
            if os.path.exists(f"{test_db_path}-shm"):
                os.remove(f"{test_db_path}-shm")
        except Exception as e:
            print(f"Warning: Could not clean up test database: {e}")

def test_mem0_operations():
    """Test Mem0 operations"""
    print_test("Mem0 Operations")
    
    mem0 = Mem0Store()
    
    # Add active reminder
    mem0_id = mem0.upsert_active_reminder(
        "Test reminder: Call dentist tomorrow at 3pm",
        user_id=TEST_USER_ID,
        metadata={"reminder_id": 999}
    )
    print_success(f"Created Mem0 memory: {mem0_id}")
    
    # Search for it
    results = mem0.search_reminders(
        "dentist",
        user_id=TEST_USER_ID,
        active_only=True
    )
    
    if results and len(results) > 0:
        print_success(f"Found {len(results)} memories")
    else:
        print_error("Memory not found")
        return False
    
    # Archive it
    archive_id = mem0.upsert_archived_reminder(
        "Completed: Call dentist",
        user_id=TEST_USER_ID,
        metadata={"reminder_id": 999}
    )
    print_success(f"Archived memory: {archive_id}")
    
    # Clean up
    if mem0_id:
        mem0.delete_memory(mem0_id)
    if archive_id:
        mem0.delete_memory(archive_id)
    
    return True

async def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("🧪 REMINDER CONCIERGE - TEST SUITE")
    print("="*60)
    
    results = []
    
    # Database tests
    results.append(("Database Operations", test_db_operations()))
    
    # Mem0 tests
    results.append(("Mem0 Operations", test_mem0_operations()))
    
    # Agentic tests
    results.append(("Create Reminder", await test_create_reminder()))
    results.append(("List Reminders", await test_list_reminders()))
    results.append(("Update Reminder", await test_update_reminder()))
    results.append(("Mark Done", await test_mark_done()))
    results.append(("Search Reminders", await test_search_reminders()))
    results.append(("Set Preference", await test_set_preference()))
    results.append(("Mem0 Context", await test_mem0_context()))
    results.append(("Date Parsing", await test_date_parsing()))
    results.append(("Clarification", await test_clarification()))
    
    # Print summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        color = Colors.GREEN if result else Colors.RED
        print(f"{color}{status}{Colors.RESET} - {test_name}")
    
    print(f"\n{Colors.BLUE}Results: {passed}/{total} tests passed{Colors.RESET}")
    
    if passed == total:
        print(f"{Colors.GREEN}🎉 All tests passed!{Colors.RESET}")
    else:
        print(f"{Colors.RED}⚠ Some tests failed{Colors.RESET}")
    
    print("="*60 + "\n")

if __name__ == "__main__":
    # Load environment
    from dotenv import load_dotenv
    load_dotenv()
    
    # Run tests
    asyncio.run(run_all_tests())

"""
Setup script to configure Mem0 with custom instructions and categories
Run this once to initialize your Mem0 project
"""

import os
from mem0 import MemoryClient


from dotenv import load_dotenv

load_dotenv()

# Initialize Mem0 client
client = MemoryClient(
    api_key=os.getenv("MEM0_API_KEY"),
    org_id=os.getenv("MEM0_ORG_ID"),
    project_id=os.getenv("MEM0_PROJECT_ID")
)

# Custom instructions for Mem0
CUSTOM_INSTRUCTIONS = """
You are a memory system for a reminder assistant. Follow these guidelines:

1. ONLY store confirmed facts about reminders and user preferences
2. DO NOT store:
   - Speculative information
   - Small talk or pleasantries
   - Temporary conversation context that won't be needed later
   - Duplicate information

3. When storing reminders:
   - Include: title, description, due date/time
   - Assign category: "reminder_active" for active reminders
   - Assign category: "reminder_archived" for completed reminders
   - Include metadata: reminder_id, due_at_epoch
   - For rescheduled (snoozed/changed due date) reminders, keep category "reminder_active"
     and include metadata: reschedule_count, last_rescheduled_at_epoch
   - Include metadata: category (e.g., "family", "work", "personal") to personalize defaults

4. When storing preferences:
   - Include: preference key and value
   - Assign category: "user_prefs"
   - Include metadata: pref_key

5. When storing conversation history:
   - Store only meaningful exchanges
   - Assign category: "conversation"
   - Include metadata: timestamp

6. Update existing memories instead of creating duplicates
7. Delete memories only when explicitly requested by the user

Format examples:
- Reminder: "Reminder: Team meeting. Due: 2024-01-20 15:00. Description: Discuss Q1 goals"
- Preference: "User preference: timezone = Asia/Kolkata"
- Conversation: "User asked about meeting reminders. Assistant listed 3 active meetings."
"""

# Custom categories
CUSTOM_CATEGORIES = [
    {
        "name": "reminder_active",
        "description": "Active reminders that are not yet completed"
    },
    {
        "name": "reminder_archived",
        "description": "Completed or archived reminders"
    },
    {
        "name": "user_prefs",
        "description": "User preferences like timezone, notification settings, etc."
    },
    {
        "name": "conversation",
        "description": "Important conversation history and context"
    }
]

def setup_instructions():
    """Set custom instructions for Mem0"""
    try:
        # Note: Check Mem0 v2 API documentation for exact method
        # This is a placeholder - adjust based on actual API
        response = client.set_custom_instructions(CUSTOM_INSTRUCTIONS)
        print("✓ Custom instructions set successfully")
        print(f"Response: {response}")
    except AttributeError:
        print("⚠ set_custom_instructions method not available in current Mem0 SDK")
        print("Please set instructions manually in Mem0 dashboard")
        print(f"\nInstructions to set:\n{CUSTOM_INSTRUCTIONS}")
    except Exception as e:
        print(f"✗ Error setting instructions: {e}")

def setup_categories():
    """Set custom categories for Mem0"""
    try:
        # Note: Check Mem0 v2 API documentation for exact method
        # This is a placeholder - adjust based on actual API
        for category in CUSTOM_CATEGORIES:
            response = client.create_category(
                name=category["name"],
                description=category["description"]
            )
            print(f"✓ Created category: {category['name']}")
    except AttributeError:
        print("⚠ create_category method not available in current Mem0 SDK")
        print("Please create categories manually in Mem0 dashboard")
        print("\nCategories to create:")
        for cat in CUSTOM_CATEGORIES:
            print(f"  - {cat['name']}: {cat['description']}")
    except Exception as e:
        print(f"✗ Error creating categories: {e}")

def verify_setup():
    """Verify the setup by checking project info"""
    try:
        # Test a simple operation
        result = client.get_all(user_id="test_user", limit=1)
        print("\n✓ Mem0 connection successful")
        print(f"Project ID: {os.getenv('MEM0_PROJECT_ID')}")
        print(f"Org ID: {os.getenv('MEM0_ORG_ID')}")
    except Exception as e:
        print(f"\n✗ Mem0 connection failed: {e}")

if __name__ == "__main__":
    print("=== Mem0 Setup Script ===\n")
    
    # Verify environment variables
    required_vars = ["MEM0_API_KEY", "MEM0_ORG_ID", "MEM0_PROJECT_ID"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"✗ Missing environment variables: {', '.join(missing_vars)}")
        print("Please set them in your .env file")
        exit(1)
    
    print("Setting up custom instructions...")
    setup_instructions()
    
    print("\nSetting up custom categories...")
    setup_categories()
    
    print("\nVerifying setup...")
    verify_setup()
    
    print("\n=== Setup Complete ===")
    print("\nNote: If methods are not available in SDK,")
    print("please configure manually in Mem0 dashboard at:")
    print("https://app.mem0.ai/")

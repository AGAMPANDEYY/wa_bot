"""
Setup script to register Mem0 webhooks
Run this to enable real-time memory event notifications
"""

import os
import requests

# Mem0 API configuration
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
MEM0_ORG_ID = os.getenv("MEM0_ORG_ID")
MEM0_PROJECT_ID = os.getenv("MEM0_PROJECT_ID")
MEM0_WEBHOOK_URL = os.getenv("MEM0_WEBHOOK_URL")  # e.g., https://your-domain.com/webhook/mem0

# Mem0 API endpoint (adjust based on actual v2 API)
MEM0_API_BASE = "https://api.mem0.ai/v2"

def register_webhook():
    """Register webhook with Mem0"""
    
    if not MEM0_WEBHOOK_URL:
        print("✗ MEM0_WEBHOOK_URL not set in environment")
        print("Please set it to your public webhook endpoint")
        print("Example: https://your-domain.com/webhook/mem0")
        return
    
    # Webhook configuration
    webhook_config = {
        "url": MEM0_WEBHOOK_URL,
        "events": [
            "memory.created",
            "memory.updated",
            "memory.deleted"
        ],
        "description": "Reminder Concierge webhook for memory events"
    }
    
    headers = {
        "Authorization": f"Bearer {MEM0_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # Attempt to register webhook
        # Note: Adjust endpoint based on actual Mem0 v2 API documentation
        response = requests.post(
            f"{MEM0_API_BASE}/projects/{MEM0_PROJECT_ID}/webhooks",
            json=webhook_config,
            headers=headers
        )
        
        if response.status_code in [200, 201]:
            print("✓ Webhook registered successfully")
            print(f"Webhook URL: {MEM0_WEBHOOK_URL}")
            print(f"Events: {', '.join(webhook_config['events'])}")
            print(f"\nWebhook ID: {response.json().get('id')}")
        else:
            print(f"✗ Webhook registration failed: {response.status_code}")
            print(f"Response: {response.text}")
    
    except Exception as e:
        print(f"✗ Error registering webhook: {e}")
        print("\nPlease register webhook manually in Mem0 dashboard:")
        print(f"1. Go to https://app.mem0.ai/")
        print(f"2. Navigate to Project Settings -> Webhooks")
        print(f"3. Add webhook URL: {MEM0_WEBHOOK_URL}")
        print(f"4. Enable events: memory.created, memory.updated, memory.deleted")

def list_webhooks():
    """List all registered webhooks"""
    headers = {
        "Authorization": f"Bearer {MEM0_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            f"{MEM0_API_BASE}/projects/{MEM0_PROJECT_ID}/webhooks",
            headers=headers
        )
        
        if response.status_code == 200:
            webhooks = response.json()
            print("\n=== Registered Webhooks ===")
            for webhook in webhooks.get("webhooks", []):
                print(f"\nID: {webhook.get('id')}")
                print(f"URL: {webhook.get('url')}")
                print(f"Events: {', '.join(webhook.get('events', []))}")
                print(f"Status: {webhook.get('status', 'active')}")
        else:
            print(f"Could not list webhooks: {response.status_code}")
    
    except Exception as e:
        print(f"Error listing webhooks: {e}")

def delete_webhook(webhook_id: str):
    """Delete a webhook by ID"""
    headers = {
        "Authorization": f"Bearer {MEM0_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.delete(
            f"{MEM0_API_BASE}/projects/{MEM0_PROJECT_ID}/webhooks/{webhook_id}",
            headers=headers
        )
        
        if response.status_code in [200, 204]:
            print(f"✓ Webhook {webhook_id} deleted successfully")
        else:
            print(f"✗ Could not delete webhook: {response.status_code}")
    
    except Exception as e:
        print(f"Error deleting webhook: {e}")

def test_webhook():
    """Test webhook endpoint by sending a test event"""
    if not MEM0_WEBHOOK_URL:
        print("✗ MEM0_WEBHOOK_URL not set")
        return
    
    test_payload = {
        "event": "test",
        "timestamp": "2024-01-20T12:00:00Z",
        "data": {
            "message": "Test webhook event"
        }
    }
    
    try:
        response = requests.post(
            MEM0_WEBHOOK_URL,
            json=test_payload,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            print("✓ Webhook endpoint is reachable")
            print(f"Response: {response.json()}")
        else:
            print(f"⚠ Webhook returned status: {response.status_code}")
    
    except Exception as e:
        print(f"✗ Webhook test failed: {e}")
        print("Make sure your server is running and accessible")

if __name__ == "__main__":
    print("=== Mem0 Webhook Setup ===\n")
    
    # Verify environment variables
    required_vars = ["MEM0_API_KEY", "MEM0_ORG_ID", "MEM0_PROJECT_ID"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"✗ Missing environment variables: {', '.join(missing_vars)}")
        print("Please set them in your .env file")
        exit(1)
    
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "list":
            list_webhooks()
        elif command == "delete" and len(sys.argv) > 2:
            delete_webhook(sys.argv[2])
        elif command == "test":
            test_webhook()
        else:
            print("Usage:")
            print("  python setup_mem0_webhook.py          # Register webhook")
            print("  python setup_mem0_webhook.py list     # List webhooks")
            print("  python setup_mem0_webhook.py delete <id>  # Delete webhook")
            print("  python setup_mem0_webhook.py test     # Test webhook")
    else:
        # Default: register webhook
        register_webhook()
        print("\nListing current webhooks...")
        list_webhooks()
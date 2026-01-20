import os
import time
from typing import List, Dict, Any, Optional
from mem0 import MemoryClient



def _extract_memory_id(result: Any) -> Optional[str]:
    if isinstance(result, dict):
        if result.get("id"):
            return result["id"]
        if result.get("memory_id"):
            return result["memory_id"]
        if isinstance(result.get("memory"), dict) and result["memory"].get("id"):
            return result["memory"]["id"]
        if isinstance(result.get("data"), dict) and result["data"].get("id"):
            return result["data"]["id"]
        if isinstance(result.get("memories"), list) and result["memories"]:
            first = result["memories"][0]
            if isinstance(first, dict) and first.get("id"):
                return first["id"]
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict) and first.get("id"):
            return first["id"]
    return None

def _is_empty_add_response(result: Any) -> bool:
    return result == [] or result is None

def _apply_category_metadata(metadata: Dict[str, Any], category: str) -> Dict[str, Any]:
    updated = dict(metadata or {})
    updated["mem0_category"] = category
    return updated
from dotenv import load_dotenv

load_dotenv()

class Mem0Store:
    """Enhanced Mem0 wrapper with category-based search and filtering"""
    
    def __init__(self):
        self.client = MemoryClient(
            api_key=os.getenv("MEM0_API_KEY"),
            org_id=os.getenv("MEM0_ORG_ID"),
            project_id=os.getenv("MEM0_PROJECT_ID")
        )
        self.debug = os.getenv("MEM0_DEBUG", "").lower() in ("1", "true", "yes", "on")
        self.add_retry_count = 0
        self.add_retry_delay = 0.0
        self.store_conversation = os.getenv("MEM0_STORE_CONVERSATION", "1").lower() in ("1", "true", "yes", "on")
        
        # Category constants
        self.CAT_REMINDER_ACTIVE = "reminder_active"
        self.CAT_REMINDER_ARCHIVED = "reminder_archived"
        self.CAT_USER_PREFS = "user_prefs"
        self.CAT_CONVERSATION = "conversation"
        self.CAT_USER_BEHAVIOR = "user_behavior"

    def _add_with_retry(self, **kwargs):
        result = self.client.add(**kwargs)
        if self.debug and _is_empty_add_response(result):
            print("Mem0 add returned empty response")
        return result
    
    def search_reminders(
        self, 
        query: str, 
        user_id: str = "default_user",
        active_only: bool = True,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search reminders using category filtering.
        Mem0 v2 doesn't support metadata filters, so we use categories.
        """
        category = self.CAT_REMINDER_ACTIVE if active_only else self.CAT_REMINDER_ARCHIVED
        
        try:
            results = self.client.search(
                query=query,
                user_id=user_id,
                categories=[category],
                limit=limit
            )
            if not results:
                results = self.client.search(
                    query=query,
                    user_id=user_id,
                    limit=limit
                )
            
            memories = []
            
            for item in results:
                memory_data = {
                    "id": item.get("id"),
                    "memory": item.get("memory"),
                    "metadata": item.get("metadata", {}),
                    "categories": item.get("categories", []),
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "score": item.get("score", 0)
                }

                mem_category = memory_data["metadata"].get("mem0_category")
                if mem_category and mem_category != category:
                    continue
                
                memories.append(memory_data)
            
            return memories
            
        except Exception as e:
            print(f"Mem0 search error: {e}")
            return []
    
    def search_preferences(
        self,
        query: str,
        user_id: str = "default_user",
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search user preferences"""
        try:
            results = self.client.search(
                query=query,
                user_id=user_id,
                categories=[self.CAT_USER_PREFS],
                    async_mode=False,
                limit=limit
            )
            
            return [
                {
                    "id": item.get("id"),
                    "memory": item.get("memory"),
                    "metadata": item.get("metadata", {}),
                    "score": item.get("score", 0)
                }
                for item in results
            ]
        except Exception as e:
            print(f"Mem0 preference search error: {e}")
            return []
    
    def search_conversation(
        self,
        query: str,
        user_id: str = "default_user",
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search conversation history"""
        try:
            results = self.client.search(
                query=query,
                user_id=user_id,
                categories=[self.CAT_CONVERSATION],
                async_mode=False,
                limit=limit
            )
            
            return [
                {
                    "id": item.get("id"),
                    "memory": item.get("memory"),
                    "created_at": item.get("created_at"),
                    "score": item.get("score", 0)
                }
                for item in results
            ]
        except Exception as e:
            print(f"Mem0 conversation search error: {e}")
            return []
    
    def search_behavior(
        self,
        query: str,
        user_id: str = "default_user",
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search behavior summaries"""
        try:
            results = self.client.search(
                query=query,
                user_id=user_id,
                categories=[self.CAT_USER_BEHAVIOR],
                async_mode=False,
                limit=limit
            )

            return [
                {
                    "id": item.get("id"),
                    "memory": item.get("memory"),
                    "metadata": item.get("metadata", {}),
                    "score": item.get("score", 0)
                }
                for item in results
            ]
        except Exception as e:
            print(f"Mem0 behavior search error: {e}")
            return []

    def upsert_active_reminder(
        self,
        text: str,
        user_id: str = "default_user",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add or update an active reminder in Mem0"""
        metadata = _apply_category_metadata(metadata or {}, self.CAT_REMINDER_ACTIVE)

        reminder_id = metadata.get("reminder_id")
        existing_memory_id = None

        if reminder_id:
            try:
                results = self.client.search(
                    query=f"reminder_id:{reminder_id}",
                    user_id=user_id,
                    categories=[self.CAT_REMINDER_ACTIVE],
                    limit=1
                )
                if results and len(results) > 0:
                    existing_memory_id = results[0].get("id")
            except Exception:
                pass

        try:
            if existing_memory_id:
                try:
                    self.client.update(
                        memory_id=existing_memory_id,
                        text=text,
                        metadata=metadata,
                        version="v2"
                    )
                    return existing_memory_id
                except TypeError:
                    self.client.update(
                        memory_id=existing_memory_id,
                        data=text
                    )
                    if metadata:
                        self.client.delete(existing_memory_id)
                    else:
                        return existing_memory_id

            result = self._add_with_retry(
                messages=[{"role": "user", "content": text}],
                user_id=user_id,
                metadata=metadata,
                categories=[self.CAT_REMINDER_ACTIVE],
                async_mode=False,
                version="v2",
            )
            if self.debug:
                print("Mem0 add (active) payload:", {
                    "user_id": user_id,
                    "categories": [self.CAT_REMINDER_ACTIVE],
                    "metadata": metadata
                })
                print("Mem0 add (active) raw response:", result)
            mem_id = _extract_memory_id(result)
            if not mem_id:
                print("Mem0 add response (active):", result)
            return mem_id
        except Exception as e:
            print(f"Mem0 upsert active reminder error: {e}")
            return None


    def upsert_archived_reminder(
            self,
            text: str,
            user_id: str = "default_user",
            metadata: Optional[Dict[str, Any]] = None
        ) -> str:
            """Archive a reminder (move from active to archived category)"""
            metadata = _apply_category_metadata(metadata or {}, self.CAT_REMINDER_ARCHIVED)

            reminder_id = metadata.get("reminder_id")
            if reminder_id:
                try:
                    results = self.client.search(
                        query=f"reminder_id:{reminder_id}",
                        user_id=user_id,
                        categories=[self.CAT_REMINDER_ACTIVE],
                        limit=1
                    )
                    if results and len(results) > 0:
                        self.client.delete(results[0].get("id"))
                except Exception:
                    pass

            try:
                result = self._add_with_retry(
                    messages=[{"role": "user", "content": text}],
                    user_id=user_id,
                    metadata=metadata,
                    categories=[self.CAT_REMINDER_ARCHIVED],
                    async_mode=False,
                    version="v2",
                )
                if self.debug:
                    print("Mem0 add (archived) payload:", {
                        "user_id": user_id,
                        "categories": [self.CAT_REMINDER_ARCHIVED],
                        "metadata": metadata
                    })
                    print("Mem0 add (archived) raw response:", result)
                mem_id = _extract_memory_id(result)
                if not mem_id:
                    print("Mem0 add response (archived):", result)
                return mem_id
            except Exception as e:
                print(f"Mem0 archive reminder error: {e}")
                return None


    def upsert_preference(
            self,
            text: str,
            user_id: str = "default_user",
            metadata: Optional[Dict[str, Any]] = None
        ) -> str:
            """Add or update a user preference"""
            metadata = _apply_category_metadata(metadata or {}, self.CAT_USER_PREFS)

            pref_key = metadata.get("pref_key")
            existing_memory_id = None

            if pref_key:
                try:
                    results = self.client.search(
                        query=f"pref_key:{pref_key}",
                        user_id=user_id,
                        categories=[self.CAT_USER_PREFS],
                        limit=1
                    )
                    if results and len(results) > 0:
                        existing_memory_id = results[0].get("id")
                except Exception:
                    pass

            try:
                if existing_memory_id:
                    self.client.update(
                        memory_id=existing_memory_id,
                        text=text,
                        metadata=metadata,
                        version="v2"
                    )
                    return existing_memory_id

                result = self._add_with_retry(
                    messages=[{"role": "user", "content": text}],
                    user_id=user_id,
                    metadata=metadata,
                    categories=[self.CAT_USER_PREFS],
                    async_mode=False,
                    version="v2",
                )
                if self.debug:
                    print("Mem0 add (prefs) payload:", {
                        "user_id": user_id,
                        "categories": [self.CAT_USER_PREFS],
                        "metadata": metadata
                    })
                    print("Mem0 add (prefs) raw response:", result)
                mem_id = _extract_memory_id(result)
                if not mem_id:
                    print("Mem0 add response (prefs):", result)
                return mem_id
            except Exception as e:
                print(f"Mem0 upsert preference error: {e}")
                return None


    def upsert_behavior_summary(
        self,
        text: str,
        user_id: str = "default_user",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add or update user behavior summary"""
        metadata = _apply_category_metadata(metadata or {}, self.CAT_USER_BEHAVIOR)
        metadata.setdefault("type", "behavior_summary")

        existing_memory_id = None
        try:
            results = self.client.search(
                query="behavior_summary",
                user_id=user_id,
                categories=[self.CAT_USER_BEHAVIOR],
                limit=1
            )
            if results and len(results) > 0:
                existing_memory_id = results[0].get("id")
        except Exception:
            pass

        try:
            if existing_memory_id:
                self.client.update(
                    memory_id=existing_memory_id,
                    text=text,
                    metadata=metadata,
                    version="v2"
                )
                return existing_memory_id

            result = self._add_with_retry(
                messages=[{"role": "user", "content": text}],
                user_id=user_id,
                metadata=metadata,
                categories=[self.CAT_USER_BEHAVIOR],
                async_mode=False,
                version="v2",
            )
            if self.debug:
                print("Mem0 add (behavior) payload:", {
                    "user_id": user_id,
                    "categories": [self.CAT_USER_BEHAVIOR],
                    "metadata": metadata
                })
                print("Mem0 add (behavior) raw response:", result)
            mem_id = _extract_memory_id(result)
            if not mem_id:
                print("Mem0 add response (behavior):", result)
            return mem_id
        except Exception as e:
            print(f"Mem0 upsert behavior error: {e}")
            return None

    def add_conversation(
        self,
        text: str,
        user_id: str = "default_user",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a conversation turn to memory"""
        if not self.store_conversation:
            if self.debug:
                print("Mem0 conversation storage disabled by MEM0_STORE_CONVERSATION")
            return None
        metadata = _apply_category_metadata(metadata or {}, self.CAT_CONVERSATION)
        metadata["timestamp"] = int(time.time())

        try:
            result = self._add_with_retry(
                messages=[{"role": "user", "content": text}],
                user_id=user_id,
                metadata=metadata,
                categories=[self.CAT_CONVERSATION],
                async_mode=False,
                version="v2",
            )
            if self.debug:
                print("Mem0 add (conversation) payload:", {
                    "user_id": user_id,
                    "categories": [self.CAT_CONVERSATION],
                    "metadata": metadata
                })
                print("Mem0 add (conversation) raw response:", result)
            mem_id = _extract_memory_id(result)
            if not mem_id:
                print("Mem0 add response (conversation):", result)
            return mem_id
        except Exception as e:
            print(f"Mem0 add conversation error: {e}")
            return None

    def delete_memory(self, memory_id: str) -> bool:
            """Delete a memory by ID"""
            try:
                self.client.delete(memory_id)
                return True
            except Exception as e:
                print(f"Mem0 delete error: {e}")
                return False
        
    def get_all_memories(
            self,
            user_id: str = "default_user",
            categories: Optional[List[str]] = None
        ) -> List[Dict[str, Any]]:
            """Get all memories for a user, optionally filtered by categories"""
            try:
                try:
                    results = self.client.get_all(
                        filters={"AND": [{"user_id": user_id}]},
                        version="v2"
                    )
                except TypeError:
                    try:
                        results = self.client.get_all(
                            user_id=user_id,
                            categories=categories
                        )
                    except TypeError:
                        results = self.client.get_all(
                            user_id=user_id
                        )
                
                if isinstance(results, str):
                    try:
                        results = json.loads(results)
                    except Exception:
                        if self.debug:
                            print("Mem0 get all returned non-JSON string:", results)
                        return []
                if not isinstance(results, list):
                    if self.debug:
                        print("Mem0 get all returned unexpected type:", type(results))
                    return []

                memories = [
                    {
                        "id": item.get("id"),
                        "memory": item.get("memory"),
                        "metadata": item.get("metadata", {}),
                        "categories": item.get("categories", []),
                        "created_at": item.get("created_at"),
                        "updated_at": item.get("updated_at")
                    }
                    for item in results
                    if isinstance(item, dict)
                ]
                if categories:
                    category_set = set(categories)
                    return [
                        m for m in memories
                        if m.get("metadata", {}).get("mem0_category") in category_set
                    ]
                return memories
            except Exception as e:
                print(f"Mem0 get all error: {e}")
                return []

    def get_rescheduled_active_reminders(
            self,
            user_id: str = "default_user",
            limit: int = 50
        ) -> List[Dict[str, Any]]:
            """Get active reminders that have been rescheduled at least once."""
            memories = self.get_all_memories(
                user_id=user_id,
                categories=[self.CAT_REMINDER_ACTIVE]
            )
            filtered = []
            for mem in memories:
                metadata = mem.get("metadata", {}) or {}
                reschedule_count = metadata.get("reschedule_count", 0) or 0
                if reschedule_count > 0 or metadata.get("last_rescheduled_at_epoch"):
                    filtered.append(mem)

            filtered.sort(
                key=lambda item: (item.get("metadata", {}) or {}).get("last_rescheduled_at_epoch") or 0,
                reverse=True
            )
            if limit:
                return filtered[:limit]
            return filtered

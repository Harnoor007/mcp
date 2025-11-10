from datetime import datetime
import json
import logging
import os
from typing import Any, Dict, Optional


import redis


logger = logging.getLogger(__name__)

class RedisSessionManager:
    def __init__(self, host='redis', port=6379, db=0):
        host = host or os.getenv("REDIS_HOST", "redis")
        port = int(port or os.getenv("REDIS_PORT", 6379))
        db = int(db or os.getenv("REDIS_DB", 0))
        try:
            self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self.client.ping()
            logger.info("Connected to Redis for session management. session server")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Could not connect to Redis: {e}. Sessions redis will not be persisted.")
            self.client = None

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        session_data = self.client.get(f"session:{session_id}")
        if session_data:
            session_dict = json.loads(session_data)
            if 'created_at' in session_dict and session_dict['created_at']:
                session_dict['created_at'] = datetime.fromisoformat(session_dict['created_at'])
            if 'last_accessed' in session_dict and session_dict['last_accessed']:
                session_dict['last_accessed'] = datetime.fromisoformat(session_dict['last_accessed'])
            return session_dict
        return None

    def set_session(self, session_id: str, session_data: Dict[str, Any], expiry: Optional[int] = None):
        if not self.client:
            return
        # Convert datetime objects to isoformat strings for JSON serialization
        session_copy = session_data.copy()
        if 'created_at' in session_copy and isinstance(session_copy['created_at'], datetime):
            session_copy['created_at'] = session_copy['created_at'].isoformat()
        if 'last_accessed' in session_copy and isinstance(session_copy['last_accessed'], datetime):
            session_copy['last_accessed'] = session_copy['last_accessed'].isoformat()
        self.client.set(f"session:{session_id}", json.dumps(session_copy), ex=86400)  # 24-hour TTL

    def delete_session(self, session_id: str):
        if not self.client:
            return
        self.client.delete(f"session:{session_id}")

    def exists_session(self, session_id: str) -> bool:
        if not self.client:
            return False
        return self.client.exists(f"session:{session_id}") > 0

    def count_session(self) -> int:
        if not self.client:
            return 0
        return len(self.client.keys("session:*"))


_redis_client = RedisSessionManager()

def get_redis_client() -> RedisSessionManager:
    """Return the global RedisSessionManager instance"""
    return _redis_client
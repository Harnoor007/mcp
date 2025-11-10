"""Session persistence service for MCP server

This module provides Redis-based session persistence to survive MCP subprocess restarts.
Since Langflow's STDIO MCP client creates new subprocess for each tool call,
we need to persist session state to a central store like Redis.
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging

from ..models.session import Session
from ..utils.logger import get_logger
from src.redis_service import get_redis_client

logger = get_logger(__name__)


class SessionPersistence:
    """Handles Redis-based session persistence for MCP server"""

    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize session persistence service

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
        """
        self.redis_client = get_redis_client()
        self.session_timeout = timedelta(hours=24)  # Sessions expire after 24 hours
        logger.info(f"SessionPersistence 2 initialized with Redis at: {self.redis_client.client.connection_pool.connection_kwargs.get('host')}:{self.redis_client.client.connection_pool.connection_kwargs.get('port')}")

    def get_session(self, session_id: Optional[str] = None) -> Session:
        """
        Get or create session with persistence

        Args:
            session_id: Optional session ID to retrieve or create with

        Returns:
            Session object (loaded from Redis or newly created)
        """
        if session_id:
            # Try to load existing session
            session = self._load_from_redis(session_id)
            if session and self._is_valid(session):
                session.update_access_time()
                self._save_to_redis(session)
                logger.debug(f"[MCP-Session] Loaded existing session: {session_id}")
                return session

            # Create new session with provided ID
            session = Session(session_id=session_id)
            self._save_to_redis(session)
            logger.info(f"[MCP-Session] Created new session with ID: {session_id}")
            return session

        # Create session with auto-generated ID
        session = Session()
        self._save_to_redis(session)
        logger.info(f"[MCP-Session] Created new session: {session.session_id}")
        return session

    def save_session(self, session: Session) -> bool:
        """
        Save session to Redis

        Args:
            session: Session to save

        Returns:
            True if successful
        """
        try:
            session.update_access_time()
            return self._save_to_redis(session)
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")
            return False

    def delete_session(self, session_id: str) -> bool:
        """
        Delete session from Redis

        Args:
            session_id: Session ID to delete

        Returns:
            True if successful
        """
        try:
            self.redis_client.delete_session(session_id)
            logger.info(f"[MCP-Session] Deleted session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    def cleanup_expired(self) -> int:
        """
        Clean up expired sessions (Redis handles this automatically with TTL)
        This method can be used for manual cleanup if needed.

        Returns:
            Number of sessions cleaned up
        """
        cleaned = 0
        # RedisSessionManager sets TTL, so explicit cleanup is mostly for sessions without TTL
        # or if Redis is not configured to expire keys automatically.
        # This implementation assumes RedisSessionManager handles TTL.
        # If there are keys without TTL, they would need to be handled here.
        # For now, we'll rely on Redis's built-in expiration.
        logger.info("[MCP-Session] Redis handles session expiration automatically. Manual cleanup skipped.")
        return cleaned

    def list_sessions(self) -> List[str]:
        """
        List all session IDs

        Returns:
            List of session IDs
        """
        session_ids = []
        # Assuming RedisSessionManager stores keys as 'session:{session_id}'
        for key in self.redis_client.client.scan_iter("session:*"):
            session_ids.append(key.decode('utf-8').split(':', 1)[1])
        return sorted(session_ids)

    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get summary of session without loading full object

        Args:
            session_id: Session ID to summarize

        Returns:
            Summary dictionary or None if not found
        """
        try:
            session_data = self.redis_client.get_session(session_id)
            if not session_data:
                return None

            return {
                'session_id': session_data.get('session_id'),
                'created_at': session_data.get('created_at'),
                'last_accessed': session_data.get('last_accessed'),
                'cart_items': len(session_data.get('cart', {}).get('items', [])),
                'total_value': session_data.get('cart', {}).get('total_value', 0),
                'checkout_stage': session_data.get('checkout_state', {}).get('stage'),
                'transaction_id': session_data.get('checkout_state', {}).get('transaction_id')
            }
        except Exception as e:
            logger.error(f"Failed to get session summary for {session_id}: {e}")
            return None

    def _is_valid(self, session: Session) -> bool:
        """
        Check if session is still valid (not strictly needed with Redis TTL, but good for consistency)

        Args:
            session: Session to check

        Returns:
            True if valid
        """
        age = datetime.utcnow() - session.last_accessed
        return age < self.session_timeout

    def _save_to_redis(self, session: Session) -> bool:
        """
        Save session to Redis

        Args:
            session: Session to save

        Returns:
            True if successful
        """
        try:
            session_dict = session.to_dict()
            self.redis_client.set_session(session.session_id, session_dict, ex=int(self.session_timeout.total_seconds()))
            logger.debug(f"[MCP-Session] Saved session to Redis: {session.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id} to Redis: {e}")
            return False

    def _load_from_redis(self, session_id: str) -> Optional[Session]:
        """
        Load session from Redis

        Args:
            session_id: Session ID to load

        Returns:
            Session object or None if not found
        """
        try:
            session_data = self.redis_client.get_session(session_id)
            if not session_data:
                logger.debug(f"[MCP-Session] Session not found in Redis: {session_id}")
                return None

            return Session.from_dict(session_data)
        except Exception as e:
            logger.error(f"Failed to load session {session_id} from Redis: {e}")
            return None


# Singleton instance for MCP server
_session_persistence: Optional[SessionPersistence] = None


def get_session_persistence() -> SessionPersistence:
    """Get singleton SessionPersistence instance for MCP server"""
    global _session_persistence
    if _session_persistence is None:
        _session_persistence = SessionPersistence(os.getenv("REDIS_URL"))
    return _session_persistence

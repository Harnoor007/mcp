"""Session service for centralized session management using Redis"""

import asyncio
import os
import json
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import logging

from ..models.session import Session
from ..utils.logger import get_logger

from src.redis_service import get_redis_client

logger = get_logger(__name__)



class SessionService:
    """Service for managing user sessions with Redis"""

    def __init__(self):
        """
        Initialize session service

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
        """
        try:
            self.redis_client = get_redis_client()
            self.session_timeout = timedelta(hours=24)
            self._lock = asyncio.Lock()
            logger.info(f"SessionService 3 initialized with Redis at: {self.redis_client.client.connection_pool.connection_kwargs.get('host')}:{self.redis_client.client.connection_pool.connection_kwargs.get('port')}")
        except Exception as e:
            logger.error(f"Could not initialize SessionService due to Redis connection error: {e}. Sessions will not be persisted.")    
    def get_or_create(self, session_id: Optional[str] = None) -> Session:
        """
        Get existing session or create new one

        Args:
            session_id: Optional session ID to retrieve or create with

        Returns:
            Session object
        """
        if session_id:
            session = self.get(session_id)
            if session:
                return session
            return self.create_with_id(session_id)

        return self.create()

    def get(self, session_id: str) -> Optional[Session]:
        """
        Get session by ID
        Args:
            session_id: Session ID to retrieve

        Returns:
            Session object or None if not found/expired
        """
        session = self._load_from_redis(session_id)
        if session and self._is_valid(session):
            session.update_access_time()
            return session

        return None

    def create(self, session_id: Optional[str] = None) -> Session:
        """
        Create new session

        Args:
            session_id: Optional external session ID to use

        Returns:
            New Session object
        """
        if session_id:
            return self.create_with_id(session_id)

        session = Session()
        self._save_to_redis(session)
        logger.info(f"Created new session: {session.session_id}")
        return session

    def create_with_id(self, session_id: str) -> Session:
        """
        Create session with provided external ID

        Args:
            session_id: External session ID to use

        Returns:
            New Session object with provided ID
        """
        existing_session = self.get(session_id)
        if existing_session:
            logger.info(f"Session with external ID already exists: {session_id}")
            return existing_session

        session = Session(session_id=session_id)
        self._save_to_redis(session)
        logger.info(f"Created new session with external ID: {session_id}")
        return session

    def update(self, session: Session) -> bool:
        """
        Update session

        Args:
            session: Session to update

        Returns:
            True if successful
        """
        try:
            session.update_access_time()
            self._save_to_redis(session)
            return True
        except Exception as e:
            logger.error(f"Failed to update session {session.session_id}: {e}")
            return False

    def delete(self, session_id: str) -> bool:
        """
        Delete session

        Args:
            session_id: Session ID to delete

        Returns:
            True if successful
        """
        try:
            self.redis_client.delete_session(f"session:{session_id}")
            logger.info(f"Deleted session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    def cleanup_expired(self) -> int:
        """
        Redis handles the main expiration. This method is a no-op.

        Returns:
            0
        """
        logger.info("Redis handles session expiration automatically. Cleanup is not needed.")
        return 0

    def _is_valid(self, session: Session) -> bool:
        """
        Check if session is still valid

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
            # Convert Session object to dictionary for RedisSessionManager
            session_dict = session.to_dict()
            self.redis_client.set_session(f"session:{session.session_id}", session_dict, ex=int(self.session_timeout.total_seconds()))
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
            session_data = self.redis_client.get_session(f"session:{session_id}")
            if not session_data:
                return None
            # return Session.from_dict(session_data)
            return Session.from_dict(session_data)
        except Exception as e:
            logger.error(f"Failed to load session {session_id} from Redis: {e}")
            return None

    def get_session_summary(self, session: Session) -> Dict[str, Any]:
        """
        Get summary of session state

        Args:
            session: Session to summarize

        Returns:
            Summary dictionary
        """
        return {
            'session_id': session.session_id,
            'cart': {
                'items_count': session.cart.total_items,
                'total_value': session.cart.total_value,
                'items': [item.to_dict() for item in session.cart.items]
            },
            'checkout': {
                'stage': session.checkout_state.stage.value,
                'has_delivery_info': session.checkout_state.delivery_info is not None,
                'transaction_id': session.checkout_state.transaction_id
            },
            'preferences': session.preferences.to_dict(),
            'age': str(datetime.utcnow() - session.created_at)
        }


# Singleton instance
_session_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """Get singleton SessionService instance"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service

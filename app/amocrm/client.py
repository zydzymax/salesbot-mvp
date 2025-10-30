"""
AmoCRM API Client with rate limiting and token management
Handles all interactions with AmoCRM API
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import json

import httpx
import structlog

from ..config import get_settings
from ..utils.security import SecurityManager
from ..database.crud import TokenStorageCRUD
from ..database.init_db import db_manager

logger = structlog.get_logger("salesbot.amocrm.client")


class RateLimiter:
    """Simple rate limiter for API calls"""
    
    def __init__(self, calls_per_second: int = 7):
        self.calls_per_second = calls_per_second
        self.calls = []
    
    async def acquire(self):
        """Wait if necessary to respect rate limits"""
        now = datetime.utcnow()
        # Remove calls older than 1 second
        self.calls = [call_time for call_time in self.calls 
                     if (now - call_time).total_seconds() < 1.0]
        
        if len(self.calls) >= self.calls_per_second:
            sleep_time = 1.0 - (now - self.calls[0]).total_seconds()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                return await self.acquire()
        
        self.calls.append(now)


class AmoCRMError(Exception):
    """AmoCRM API error"""
    pass


class AmoCRMClient:
    """Asynchronous AmoCRM API client"""
    
    def __init__(self):
        self.settings = get_settings()
        self.rate_limiter = RateLimiter(self.settings.amocrm_rate_limit)
        self.security = SecurityManager()
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        
    async def _get_stored_tokens(self):
        """Load tokens from database"""
        async with db_manager.get_session() as session:
            encrypted_access = await TokenStorageCRUD.get_token(
                session, "amocrm", "access_token"
            )
            encrypted_refresh = await TokenStorageCRUD.get_token(
                session, "amocrm", "refresh_token"
            )

            if encrypted_access:
                try:
                    self.access_token = self.security.decrypt_data(encrypted_access)
                except Exception as e:
                    logger.warning(f"Failed to decrypt access token, will use from config: {e}")
                    self.access_token = None
            if encrypted_refresh:
                try:
                    self.refresh_token = self.security.decrypt_data(encrypted_refresh)
                except Exception as e:
                    logger.warning(f"Failed to decrypt refresh token, will use from config: {e}")
                    self.refresh_token = None
    
    async def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int):
        """Save tokens to database"""
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 60)
        
        async with db_manager.get_session() as session:
            await TokenStorageCRUD.save_token(
                session=session,
                service="amocrm",
                token_type="access_token",
                encrypted_token=self.security.encrypt_data(access_token),
                expires_at=self.token_expires_at
            )
            await TokenStorageCRUD.save_token(
                session=session,
                service="amocrm",
                token_type="refresh_token",
                encrypted_token=self.security.encrypt_data(refresh_token)
            )
    
    async def _refresh_access_token(self) -> bool:
        """Refresh access token using refresh token"""
        if not self.refresh_token:
            await self._get_stored_tokens()
        
        if not self.refresh_token:
            logger.error("No refresh token available")
            return False
        
        url = f"{self.settings.amocrm_base_url}/oauth2/access_token"
        data = {
            "client_id": self.settings.amocrm_client_id,
            "client_secret": self.settings.amocrm_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "redirect_uri": self.settings.amocrm_redirect_uri
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=data)
                response.raise_for_status()
                
                token_data = response.json()
                await self._save_tokens(
                    access_token=token_data["access_token"],
                    refresh_token=token_data["refresh_token"],
                    expires_in=token_data["expires_in"]
                )
                
                logger.info("Access token refreshed successfully")
                return True
                
            except httpx.HTTPError as e:
                logger.error(f"Failed to refresh token: {e}")
                return False
    
    async def _ensure_valid_token(self):
        """Ensure we have a valid access token"""
        if not self.access_token:
            await self._get_stored_tokens()
        
        # Check if token is about to expire
        if (self.token_expires_at and 
            datetime.utcnow() >= self.token_expires_at - timedelta(minutes=5)):
            await self._refresh_access_token()
        
        if not self.access_token:
            # Try to use initial tokens from config
            if self.settings.amocrm_access_token:
                self.access_token = self.settings.amocrm_access_token
                if self.settings.amocrm_refresh_token:
                    await self._save_tokens(
                        access_token=self.settings.amocrm_access_token,
                        refresh_token=self.settings.amocrm_refresh_token,
                        expires_in=86400  # 24 hours default
                    )
            else:
                raise AmoCRMError("No access token available")
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        retry_count: int = 0
    ) -> Dict[str, Any]:
        """Make authenticated request to AmoCRM API"""
        await self.rate_limiter.acquire()
        await self._ensure_valid_token()
        
        url = f"{self.settings.amocrm_base_url}/api/v4/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=data
                )
                
                logger.info(
                    f"AmoCRM API request",
                    method=method,
                    endpoint=endpoint,
                    status_code=response.status_code
                )
                
                if response.status_code == 401 and retry_count < 2:
                    # Token expired, refresh and retry
                    if await self._refresh_access_token():
                        return await self._make_request(
                            method, endpoint, params, data, retry_count + 1
                        )
                
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPError as e:
                logger.error(f"AmoCRM API error: {e}")
                raise AmoCRMError(f"API request failed: {e}")
    
    async def get_events(
        self,
        limit: int = 100,
        page: int = 1,
        filter_params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Get events from AmoCRM (includes calls)"""
        params = {
            "limit": min(limit, 100),  # AmoCRM events limit
            "page": page
        }

        if filter_params:
            params.update(filter_params)

        return await self._make_request("GET", "events", params=params)

    async def get_calls(
        self,
        limit: int = 50,
        page: int = 1,
        filter_params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Get calls from AmoCRM via events API"""
        # Use events API filtered for call events
        events_filter = {
            "filter[type][]": ["incoming_call", "outgoing_call"]
        }

        if filter_params:
            events_filter.update(filter_params)

        return await self.get_events(limit=limit, page=page, filter_params=events_filter)
    
    async def get_call_details(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed call information"""
        try:
            result = await self._make_request("GET", f"calls/{call_id}")
            return result
        except AmoCRMError:
            return None
    
    async def get_lead(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Get lead information"""
        try:
            result = await self._make_request("GET", f"leads/{lead_id}")
            return result
        except AmoCRMError:
            return None

    async def get_leads(
        self,
        limit: int = 50,
        page: int = 1,
        filter_params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Get leads from AmoCRM"""
        params = {
            "limit": min(limit, 250),  # AmoCRM limit
            "page": page,
            "with": "contacts"  # Include contacts info
        }

        if filter_params:
            params.update(filter_params)

        return await self._make_request("GET", "leads", params=params)

    async def get_lead_calls(self, lead_id: str) -> List[Dict[str, Any]]:
        """Get all calls for a specific lead"""
        try:
            # Get calls filtered by entity_id (lead)
            params = {
                "filter[entity_id]": lead_id,
                "filter[entity_type]": "leads",
                "limit": 250
            }

            result = await self._make_request("GET", "calls", params=params)
            return result.get("_embedded", {}).get("calls", [])
        except AmoCRMError:
            return []

    async def get_lead_notes(
        self,
        lead_id: str,
        limit: int = 250,
        note_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get notes for a specific lead"""
        try:
            params = {"limit": min(limit, 250)}

            # Filter by note types if specified
            if note_types:
                for note_type in note_types:
                    params[f"filter[note_type][]"] = note_type

            result = await self._make_request(
                "GET",
                f"leads/{lead_id}/notes",
                params=params
            )
            return result.get("_embedded", {}).get("notes", [])
        except AmoCRMError as e:
            logger.warning(f"Failed to get notes for lead {lead_id}: {e}")
            return []

    async def get_note_details(self, lead_id: str, note_id: str) -> Optional[Dict[str, Any]]:
        """Get specific note details"""
        try:
            result = await self._make_request(
                "GET",
                f"leads/{lead_id}/notes/{note_id}"
            )
            return result
        except AmoCRMError:
            return None

    async def update_lead_note(self, lead_id: str, note_text: str) -> bool:
        """Add note to lead"""
        try:
            data = [{
                "entity_id": int(lead_id),
                "entity_type": "leads",
                "note_type": "common",
                "params": {
                    "text": note_text
                }
            }]
            
            await self._make_request("POST", "leads/notes", data=data)
            return True
        except AmoCRMError:
            return False
    
    async def add_task(
        self,
        responsible_user_id: str,
        text: str,
        complete_till: datetime,
        entity_id: Optional[str] = None,
        entity_type: str = "leads"
    ) -> bool:
        """Add task in AmoCRM"""
        try:
            task_data = {
                "responsible_user_id": int(responsible_user_id),
                "text": text,
                "complete_till": int(complete_till.timestamp()),
                "task_type": 1  # Звонок
            }
            
            if entity_id:
                task_data["entity_id"] = int(entity_id)
                task_data["entity_type"] = entity_type
            
            await self._make_request("POST", "tasks", data=[task_data])
            return True
        except AmoCRMError:
            return False
    
    async def get_users(self) -> List[Dict[str, Any]]:
        """Get all users (managers)"""
        try:
            result = await self._make_request("GET", "users")
            return result.get("_embedded", {}).get("users", [])
        except AmoCRMError:
            return []
    
    async def download_call_recording(self, recording_url: str) -> Optional[bytes]:
        """Download call recording file"""
        await self.rate_limiter.acquire()

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            try:
                response = await client.get(recording_url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                logger.error(f"Failed to download recording: {e}")
                return None
    
    async def test_connection(self) -> bool:
        """Test AmoCRM connection"""
        try:
            await self._make_request("GET", "account")
            return True
        except AmoCRMError:
            return False


# Global client instance
amocrm_client = AmoCRMClient()
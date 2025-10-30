"""
AmoCRM webhook handlers
Process incoming webhooks for calls and leads
"""

from datetime import datetime
from typing import Dict, Any, Optional
import json

import structlog

from ..database.init_db import db_manager
from ..database.crud import CallCRUD, ManagerCRUD
from ..tasks.queue import task_queue
from .client import amocrm_client

logger = structlog.get_logger("salesbot.amocrm.webhooks")


class WebhookHandler:
    """Handle AmoCRM webhooks"""
    
    @staticmethod
    async def handle_call_add(webhook_data: Dict[str, Any]) -> bool:
        """Handle new call webhook"""
        try:
            calls_data = webhook_data.get("calls", {}).get("add", [])
            
            for call_data in calls_data:
                await WebhookHandler._process_new_call(call_data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling call_add webhook: {e}")
            return False
    
    @staticmethod
    async def handle_call_update(webhook_data: Dict[str, Any]) -> bool:
        """Handle call update webhook"""
        try:
            calls_data = webhook_data.get("calls", {}).get("update", [])
            
            for call_data in calls_data:
                await WebhookHandler._process_call_update(call_data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling call_update webhook: {e}")
            return False
    
    @staticmethod
    async def _process_new_call(call_data: Dict[str, Any]):
        """Process new call from webhook"""
        call_id = str(call_data.get("id"))
        responsible_user_id = str(call_data.get("responsible_user_id"))
        
        logger.info(f"Processing new call", call_id=call_id)
        
        async with db_manager.get_session() as session:
            # Check if call already exists
            existing_call = await CallCRUD.get_call_by_amocrm_id(session, call_id)
            if existing_call:
                logger.info(f"Call already exists", call_id=call_id)
                return
            
            # Get or create manager
            manager = await ManagerCRUD.get_manager_by_amocrm_id(
                session, responsible_user_id
            )
            
            if not manager:
                # Get manager info from AmoCRM
                users = await amocrm_client.get_users()
                user_info = next(
                    (u for u in users if str(u["id"]) == responsible_user_id), 
                    None
                )
                
                if user_info:
                    manager = await ManagerCRUD.create_manager(
                        session=session,
                        amocrm_user_id=responsible_user_id,
                        name=user_info.get("name", f"User {responsible_user_id}"),
                        email=user_info.get("email")
                    )
                    logger.info(f"Created new manager", manager_id=manager.id)
                else:
                    logger.error(f"Could not find user info", user_id=responsible_user_id)
                    return
            
            # Extract call details
            duration = call_data.get("duration", 0)
            entity_id = call_data.get("entity_id")
            phone = None
            
            # Try to extract phone from different sources
            if "source" in call_data:
                phone = call_data["source"].get("phone")
            elif "phone" in call_data:
                phone = call_data["phone"]
            
            # Create call record
            call = await CallCRUD.create_call(
                session=session,
                amocrm_call_id=call_id,
                manager_id=manager.id,
                amocrm_lead_id=str(entity_id) if entity_id else None,
                client_phone=phone,
                duration_seconds=duration
            )
            
            logger.info(f"Created call record", call_id=call.id)
            
        # Get detailed call info to check for recording
        await WebhookHandler._check_call_recording(call_id)
    
    @staticmethod
    async def _process_call_update(call_data: Dict[str, Any]):
        """Process call update from webhook"""
        call_id = str(call_data.get("id"))
        
        logger.info(f"Processing call update", call_id=call_id)
        
        # Check if recording became available
        await WebhookHandler._check_call_recording(call_id)
    
    @staticmethod
    async def _check_call_recording(call_id: str):
        """Check if call has recording and queue for processing"""
        # Get detailed call info
        call_details = await amocrm_client.get_call_details(call_id)
        
        if not call_details:
            logger.warning(f"Could not get call details", call_id=call_id)
            return
        
        # Check for recording
        recording_url = None
        if "recording" in call_details:
            recording_url = call_details["recording"].get("url")
        
        if recording_url:
            async with db_manager.get_session() as session:
                # Update call with recording URL
                call = await CallCRUD.get_call_by_amocrm_id(session, call_id)
                if call:
                    # Update the call with recording URL
                    # Note: We'd need to add this method to CallCRUD
                    # For now, we'll create the transcription task
                    
                    logger.info(f"Found recording for call", call_id=call_id)

                    # Queue transcription task (lazy import to avoid circular dependency)
                    from ..tasks.workers import TranscribeCallTask
                    task = TranscribeCallTask(
                        call_id=str(call.id),
                        recording_url=recording_url
                    )
                    await task_queue.add_task(task.execute, priority=5)
                    
                    logger.info(f"Queued transcription task", call_id=call.id)
        else:
            logger.info(f"No recording found for call", call_id=call_id)
    
    @staticmethod
    async def validate_webhook(
        webhook_data: Dict[str, Any],
        webhook_key: Optional[str] = None
    ) -> bool:
        """Validate webhook authenticity"""
        # Basic validation - in production, implement proper signature verification
        required_fields = ["account", "timestamp"]
        
        for field in required_fields:
            if field not in webhook_data:
                logger.warning(f"Missing required field in webhook: {field}")
                return False
        
        # Check timestamp (within last 5 minutes)
        webhook_timestamp = webhook_data.get("timestamp", 0)
        current_timestamp = int(datetime.utcnow().timestamp())
        
        if abs(current_timestamp - webhook_timestamp) > 300:  # 5 minutes
            logger.warning("Webhook timestamp too old")
            return False
        
        return True
    
    @staticmethod
    async def process_webhook(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main webhook processing entry point"""
        logger.info("Processing AmoCRM webhook", data_keys=list(webhook_data.keys()))
        
        # Validate webhook
        if not await WebhookHandler.validate_webhook(webhook_data):
            return {"status": "error", "message": "Invalid webhook"}
        
        results = {"processed": [], "errors": []}
        
        # Process different webhook types
        if "calls" in webhook_data:
            calls_data = webhook_data["calls"]
            
            # Handle new calls
            if "add" in calls_data:
                try:
                    success = await WebhookHandler.handle_call_add(webhook_data)
                    if success:
                        results["processed"].append("calls_add")
                    else:
                        results["errors"].append("calls_add")
                except Exception as e:
                    logger.error(f"Error processing call_add: {e}")
                    results["errors"].append(f"calls_add: {e}")
            
            # Handle call updates
            if "update" in calls_data:
                try:
                    success = await WebhookHandler.handle_call_update(webhook_data)
                    if success:
                        results["processed"].append("calls_update")
                    else:
                        results["errors"].append("calls_update")
                except Exception as e:
                    logger.error(f"Error processing call_update: {e}")
                    results["errors"].append(f"calls_update: {e}")
        
        return {
            "status": "success" if not results["errors"] else "partial",
            "results": results
        }
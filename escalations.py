from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
import structlog
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from app.core.database import get_db
from app.models import User, MentorSession, RiskEvent, Interaction
from app.services.twilio_service import twilio_service
from app.services.ai_service import ai_service
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter()

class EscalationRequest(BaseModel):
    user_id: str
    risk_level: str
    context: Dict[str, Any]
    priority: int = 5
    session_type: str = "chat"  # chat, voice, emergency

class TaskRouterWebhook(BaseModel):
    TaskSid: str
    WorkerSid: Optional[str] = None
    TaskAttributes: str
    EventType: str
    WorkspaceSid: str

@router.post("/escalations/create")
async def create_escalation(
    escalation: EscalationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Create manual escalation to human mentor"""
    
    logger.info(
        "escalation_requested",
        user_id=escalation.user_id,
        risk_level=escalation.risk_level,
        session_type=escalation.session_type
    )
    
    try:
        user = db.query(User).filter(User.user_id == escalation.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Create TaskRouter task
        task_sid = await twilio_service.create_taskrouter_task(
            user_id=escalation.user_id,
            priority=escalation.priority,
            risk_level=escalation.risk_level,
            context=escalation.context
        )
        
        if not task_sid:
            raise HTTPException(status_code=500, detail="Failed to create escalation task")
        
        # Create mentor session record
        mentor_session = MentorSession(
            user_id=user.user_id,
            mentor_id="pending",
            session_type=escalation.session_type,
            taskrouter_task_sid=task_sid,
            started_at=datetime.now(timezone.utc)
        )
        db.add(mentor_session)
        db.commit()
        
        # Send notification to user
        if escalation.session_type == "emergency":
            message = (
                "I'm immediately connecting you with emergency support. "
                "A trained mentor will be with you right away. Please stay with me."
            )
        else:
            message = (
                "I'm connecting you with one of our human mentors. "
                "They'll be with you shortly to provide additional support."
            )
        
        background_tasks.add_task(
            twilio_service.send_sms,
            user.phone,
            message
        )
        
        return {
            "task_sid": task_sid,
            "mentor_session_id": mentor_session.id,
            "status": "escalation_created"
        }
        
    except Exception as e:
        logger.error(
            "escalation_creation_failed",
            user_id=escalation.user_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to create escalation")

@router.post("/taskrouter/events")
async def handle_taskrouter_events(
    event: TaskRouterWebhook,
    db: Session = Depends(get_db)
):
    """Handle TaskRouter webhook events for mentor assignment and completion"""
    
    logger.info(
        "taskrouter_event_received",
        task_sid=event.TaskSid,
        event_type=event.EventType,
        worker_sid=event.WorkerSid
    )
    
    try:
        # Find mentor session by task SID
        mentor_session = db.query(MentorSession).filter(
            MentorSession.taskrouter_task_sid == event.TaskSid
        ).first()
        
        if not mentor_session:
            logger.warning(
                "mentor_session_not_found",
                task_sid=event.TaskSid
            )
            return {"status": "session_not_found"}
        
        user = db.query(User).filter(User.user_id == mentor_session.user_id).first()
        
        if event.EventType == "task.assigned":
            # Mentor has been assigned
            mentor_session.mentor_id = event.WorkerSid or "unknown"
            
            # Create Conversations room for text-based escalations
            if mentor_session.session_type in ["chat", "emergency"]:
                conversation_sid = await twilio_service.create_conversation(
                    user.phone,
                    event.WorkerSid,
                    event.TaskSid
                )
                
                if conversation_sid:
                    mentor_session.conversation_sid = conversation_sid
                    
                    # Send welcome message to conversation
                    await twilio_service.send_sms(
                        user.phone,
                        f"Hi {user.alias}, I'm here to support you. How can I help today?"
                    )
            
            logger.info(
                "mentor_assigned",
                task_sid=event.TaskSid,
                mentor_id=event.WorkerSid,
                user_id=str(mentor_session.user_id)
            )
        
        elif event.EventType == "task.completed":
            # Mentor session completed
            mentor_session.ended_at = datetime.now(timezone.utc)
            mentor_session.outcome = "completed"
            
            if mentor_session.started_at and mentor_session.ended_at:
                duration = mentor_session.ended_at - mentor_session.started_at
                mentor_session.duration_seconds = int(duration.total_seconds())
            
            # Send follow-up message
            follow_up_message = (
                f"Thank you for talking with our mentor today, {user.alias}. "
                "Remember, we're here for you 24/7. How are you feeling now?"
            )
            
            await twilio_service.send_sms(user.phone, follow_up_message)
            
            logger.info(
                "mentor_session_completed",
                task_sid=event.TaskSid,
                duration_seconds=mentor_session.duration_seconds,
                user_id=str(mentor_session.user_id)
            )
        
        elif event.EventType == "task.canceled":
            # Task was canceled (no available mentors, timeout, etc.)
            mentor_session.ended_at = datetime.now(timezone.utc)
            mentor_session.outcome = "canceled"
            
            # Send fallback support message
            fallback_message = (
                f"I'm sorry, {user.alias}, but no mentors are available right now. "
                "I'm still here for you. If this is an emergency, please call 988 or 911. "
                "Otherwise, let's continue talking - what's on your mind?"
            )
            
            await twilio_service.send_sms(user.phone, fallback_message)
            
            logger.warning(
                "mentor_task_canceled",
                task_sid=event.TaskSid,
                user_id=str(mentor_session.user_id)
            )
        
        db.commit()
        
        return {"status": "event_processed"}
        
    except Exception as e:
        logger.error(
            "taskrouter_event_error",
            task_sid=event.TaskSid,
            event_type=event.EventType,
            error=str(e)
        )
        return {"status": "error", "message": str(e)}

@router.post("/conversations/message")
async def handle_conversation_message(
    request: dict,
    db: Session = Depends(get_db)
):
    """Handle messages in Twilio Conversations (mentor chat)"""
    
    conversation_sid = request.get("ConversationSid")
    participant_sid = request.get("ParticipantSid")
    author = request.get("Author")
    body = request.get("Body")
    
    logger.info(
        "conversation_message_received",
        conversation_sid=conversation_sid,
        author=author,
        body_preview=body[:50] if body else None
    )
    
    try:
        # Find mentor session by conversation SID
        mentor_session = db.query(MentorSession).filter(
            MentorSession.conversation_sid == conversation_sid
        ).first()
        
        if not mentor_session:
            return {"status": "session_not_found"}
        
        # Log the conversation message
        direction = "inbound" if author != "system" else "outbound"
        handled_by = "mentor" if author != "system" else "system"
        
        interaction = Interaction(
            user_id=mentor_session.user_id,
            channel="Conversation",
            direction=direction,
            text=body,
            handled_by=handled_by,
            session_id=conversation_sid
        )
        db.add(interaction)
        db.commit()
        
        return {"status": "message_logged"}
        
    except Exception as e:
        logger.error(
            "conversation_message_error",
            conversation_sid=conversation_sid,
            error=str(e)
        )
        return {"status": "error"}

@router.get("/escalations/active")
async def get_active_escalations(db: Session = Depends(get_db)):
    """Get list of active mentor sessions for dashboard"""
    
    try:
        active_sessions = db.query(MentorSession).filter(
            MentorSession.ended_at.is_(None)
        ).order_by(MentorSession.started_at.desc()).all()
        
        sessions_data = []
        for session in active_sessions:
            user = db.query(User).filter(User.user_id == session.user_id).first()
            
            # Get latest risk event for context
            latest_risk = db.query(RiskEvent).filter(
                RiskEvent.user_id == session.user_id
            ).order_by(RiskEvent.created_at.desc()).first()
            
            sessions_data.append({
                "session_id": session.id,
                "task_sid": session.taskrouter_task_sid,
                "user_alias": user.alias if user else "Unknown",
                "session_type": session.session_type,
                "started_at": session.started_at.isoformat(),
                "mentor_id": session.mentor_id,
                "conversation_sid": session.conversation_sid,
                "risk_level": latest_risk.risk_level if latest_risk else "unknown",
                "duration_minutes": int((datetime.now(timezone.utc) - session.started_at).total_seconds() // 60)
            })
        
        return {
            "active_sessions": sessions_data,
            "total_count": len(sessions_data)
        }
        
    except Exception as e:
        logger.error(
            "get_active_escalations_error",
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to fetch active escalations")

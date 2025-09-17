from fastapi import APIRouter, Request, HTTPException, Depends, Form, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session
import structlog
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.database import get_db
from app.models import User, Interaction, RiskEvent, MentorSession
from app.services.twilio_service import twilio_service
from app.services.ai_service import ai_service

logger = structlog.get_logger()
router = APIRouter()

@router.post("/messages/inbound")
async def handle_inbound_message(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    MessageSid: str = Form(...),
    AccountSid: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle incoming SMS/WhatsApp messages from Twilio"""
    
    logger.info(
        "inbound_message_received",
        from_number=From,
        message_sid=MessageSid,
        body_preview=Body[:50]
    )
    
    try:
        # Find user by phone number
        user = db.query(User).filter(User.phone == From, User.is_active == True).first()
        
        if not user:
            # Handle unregistered user
            response_text = (
                "Hello! I'm ARC, your AI Recovery Companion. "
                "To get started, please visit our signup page or contact our team. "
                "If this is an emergency, please call 988 or your local emergency services."
            )
            
            logger.info(
                "unregistered_user_message",
                from_number=From,
                message_sid=MessageSid
            )
            
            # Send response via Twilio
            await twilio_service.send_sms(From, response_text)
            
            return Response(
                content=twilio_service.create_messaging_response(response_text),
                media_type="application/xml"
            )
        
        # Check for opt-out keywords
        if Body.upper().strip() in ["STOP", "UNSUBSCRIBE", "QUIT", "END"]:
            user.is_active = False
            db.commit()
            
            response_text = (
                "You have been unsubscribed from ARC messages. "
                "We're here if you need us again. Take care of yourself. "
                "Reply START to reactivate."
            )
            
            await twilio_service.send_sms(From, response_text)
            
            logger.info(
                "user_opted_out",
                user_id=str(user.user_id),
                phone=From
            )
            
            return Response(
                content=twilio_service.create_messaging_response(response_text),
                media_type="application/xml"
            )
        
        # Handle opt-in/reactivation
        if Body.upper().strip() in ["START", "YES", "SUBSCRIBE"]:
            if not user.is_active:
                user.is_active = True
                db.commit()
                
                response_text = (
                    f"Welcome back, {user.alias}! I'm here to support you. "
                    "How are you feeling today?"
                )
            else:
                response_text = (
                    f"Hi {user.alias}! I'm already here for you. "
                    "What's on your mind today?"
                )
            
            await twilio_service.send_sms(From, response_text)
            
            return Response(
                content=twilio_service.create_messaging_response(response_text),
                media_type="application/xml"
            )
        
        # Process message with AI
        background_tasks.add_task(
            process_user_message,
            user_id=user.user_id,
            message_text=Body,
            message_sid=MessageSid,
            channel="SMS" if "whatsapp" not in From.lower() else "WhatsApp",
            db=db
        )
        
        # Return empty response to avoid double-sending
        return Response(content="", media_type="application/xml")
        
    except Exception as e:
        logger.error(
            "message_processing_error",
            error=str(e),
            message_sid=MessageSid,
            from_number=From
        )
        
        # Send fallback response
        fallback_text = (
            "I'm experiencing some technical difficulties right now. "
            "Please try again in a moment, or call our support line if this is urgent."
        )
        
        return Response(
            content=twilio_service.create_messaging_response(fallback_text),
            media_type="application/xml"
        )

async def process_user_message(
    user_id: str,
    message_text: str,
    message_sid: str,
    channel: str,
    db: Session
):
    """Background task to process user message with AI and respond"""
    
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return
        
        # Get recent interactions for context
        recent_interactions = db.query(Interaction).filter(
            Interaction.user_id == user_id
        ).order_by(Interaction.created_at.desc()).limit(5).all()
        
        # Classify risk level
        risk_score, risk_level, crisis_keywords = await ai_service.classify_risk(
            message_text,
            user_context={"alias": user.alias, "recent_interactions_count": len(recent_interactions)}
        )
        
        # Store incoming interaction
        interaction = Interaction(
            user_id=user_id,
            channel=channel,
            direction="inbound",
            text=message_text,
            risk_score=risk_score,
            session_id=message_sid
        )
        db.add(interaction)
        db.commit()
        
        # Check if escalation is needed
        should_escalate, escalation_reason = await ai_service.should_escalate_to_human(
            risk_score, risk_level, message_text, crisis_keywords
        )
        
        if should_escalate:
            # Create risk event
            risk_event = RiskEvent(
                user_id=user_id,
                event_type="crisis" if crisis_keywords else "high_risk",
                risk_level=risk_level,
                source_interaction_id=interaction.id,
                trigger_keywords=crisis_keywords
            )
            db.add(risk_event)
            
            # Create TaskRouter task for mentor
            task_sid = await twilio_service.create_taskrouter_task(
                user_id=str(user_id),
                priority=10 if crisis_keywords else 5,
                risk_level=risk_level,
                context={
                    "message": message_text,
                    "risk_score": risk_score,
                    "escalation_reason": escalation_reason
                }
            )
            
            if task_sid:
                # Send escalation message to user
                escalation_text = (
                    "I can hear this is really important. I'm connecting you with "
                    "one of our human mentors right now. They'll be with you shortly. "
                    "In the meantime, you're doing the right thing by reaching out."
                )
                
                if crisis_keywords:
                    escalation_text = (
                        "I'm here with you. I'm immediately connecting you to someone "
                        "who can provide the support you need. Please stay with me. "
                        "If this is an emergency, please also call 988 or 911."
                    )
                
                await twilio_service.send_sms(user.phone, escalation_text)
                
                # Store outbound interaction
                outbound_interaction = Interaction(
                    user_id=user_id,
                    channel=channel,
                    direction="outbound",
                    text=escalation_text,
                    handled_by="AI_escalation",
                    session_id=message_sid
                )
                db.add(outbound_interaction)
                
                logger.warning(
                    "escalation_initiated",
                    user_id=str(user_id),
                    risk_level=risk_level,
                    task_sid=task_sid,
                    reason=escalation_reason
                )
            
            db.commit()
            return
        
        # Generate AI response
        ai_response, resource_id = await ai_service.generate_response(
            message_text,
            user,
            risk_level,
            "support_needed",  # Default intent for now
            recent_interactions
        )
        
        # Send AI response
        await twilio_service.send_sms(user.phone, ai_response)
        
        # Store outbound interaction
        outbound_interaction = Interaction(
            user_id=user_id,
            channel=channel,
            direction="outbound",
            text=ai_response,
            handled_by="AI",
            session_id=message_sid
        )
        db.add(outbound_interaction)
        db.commit()
        
        logger.info(
            "message_processed_successfully",
            user_id=str(user_id),
            risk_level=risk_level,
            response_sent=True
        )
        
    except Exception as e:
        logger.error(
            "background_message_processing_error",
            user_id=str(user_id),
            error=str(e)
        )
        
        # Send fallback response
        try:
            fallback_text = (
                "I'm having trouble processing your message right now, "
                "but I want you to know I'm here. Please try again, or if this is urgent, "
                "don't hesitate to call our support line."
            )
            
            user = db.query(User).filter(User.user_id == user_id).first()
            if user:
                await twilio_service.send_sms(user.phone, fallback_text)
                
        except Exception as fallback_error:
            logger.error(
                "fallback_response_failed",
                user_id=str(user_id),
                error=str(fallback_error)
            )

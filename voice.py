from fastapi import APIRouter, Request, HTTPException, Depends, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
import structlog
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.database import get_db
from app.models import User, Interaction, RiskEvent
from app.services.twilio_service import twilio_service
from app.services.ai_service import ai_service

logger = structlog.get_logger()
router = APIRouter()

@router.post("/voice/inbound")
async def handle_inbound_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallStatus: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle incoming voice calls from Twilio"""
    
    logger.info(
        "inbound_call_received",
        call_sid=CallSid,
        from_number=From,
        call_status=CallStatus
    )
    
    try:
        # Generate unique session ID for this call
        session_id = str(uuid.uuid4())
        
        # Find user by phone number
        user = db.query(User).filter(User.phone == From, User.is_active == True).first()
        
        if user:
            # Log the call interaction
            interaction = Interaction(
                user_id=user.user_id,
                channel="Voice",
                direction="inbound",
                text=f"Voice call initiated - CallSid: {CallSid}",
                session_id=session_id
            )
            db.add(interaction)
            db.commit()
            
            logger.info(
                "call_from_registered_user",
                user_id=str(user.user_id),
                call_sid=CallSid
            )
        else:
            logger.info(
                "call_from_unregistered_user",
                from_number=From,
                call_sid=CallSid
            )
        
        # Create TwiML response with Media Streams for real-time AI
        twiml_response = twilio_service.create_voice_response(session_id)
        
        return Response(
            content=twiml_response,
            media_type="application/xml"
        )
        
    except Exception as e:
        logger.error(
            "voice_call_error",
            call_sid=CallSid,
            error=str(e)
        )
        
        # Fallback TwiML response
        fallback_twiml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="alice">
                I'm sorry, I'm experiencing technical difficulties right now.
                Please try calling back in a few minutes, or text us for immediate support.
                If this is an emergency, please hang up and dial 911.
            </Say>
            <Hangup/>
        </Response>
        """
        
        return Response(
            content=fallback_twiml,
            media_type="application/xml"
        )

@router.post("/voice/outbound/{user_id}")
async def handle_outbound_call(
    user_id: str,
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle outbound proactive calls for crisis intervention"""
    
    logger.info(
        "outbound_call_webhook",
        user_id=user_id,
        call_sid=CallSid,
        call_status=CallStatus
    )
    
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Crisis intervention TwiML
        crisis_twiml = f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="alice">
                Hello {user.alias}, this is ARC calling to check on you.
                I noticed you might be going through a difficult time right now.
                I'm here to listen and support you.
                Please stay on the line, and let's talk.
            </Say>
            <Pause length="2"/>
            <Say voice="alice">
                If you'd prefer to speak with a human mentor, press 1.
                Otherwise, please tell me how you're feeling right now.
            </Say>
            <Gather input="speech dtmf" timeout="10" speechTimeout="auto">
                <Say voice="alice">I'm listening...</Say>
            </Gather>
            <Say voice="alice">
                I want you to know that you're not alone.
                Our support team is here for you 24/7.
                Please call us back anytime you need support.
            </Say>
        </Response>
        """
        
        # Log the outbound call
        interaction = Interaction(
            user_id=user.user_id,
            channel="Voice",
            direction="outbound",
            text=f"Proactive crisis intervention call - CallSid: {CallSid}",
            handled_by="AI_proactive",
            session_id=CallSid
        )
        db.add(interaction)
        db.commit()
        
        return Response(
            content=crisis_twiml,
            media_type="application/xml"
        )
        
    except Exception as e:
        logger.error(
            "outbound_call_error",
            user_id=user_id,
            call_sid=CallSid,
            error=str(e)
        )
        
        return Response(
            content="<?xml version='1.0' encoding='UTF-8'?><Response><Hangup/></Response>",
            media_type="application/xml"
        )

@router.post("/voice/gather")
async def handle_voice_gather(
    request: Request,
    CallSid: str = Form(...),
    SpeechResult: Optional[str] = Form(None),
    Digits: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Handle speech/DTMF input from voice calls"""
    
    logger.info(
        "voice_input_received",
        call_sid=CallSid,
        speech_result=SpeechResult,
        digits=Digits
    )
    
    try:
        # Find user by looking up the call session
        interaction = db.query(Interaction).filter(
            Interaction.session_id == CallSid
        ).first()
        
        if not interaction:
            # Generic response for unknown callers
            response_twiml = """
            <?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Say voice="alice">
                    Thank you for calling. Our support team will be in touch.
                    Take care of yourself.
                </Say>
                <Hangup/>
            </Response>
            """
            return Response(content=response_twiml, media_type="application/xml")
        
        user = db.query(User).filter(User.user_id == interaction.user_id).first()
        
        # Handle DTMF input (user pressed 1 for human mentor)
        if Digits == "1":
            # Create TaskRouter task for immediate human escalation
            task_sid = await twilio_service.create_taskrouter_task(
                user_id=str(user.user_id),
                priority=10,
                risk_level="high",
                context={"call_sid": CallSid, "requested_human": True}
            )
            
            response_twiml = """
            <?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Say voice="alice">
                    I'm connecting you with a human mentor right now.
                    Please hold while I transfer your call.
                </Say>
                <Pause length="3"/>
                <Say voice="alice">
                    A mentor will be with you shortly. Thank you for reaching out.
                </Say>
            </Response>
            """
            
            logger.info(
                "voice_human_escalation_requested",
                user_id=str(user.user_id),
                call_sid=CallSid,
                task_sid=task_sid
            )
            
            return Response(content=response_twiml, media_type="application/xml")
        
        # Process speech input with AI
        if SpeechResult:
            # Classify risk and generate response
            risk_score, risk_level, crisis_keywords = await ai_service.classify_risk(
                SpeechResult,
                user_context={"alias": user.alias, "channel": "voice"}
            )
            
            # Generate empathetic response
            ai_response, _ = await ai_service.generate_response(
                SpeechResult,
                user,
                risk_level,
                "voice_support",
                []
            )
            
            # Create response TwiML
            response_twiml = f"""
            <?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Say voice="alice">{ai_response}</Say>
                <Pause length="2"/>
                <Say voice="alice">
                    Is there anything else you'd like to talk about?
                    Press 1 to speak with a human mentor, or keep talking with me.
                </Say>
                <Gather input="speech dtmf" timeout="15" speechTimeout="auto">
                    <Say voice="alice">I'm here to listen...</Say>
                </Gather>
                <Say voice="alice">
                    Thank you for sharing with me today.
                    Remember, you can call or text us anytime you need support.
                    Take care of yourself.
                </Say>
                <Hangup/>
            </Response>
            """
            
            # Log the interaction
            speech_interaction = Interaction(
                user_id=user.user_id,
                channel="Voice",
                direction="inbound",
                text=SpeechResult,
                risk_score=risk_score,
                session_id=CallSid
            )
            db.add(speech_interaction)
            
            response_interaction = Interaction(
                user_id=user.user_id,
                channel="Voice",
                direction="outbound",
                text=ai_response,
                handled_by="AI",
                session_id=CallSid
            )
            db.add(response_interaction)
            db.commit()
            
            # Check for escalation
            if risk_score >= 0.8 or crisis_keywords:
                # Auto-escalate high-risk calls
                task_sid = await twilio_service.create_taskrouter_task(
                    user_id=str(user.user_id),
                    priority=10,
                    risk_level=risk_level,
                    context={
                        "call_sid": CallSid,
                        "speech_input": SpeechResult,
                        "risk_score": risk_score
                    }
                )
                
                logger.warning(
                    "voice_auto_escalation",
                    user_id=str(user.user_id),
                    risk_score=risk_score,
                    task_sid=task_sid
                )
            
            return Response(content=response_twiml, media_type="application/xml")
        
        # Fallback if no input received
        fallback_twiml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="alice">
                I didn't hear anything, but that's okay.
                Sometimes it's hard to find words.
                You can call us back anytime you're ready to talk.
                You're not alone.
            </Say>
            <Hangup/>
        </Response>
        """
        
        return Response(content=fallback_twiml, media_type="application/xml")
        
    except Exception as e:
        logger.error(
            "voice_gather_error",
            call_sid=CallSid,
            error=str(e)
        )
        
        error_twiml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="alice">
                I'm sorry, I'm having technical difficulties.
                Please call back or text us for support.
            </Say>
            <Hangup/>
        </Response>
        """
        
        return Response(content=error_twiml, media_type="application/xml")

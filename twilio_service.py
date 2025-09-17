from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Stream
from twilio.base.exceptions import TwilioException
import structlog
from typing import Optional, Dict, Any
from app.core.config import settings

logger = structlog.get_logger()

class TwilioService:
    def __init__(self):
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.messaging_service_sid = settings.TWILIO_MESSAGING_SERVICE_SID
        self.phone_number = settings.TWILIO_PHONE_NUMBER
        self.workspace_sid = settings.TWILIO_WORKSPACE_SID
        self.workflow_sid = settings.TWILIO_WORKFLOW_SID
        self.conversations_service_sid = settings.TWILIO_CONVERSATIONS_SERVICE_SID
    
    async def send_sms(self, to: str, body: str, media_url: Optional[str] = None) -> Optional[str]:
        """Send SMS message via Twilio Messaging Service"""
        try:
            message_params = {
                'messaging_service_sid': self.messaging_service_sid,
                'to': to,
                'body': body
            }
            
            if media_url:
                message_params['media_url'] = [media_url]
            
            message = self.client.messages.create(**message_params)
            
            logger.info(
                "sms_sent",
                to=to,
                message_sid=message.sid,
                status=message.status
            )
            
            return message.sid
            
        except TwilioException as e:
            logger.error(
                "sms_send_failed",
                to=to,
                error=str(e),
                error_code=getattr(e, 'code', None)
            )
            return None
    
    async def send_whatsapp(self, to: str, body: str, template_sid: Optional[str] = None) -> Optional[str]:
        """Send WhatsApp message via Twilio"""
        try:
            # Format WhatsApp number
            whatsapp_to = f"whatsapp:{to}"
            whatsapp_from = f"whatsapp:{self.phone_number}"
            
            message_params = {
                'from_': whatsapp_from,
                'to': whatsapp_to,
                'body': body
            }
            
            if template_sid:
                message_params['content_sid'] = template_sid
            
            message = self.client.messages.create(**message_params)
            
            logger.info(
                "whatsapp_sent",
                to=to,
                message_sid=message.sid,
                template_sid=template_sid
            )
            
            return message.sid
            
        except TwilioException as e:
            logger.error(
                "whatsapp_send_failed",
                to=to,
                error=str(e)
            )
            return None
    
    def create_voice_response(self, session_id: str) -> str:
        """Create TwiML response for incoming voice calls with Media Streams"""
        response = VoiceResponse()
        
        # Greet the caller
        response.say(
            "Hello, you've reached ARC, your AI Recovery Companion. "
            "I'm here to listen and support you. Please speak freely.",
            voice='alice'
        )
        
        # Start media stream for real-time AI processing
        stream_url = f"wss://{settings.BASE_URL.replace('https://', '')}/ws/voice/{session_id}"
        
        start = Stream(url=stream_url)
        response.append(start)
        
        # Keep the call alive
        response.pause(length=60)
        
        return str(response)
    
    async def create_taskrouter_task(
        self, 
        user_id: str, 
        priority: int = 1,
        risk_level: str = "medium",
        context: Dict[str, Any] = None
    ) -> Optional[str]:
        """Create TaskRouter task for mentor escalation"""
        try:
            attributes = {
                "user_id": str(user_id),
                "risk_level": risk_level,
                "priority": priority,
                "type": "mental_health_support",
                "context": context or {}
            }
            
            task = self.client.taskrouter.v1.workspaces(self.workspace_sid).tasks.create(
                attributes=str(attributes).replace("'", '"'),  # JSON format
                workflow_sid=self.workflow_sid,
                priority=priority
            )
            
            logger.info(
                "taskrouter_task_created",
                task_sid=task.sid,
                user_id=user_id,
                risk_level=risk_level,
                priority=priority
            )
            
            return task.sid
            
        except TwilioException as e:
            logger.error(
                "taskrouter_task_failed",
                user_id=user_id,
                error=str(e)
            )
            return None
    
    async def create_conversation(
        self, 
        user_phone: str, 
        mentor_identity: str,
        task_sid: str
    ) -> Optional[str]:
        """Create Twilio Conversations room for mentor escalation"""
        try:
            # Create conversation
            conversation = self.client.conversations.v1.services(
                self.conversations_service_sid
            ).conversations.create(
                friendly_name=f"Support Session - {task_sid[:8]}",
                attributes=str({
                    "task_sid": task_sid,
                    "type": "mentor_escalation",
                    "created_by": "arc_system"
                }).replace("'", '"')
            )
            
            # Add user participant
            self.client.conversations.v1.services(
                self.conversations_service_sid
            ).conversations(conversation.sid).participants.create(
                messaging_binding_address=user_phone,
                messaging_binding_proxy_address=self.phone_number
            )
            
            # Add mentor participant
            self.client.conversations.v1.services(
                self.conversations_service_sid
            ).conversations(conversation.sid).participants.create(
                identity=mentor_identity
            )
            
            logger.info(
                "conversation_created",
                conversation_sid=conversation.sid,
                task_sid=task_sid,
                participants=[user_phone, mentor_identity]
            )
            
            return conversation.sid
            
        except TwilioException as e:
            logger.error(
                "conversation_creation_failed",
                task_sid=task_sid,
                error=str(e)
            )
            return None
    
    async def make_outbound_call(self, to: str, user_id: str) -> Optional[str]:
        """Make proactive outbound call for crisis intervention"""
        try:
            call = self.client.calls.create(
                to=to,
                from_=self.phone_number,
                url=f"{settings.WEBHOOK_BASE_URL}/voice/outbound/{user_id}",
                method='POST'
            )
            
            logger.info(
                "outbound_call_initiated",
                call_sid=call.sid,
                to=to,
                user_id=user_id
            )
            
            return call.sid
            
        except TwilioException as e:
            logger.error(
                "outbound_call_failed",
                to=to,
                user_id=user_id,
                error=str(e)
            )
            return None
    
    def create_messaging_response(self, message: str) -> str:
        """Create TwiML response for SMS/WhatsApp replies"""
        response = MessagingResponse()
        response.message(message)
        return str(response)

# Global Twilio service instance
twilio_service = TwilioService()

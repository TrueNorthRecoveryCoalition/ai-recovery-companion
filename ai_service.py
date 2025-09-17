import openai
import structlog
from typing import Dict, List, Tuple, Any, Optional
import re
from app.core.config import settings
from app.models import User, Interaction, CopingResource
from app.services.twilio_service import twilio_service
from sqlalchemy.orm import Session
import json

logger = structlog.get_logger()

# Initialize OpenAI client
openai.api_key = settings.OPENAI_API_KEY

class AIService:
    def __init__(self):
        self.risk_threshold_high = settings.RISK_THRESHOLD_HIGH
        self.risk_threshold_medium = settings.RISK_THRESHOLD_MEDIUM
        self.crisis_keywords = settings.crisis_keywords_list
        
    async def classify_risk(self, text: str, user_context: Dict[str, Any] = None) -> Tuple[float, str, List[str]]:
        """Classify risk level of user message using AI and keyword detection"""
        
        # Quick keyword-based crisis detection
        detected_keywords = []
        text_lower = text.lower()
        
        for keyword in self.crisis_keywords:
            if keyword in text_lower:
                detected_keywords.append(keyword)
        
        # If crisis keywords detected, immediately mark as high risk
        if detected_keywords:
            logger.warning(
                "crisis_keywords_detected",
                keywords=detected_keywords,
                text_preview=text[:100]
            )
            return 0.95, "high", detected_keywords
        
        # Use LLM for nuanced risk assessment
        try:
            system_prompt = """
            You are a mental health risk assessment AI. Analyze the user's message and return ONLY a JSON object with:
            {
                "risk_score": float between 0.0-1.0,
                "risk_level": "low" | "medium" | "high",
                "reasoning": "brief explanation",
                "intent": "craving" | "trigger" | "gratitude" | "logistics" | "support_needed" | "crisis"
            }
            
            Risk indicators:
            - High (0.8+): Suicidal ideation, self-harm, immediate relapse risk, hopelessness
            - Medium (0.5-0.8): Strong cravings, recent triggers, isolation, relationship issues
            - Low (0.0-0.5): Check-ins, gratitude, seeking resources, general conversation
            
            Consider context: recovery journey, addiction support, mental health.
            """
            
            user_prompt = f"""User message: "{text}"
            
            {f"User context: {json.dumps(user_context)}" if user_context else ""}
            """
            
            response = await openai.ChatCompletion.acreate(
                model=settings.RISK_CLASSIFICATION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=200
            )
            
            result = json.loads(response.choices[0].message.content)
            
            risk_score = float(result["risk_score"])
            risk_level = result["risk_level"]
            intent = result.get("intent", "unknown")
            
            logger.info(
                "risk_classified",
                risk_score=risk_score,
                risk_level=risk_level,
                intent=intent,
                reasoning=result.get("reasoning")
            )
            
            return risk_score, risk_level, detected_keywords
            
        except Exception as e:
            logger.error(
                "risk_classification_failed",
                error=str(e),
                fallback_to="medium"
            )
            # Fallback to medium risk if classification fails
            return 0.6, "medium", detected_keywords
    
    async def generate_response(
        self, 
        user_message: str, 
        user: User,
        risk_level: str,
        intent: str,
        recent_interactions: List[Interaction] = None
    ) -> Tuple[str, Optional[str]]:
        """Generate empathetic, action-oriented response using motivational interviewing principles"""
        
        try:
            # Build context from user history
            context_parts = [
                f"User alias: {user.alias}",
                f"Current risk level: {risk_level}",
                f"Message intent: {intent}",
            ]
            
            if recent_interactions:
                recent_messages = []
                for interaction in recent_interactions[-3:]:  # Last 3 interactions
                    recent_messages.append(f"{interaction.direction}: {interaction.text[:100]}")
                context_parts.append(f"Recent conversation: {'; '.join(recent_messages)}")
            
            context = "\n".join(context_parts)
            
            system_prompt = """
            You are ARC, an AI Recovery Companion specializing in addiction recovery and mental health support.
            
            Your approach:
            - Use motivational interviewing techniques (open questions, affirmations, reflective listening)
            - Be warm, empathetic, and non-judgmental
            - Keep responses brief (1-2 sentences) and actionable
            - Always include one concrete coping strategy or next step
            - Never provide medical advice
            - Affirm the user's strength and progress
            
            Response guidelines by risk level:
            - LOW: Supportive, encouraging, maintain momentum
            - MEDIUM: More active listening, offer specific coping tools
            - HIGH: Immediate grounding techniques, offer human support
            
            If user expresses gratitude: Reflect it back and build on their strength.
            If user reports craving: Validate feeling, offer immediate coping strategy.
            If user shares trigger: Help them process and plan for next time.
            
            Always end with either:
            - A coping technique they can try right now
            - A reflection question to deepen insight
            - An offer to connect with human support
            
            Respond in a conversational, supportive tone. No clinical jargon.
            """
            
            user_prompt = f"""
            Context: {context}
            
            User's message: "{user_message}"
            
            Provide a supportive response and suggest one specific coping resource if appropriate.
            Return JSON format:
            {
                "response": "your empathetic response (1-2 sentences)",
                "coping_suggestion": "specific technique or resource" or null,
                "resource_id": "ID of recommended coping resource" or null
            }
            """
            
            response = await openai.ChatCompletion.acreate(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=300
            )
            
            result = json.loads(response.choices[0].message.content)
            
            ai_response = result["response"]
            resource_id = result.get("resource_id")
            
            logger.info(
                "response_generated",
                user_id=str(user.user_id),
                response_length=len(ai_response),
                resource_suggested=resource_id is not None
            )
            
            return ai_response, resource_id
            
        except Exception as e:
            logger.error(
                "response_generation_failed",
                user_id=str(user.user_id),
                error=str(e)
            )
            
            # Fallback response based on risk level
            fallback_responses = {
                "high": "I can hear you're going through a difficult time. You're not alone. Would you like me to connect you with a human mentor right now? In the meantime, try taking 5 deep breaths with me.",
                "medium": "Thank you for sharing that with me. Your honesty takes courage. Let's focus on one small step you can take right now to take care of yourself.",
                "low": "I appreciate you checking in. You're doing great by staying connected. What's one thing that's going well for you today?"
            }
            
            return fallback_responses.get(risk_level, fallback_responses["medium"]), None
    
    async def should_escalate_to_human(
        self, 
        risk_score: float, 
        risk_level: str, 
        user_message: str,
        crisis_keywords: List[str]
    ) -> Tuple[bool, str]:
        """Determine if conversation should be escalated to human mentor"""
        
        # Immediate escalation criteria
        if crisis_keywords:
            return True, "crisis_keywords_detected"
        
        if risk_score >= self.risk_threshold_high:
            return True, "high_risk_score"
        
        # Check for explicit requests for human help
        help_requests = [
            "talk to someone", "speak to a person", "human help", 
            "counselor", "therapist", "mentor", "real person"
        ]
        
        user_lower = user_message.lower()
        for request in help_requests:
            if request in user_lower:
                return True, "explicit_human_request"
        
        return False, "no_escalation_needed"
    
    async def get_coping_resource(self, db: Session, resource_id: Optional[str] = None, category: Optional[str] = None) -> Optional[CopingResource]:
        """Retrieve specific coping resource or recommend one by category"""
        
        if resource_id:
            return db.query(CopingResource).filter(
                CopingResource.id == resource_id,
                CopingResource.is_active == True
            ).first()
        
        if category:
            return db.query(CopingResource).filter(
                CopingResource.category == category,
                CopingResource.is_active == True
            ).order_by(CopingResource.usage_count.asc()).first()
        
        # Default: return most effective general resource
        return db.query(CopingResource).filter(
            CopingResource.is_active == True,
            CopingResource.category == "breathing"
        ).order_by(CopingResource.usage_count.desc()).first()
    
    async def process_daily_checkin(
        self,
        craving_level: int,
        mood_word: str,
        completed_plan: bool,
        recent_checkins: List[Any]
    ) -> Tuple[float, str]:
        """Process daily check-in and compute wellness score"""
        
        # Simple wellness scoring algorithm
        base_score = 0.5
        
        # Craving level impact (0-3 scale, lower is better)
        craving_impact = (3 - craving_level) / 3 * 0.3
        
        # Plan completion impact
        plan_impact = 0.2 if completed_plan else -0.1
        
        # Mood sentiment analysis (simplified)
        positive_moods = ["good", "great", "happy", "peaceful", "strong", "hopeful", "grateful"]
        negative_moods = ["bad", "awful", "depressed", "anxious", "angry", "lonely", "hopeless"]
        
        mood_impact = 0
        mood_lower = mood_word.lower()
        if any(pos in mood_lower for pos in positive_moods):
            mood_impact = 0.2
        elif any(neg in mood_lower for neg in negative_moods):
            mood_impact = -0.2
        
        # Trend analysis from recent check-ins
        trend_impact = 0
        if recent_checkins and len(recent_checkins) >= 3:
            recent_scores = [c.wellness_score for c in recent_checkins[-3:] if c.wellness_score]
            if recent_scores:
                avg_recent = sum(recent_scores) / len(recent_scores)
                current_score = base_score + craving_impact + plan_impact + mood_impact
                if current_score > avg_recent:
                    trend_impact = 0.1  # Positive trend bonus
        
        wellness_score = max(0.0, min(1.0, base_score + craving_impact + plan_impact + mood_impact + trend_impact))
        
        # Generate response based on score
        if wellness_score >= 0.8:
            response = f"Wonderful to hear you're feeling {mood_word}! Your strength is really showing. Keep up the amazing work! 🌟"
        elif wellness_score >= 0.6:
            response = f"Thanks for checking in. It sounds like you're managing well today. Remember, progress isn't always linear - you're doing great."
        elif wellness_score >= 0.4:
            response = f"I appreciate your honesty about feeling {mood_word}. That takes courage. What's one small thing that might help you feel a bit better today?"
        else:
            response = f"I hear you're having a tough time feeling {mood_word}. You're not alone in this. Would you like to try a quick grounding exercise or talk to someone?"
        
        logger.info(
            "checkin_processed",
            craving_level=craving_level,
            mood=mood_word,
            completed_plan=completed_plan,
            wellness_score=wellness_score
        )
        
        return wellness_score, response

# Global AI service instance
ai_service = AIService()

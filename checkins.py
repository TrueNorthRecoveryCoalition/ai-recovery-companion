from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
import structlog
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import pytz
from sqlalchemy import and_, desc

from app.core.database import get_db, get_redis
from app.models import User, CheckIn, Streak, UserPreference
from app.services.twilio_service import twilio_service
from app.services.ai_service import ai_service
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter()

class CheckInResponse(BaseModel):
    craving_level: int  # 0-3
    mood_word: str
    completed_plan: bool
    additional_notes: Optional[str] = None

class CheckInSummary(BaseModel):
    user_id: str
    current_streak: int
    wellness_score: float
    last_checkin: Optional[datetime]
    trend: str  # improving, stable, declining

@router.post("/checkins/respond")
async def process_checkin_response(
    response: CheckInResponse,
    user_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Process user's response to daily check-in"""
    
    logger.info(
        "checkin_response_received",
        user_id=user_id,
        craving_level=response.craving_level,
        mood=response.mood_word,
        completed_plan=response.completed_plan
    )
    
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get recent check-ins for trend analysis
        recent_checkins = db.query(CheckIn).filter(
            CheckIn.user_id == user_id
        ).order_by(desc(CheckIn.created_at)).limit(7).all()
        
        # Process check-in with AI
        wellness_score, ai_response = await ai_service.process_daily_checkin(
            response.craving_level,
            response.mood_word,
            response.completed_plan,
            recent_checkins
        )
        
        # Create check-in record
        checkin = CheckIn(
            user_id=user_id,
            craving_level=response.craving_level,
            mood_word=response.mood_word,
            completed_plan=response.completed_plan,
            wellness_score=wellness_score,
            additional_notes=response.additional_notes
        )
        db.add(checkin)
        
        # Update streak
        streak = db.query(Streak).filter(Streak.user_id == user_id).first()
        if not streak:
            streak = Streak(
                user_id=user_id,
                current_streak=1,
                longest_streak=1,
                total_checkins=1,
                last_checkin_date=datetime.now(timezone.utc)
            )
            db.add(streak)
        else:
            # Check if this is consecutive day
            last_checkin_date = streak.last_checkin_date
            today = datetime.now(timezone.utc).date()
            
            if last_checkin_date and last_checkin_date.date() == today - timedelta(days=1):
                # Consecutive day - increment streak
                streak.current_streak += 1
                if streak.current_streak > streak.longest_streak:
                    streak.longest_streak = streak.current_streak
            elif not last_checkin_date or last_checkin_date.date() != today:
                # New streak or broken streak
                if last_checkin_date and last_checkin_date.date() != today:
                    streak.current_streak = 1  # Reset streak
                else:
                    streak.current_streak += 1
            
            streak.total_checkins += 1
            streak.last_checkin_date = datetime.now(timezone.utc)
        
        db.commit()
        
        # Prepare response message with streak info
        if streak.current_streak > 1:
            streak_message = f" 🔥 {streak.current_streak} day streak!"
        else:
            streak_message = ""
        
        final_response = ai_response + streak_message
        
        # Send response
        background_tasks.add_task(
            twilio_service.send_sms,
            user.phone,
            final_response
        )
        
        # Check for concerning trends
        if wellness_score < 0.4 or response.craving_level >= 3:
            background_tasks.add_task(
                handle_concerning_checkin,
                user_id,
                wellness_score,
                response.craving_level,
                db
            )
        
        return {
            "status": "checkin_processed",
            "wellness_score": wellness_score,
            "current_streak": streak.current_streak,
            "response_sent": True
        }
        
    except Exception as e:
        logger.error(
            "checkin_processing_error",
            user_id=user_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to process check-in")

async def handle_concerning_checkin(
    user_id: str,
    wellness_score: float,
    craving_level: int,
    db: Session
):
    """Handle check-ins that indicate potential risk"""
    
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return
        
        # Send supportive follow-up
        if craving_level >= 3:
            follow_up = (
                "I noticed you're experiencing strong cravings today. "
                "That's really tough, and I'm proud of you for checking in. "
                "Would you like to try a quick grounding exercise, or would you prefer to talk to someone?"
            )
        elif wellness_score < 0.3:
            follow_up = (
                "It sounds like today has been particularly challenging. "
                "Remember, difficult days don't mean you're not making progress. "
                "I'm here if you want to talk more, or I can connect you with a mentor."
            )
        else:
            follow_up = (
                "Thank you for your honest check-in. Sometimes we all have harder days. "
                "What's one small thing that might help you feel a bit better right now?"
            )
        
        await twilio_service.send_sms(user.phone, follow_up)
        
        logger.info(
            "concerning_checkin_follow_up_sent",
            user_id=user_id,
            wellness_score=wellness_score,
            craving_level=craving_level
        )
        
    except Exception as e:
        logger.error(
            "concerning_checkin_follow_up_error",
            user_id=user_id,
            error=str(e)
        )

@router.post("/checkins/send")
async def send_daily_checkins(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Send daily check-ins to users (called by scheduler)"""
    
    try:
        current_time = datetime.now(timezone.utc)
        
        # Get users due for check-in
        users_with_prefs = db.query(User, UserPreference).join(
            UserPreference, User.user_id == UserPreference.user_id
        ).filter(
            User.is_active == True
        ).all()
        
        sent_count = 0
        
        for user, preference in users_with_prefs:
            try:
                # Convert user's local time
                user_tz = pytz.timezone(user.timezone)
                local_time = current_time.astimezone(user_tz)
                
                # Parse check-in time
                checkin_hour, checkin_minute = map(int, preference.checkin_time.split(':'))
                
                # Check if it's time for their check-in (within 15 minutes)
                if (local_time.hour == checkin_hour and 
                    abs(local_time.minute - checkin_minute) <= 15):
                    
                    # Check if they already checked in today
                    today_start = local_time.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_checkin = db.query(CheckIn).filter(
                        and_(
                            CheckIn.user_id == user.user_id,
                            CheckIn.created_at >= today_start.astimezone(timezone.utc)
                        )
                    ).first()
                    
                    if not today_checkin:
                        # Send check-in message
                        checkin_message = (
                            f"Good morning, {user.alias}! Time for your daily check-in 🌅\n\n"
                            "Reply with:\n"
                            "1. Cravings (0-3): How intense are any cravings today?\n"
                            "2. Mood: One word for how you're feeling\n"
                            "3. Plan: Did you complete your plan item yesterday? (YES/NO)\n\n"
                            "Example: Cravings 1; Mood hopeful; Plan YES"
                        )
                        
                        background_tasks.add_task(
                            twilio_service.send_sms,
                            user.phone,
                            checkin_message
                        )
                        
                        sent_count += 1
                        
                        logger.info(
                            "daily_checkin_sent",
                            user_id=str(user.user_id),
                            local_time=local_time.isoformat()
                        )
            
            except Exception as user_error:
                logger.error(
                    "individual_checkin_send_error",
                    user_id=str(user.user_id),
                    error=str(user_error)
                )
                continue
        
        logger.info(
            "daily_checkins_batch_completed",
            total_sent=sent_count,
            total_users_checked=len(users_with_prefs)
        )
        
        return {
            "status": "checkins_sent",
            "count": sent_count
        }
        
    except Exception as e:
        logger.error(
            "daily_checkins_batch_error",
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to send daily check-ins")

@router.get("/checkins/summary/{user_id}")
async def get_checkin_summary(
    user_id: str,
    days: int = 7,
    db: Session = Depends(get_db)
) -> CheckInSummary:
    """Get user's check-in summary and trends"""
    
    try:
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get recent check-ins
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        recent_checkins = db.query(CheckIn).filter(
            and_(
                CheckIn.user_id == user_id,
                CheckIn.created_at >= cutoff_date
            )
        ).order_by(desc(CheckIn.created_at)).all()
        
        # Get streak info
        streak = db.query(Streak).filter(Streak.user_id == user_id).first()
        
        # Calculate trend
        trend = "stable"
        if len(recent_checkins) >= 3:
            recent_scores = [c.wellness_score for c in recent_checkins[:3]]
            older_scores = [c.wellness_score for c in recent_checkins[3:6]] if len(recent_checkins) >= 6 else []
            
            if older_scores:
                recent_avg = sum(recent_scores) / len(recent_scores)
                older_avg = sum(older_scores) / len(older_scores)
                
                if recent_avg > older_avg + 0.1:
                    trend = "improving"
                elif recent_avg < older_avg - 0.1:
                    trend = "declining"
        
        # Latest wellness score
        latest_score = recent_checkins[0].wellness_score if recent_checkins else 0.5
        last_checkin = recent_checkins[0].created_at if recent_checkins else None
        
        return CheckInSummary(
            user_id=user_id,
            current_streak=streak.current_streak if streak else 0,
            wellness_score=latest_score,
            last_checkin=last_checkin,
            trend=trend
        )
        
    except Exception as e:
        logger.error(
            "checkin_summary_error",
            user_id=user_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to get check-in summary")

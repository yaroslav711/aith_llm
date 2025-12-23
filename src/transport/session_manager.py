import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Partnership:
    """Partnership between two users."""
    partnership_id: str
    user1_id: int
    user2_id: Optional[int]
    invite_code: Optional[str]
    invite_expires_at: Optional[datetime]
    created_at: datetime


@dataclass
class Session:
    """Mediation session for a partnership."""
    session_id: str
    partnership_id: str
    current_agent: str  # "onboarding" or "therapy"
    messages: list  # Full conversation history
    classification: Optional[dict]
    created_at: datetime


class SessionManager:
    """Manages partnerships and sessions in memory."""
    
    def __init__(self):
        # user_id -> Partnership
        self.partnerships: Dict[int, Partnership] = {}
        
        # partnership_id -> Session
        self.sessions: Dict[str, Session] = {}
        
        # invite_code -> Partnership
        self.invites: Dict[str, Partnership] = {}
    
    def create_partnership(self, user_id: int) -> Partnership:
        """Create a new partnership (user1 only, waiting for user2)."""
        # Generate invite code
        invite_code = secrets.token_urlsafe(24)
        invite_expires_at = datetime.now() + timedelta(hours=3)
        
        partnership = Partnership(
            partnership_id=f"p_{user_id}_{datetime.now().timestamp()}",
            user1_id=user_id,
            user2_id=None,
            invite_code=invite_code,
            invite_expires_at=invite_expires_at,
            created_at=datetime.now(),
        )
        
        self.partnerships[user_id] = partnership
        self.invites[invite_code] = partnership
        
        return partnership
    
    def get_partnership(self, user_id: int) -> Optional[Partnership]:
        """Get partnership for a user."""
        return self.partnerships.get(user_id)
    
    def get_partnership_by_invite(self, invite_code: str) -> Optional[Partnership]:
        """Get partnership by invite code."""
        partnership = self.invites.get(invite_code)
        
        # Check if invite is expired
        if partnership and partnership.invite_expires_at:
            if datetime.now() > partnership.invite_expires_at:
                return None
        
        return partnership
    
    def accept_invite(self, invite_code: str, user2_id: int) -> Optional[Partnership]:
        """Accept invite and complete partnership."""
        partnership = self.get_partnership_by_invite(invite_code)
        
        if not partnership:
            return None
        
        # Check if already has user2
        if partnership.user2_id is not None:
            return None
        
        # Check if user2 is not the same as user1
        if partnership.user1_id == user2_id:
            return None
        
        # Check if user2 already has a partnership
        if user2_id in self.partnerships:
            return None
        
        # Complete partnership
        partnership.user2_id = user2_id
        partnership.invite_code = None  # Mark as used
        partnership.invite_expires_at = None
        
        # Add to user2's partnerships
        self.partnerships[user2_id] = partnership
        
        # Remove from invites
        del self.invites[invite_code]
        
        return partnership
    
    def get_partner_id(self, user_id: int) -> Optional[int]:
        """Get partner's user_id."""
        partnership = self.get_partnership(user_id)
        if not partnership:
            return None
        
        if partnership.user1_id == user_id:
            return partnership.user2_id
        else:
            return partnership.user1_id
    
    def get_or_create_session(self, partnership_id: str) -> Session:
        """Get or create session for a partnership."""
        if partnership_id in self.sessions:
            return self.sessions[partnership_id]
        
        session = Session(
            session_id=f"s_{partnership_id}_{datetime.now().timestamp()}",
            partnership_id=partnership_id,
            current_agent="onboarding",
            messages=[],
            classification=None,
            created_at=datetime.now(),
        )
        
        self.sessions[partnership_id] = session
        return session
    
    def update_session(
        self,
        partnership_id: str,
        current_agent: Optional[str] = None,
        classification: Optional[dict] = None,
    ):
        """Update session state."""
        session = self.sessions.get(partnership_id)
        if not session:
            return
        
        if current_agent:
            session.current_agent = current_agent
        
        if classification:
            session.classification = classification
    
    def add_message(self, partnership_id: str, role: str, content: str):
        """Add message to session history."""
        session = self.sessions.get(partnership_id)
        if not session:
            return
        
        session.messages.append({"role": role, "content": content})
    
    def is_partnership_complete(self, user_id: int) -> bool:
        """Check if partnership has both users."""
        partnership = self.get_partnership(user_id)
        if not partnership:
            return False
        
        return partnership.user2_id is not None


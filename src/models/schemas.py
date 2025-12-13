"""Data models for the mediator system."""
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# Classification Enums
class Resolvability(str, Enum):
    """Conflict resolvability (Gottman)"""
    RESOLVABLE = "resolvable"
    PERPETUAL = "perpetual"
    GRIDLOCKED = "gridlocked"


class Domain(str, Enum):
    """Life domain of conflict"""
    MONEY = "money"
    SEX = "sex"
    PARENTING = "parenting"
    RELATIVES = "relatives"
    HOUSEHOLD = "household"
    TIME_ATTENTION = "time_attention"
    FUTURE_PLANS = "future_plans"


class Nature(str, Enum):
    """Nature of conflict (rationality)"""
    RATIONAL = "rational"
    EMOTIONAL = "emotional"


class Form(str, Enum):
    """Form of conflict expression"""
    OPEN = "open"
    HIDDEN = "hidden"


class ThreatLevel(str, Enum):
    """Threat level to relationship"""
    FOUNDATIONAL = "foundational"  # Trust, safety at stake
    SURFACE = "surface"  # Manageable, doesn't touch core


# Classification Model
class ConflictClassification(BaseModel):
    """Multi-axis conflict classification"""
    resolvability: Resolvability
    domain: Domain
    nature: Nature
    form: Form
    threat_level: ThreatLevel
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    reasoning: Optional[str] = Field(None, description="Reasoning for classification")


# Message Models
class MessageType(str, Enum):
    """Type of message"""
    HOOK = "hook"
    INSIGHT = "insight"
    SYNTHESIS = "synthesis"
    PROGRESS = "progress"
    SHARE_REQUEST = "share_request"
    ACK = "ack"
    OTHER = "other"


class Message(BaseModel):
    """Single message to a user"""
    recipient: str = Field(..., description="user_1 or user_2")
    type: MessageType
    text: str


class AgentResponse(BaseModel):
    """Response from an agent"""
    messages: List[Message]
    handoff: bool = Field(default=False, description="Signal to switch agents")
    classification: Optional[ConflictClassification] = None


# Session State
class SessionState(BaseModel):
    """State of a mediation session"""
    session_id: str
    current_agent: str = Field(default="onboarding", description="onboarding or therapy")
    messages: List[Dict[str, str]] = Field(default_factory=list, description="Full conversation history")
    ui_messages: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=lambda: {"user_1": [], "user_2": []},
        description="Messages for UI (per user)"
    )
    classification: Optional[ConflictClassification] = None
    playbooks: List[str] = Field(default_factory=list, description="Selected playbook filenames")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Model settings")
    
    class Config:
        arbitrary_types_allowed = True


# LangGraph State
class GraphState(BaseModel):
    """State for LangGraph workflow"""
    session_id: str
    messages: List[Dict[str, str]] = Field(default_factory=list)
    current_agent: str = "onboarding"
    classification: Optional[ConflictClassification] = None
    playbooks: List[str] = Field(default_factory=list)
    last_response: Optional[AgentResponse] = None
    
    class Config:
        arbitrary_types_allowed = True


"""Onboarding agent - establishes contact, classifies conflict."""
from pathlib import Path
from typing import Dict, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from src.models.schemas import AgentResponse, Message, MessageType
from src.classification.classifier import parse_classification_from_response


PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class OnboardingAgent:
    """Agent for initial engagement and classification (7-10 messages)."""
    
    def __init__(self, model_name: str = "gpt-4.1", temperature: float = 0.7):
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            model_kwargs={"response_format": {"type": "json_object"}}
        )
        self.system_prompt = self._load_prompt()
    
    def _build_lc_messages(self, messages: List[Dict[str, str]]):
        """
        Convert stored history (dicts or LangChain BaseMessage) to LangChain messages.
        LangGraph with add_messages may convert dicts into HumanMessage/AIMessage, so
        we accept both shapes here.
        """
        lc_messages = [SystemMessage(content=self.system_prompt)]
        
        for msg in messages:
            role = None
            content = None
            
            if isinstance(msg, dict):
                role = msg.get("role") or msg.get("type")
                content = msg.get("content") or msg.get("text")
            elif isinstance(msg, BaseMessage):
                role = getattr(msg, "type", None)
                content = getattr(msg, "content", None)
            
            if not content:
                continue
            
            if role in ("user", "human"):
                lc_messages.append(HumanMessage(content=content))
            elif role in ("assistant", "ai"):
                lc_messages.append(AIMessage(content=content))
            elif role == "system":
                lc_messages.append(SystemMessage(content=content))
        
        return lc_messages
    
    def _load_prompt(self) -> str:
        """Load onboarding prompt from file."""
        prompt_path = PROMPTS_DIR / "onboarding.md"
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    
    def process(self, messages: List[Dict[str, str]]) -> AgentResponse:
        """
        Process conversation and generate response.
        
        Args:
            messages: Full conversation history [{"role": "user", "content": "[user_1]: ..."}, ...]
        
        Returns:
            AgentResponse with messages and optionally handoff signal
        """
        lc_messages = self._build_lc_messages(messages)
        
        # Get response from LLM
        response = self.llm.invoke(lc_messages)
        response_text = response.content.strip()
        
        # Try to parse as JSON (structured response)
        try:
            import json
            response_data = json.loads(response_text)
            
            # Check for handoff
            handoff = response_data.get("handoff", False)
            
            # Parse classification if present
            classification = None
            if handoff:
                classification = parse_classification_from_response(response_text)
            
            # Parse messages
            agent_messages = []
            for msg_data in response_data.get("messages", []):
                # Safe parse message type - fallback to OTHER if invalid
                msg_type_str = msg_data.get("type", "other")
                try:
                    msg_type = MessageType(msg_type_str)
                except ValueError:
                    print(f"Warning: Invalid message type '{msg_type_str}', using 'other'")
                    msg_type = MessageType.OTHER
                
                agent_messages.append(Message(
                    recipient=msg_data["recipient"],
                    type=msg_type,
                    text=msg_data["text"]
                ))
            
            return AgentResponse(
                messages=agent_messages,
                handoff=handoff,
                classification=classification
            )
            
        except json.JSONDecodeError:
            # Fallback: treat as plain text response to user_1
            print(f"Warning: Onboarding agent returned non-JSON: {response_text[:100]}")
            return AgentResponse(
                messages=[Message(
                    recipient="user_1",
                    type=MessageType.OTHER,
                    text=response_text
                )],
                handoff=False
            )
    


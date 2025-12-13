"""Therapy agent - deep work with conflict using specialized approaches."""
from pathlib import Path
from typing import Dict, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from src.models.schemas import AgentResponse, Message, MessageType, ConflictClassification
from src.playbooks.loader import load_selected_playbooks


PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class TherapyAgent:
    """Agent for deep conflict resolution work with psychological approaches."""
    
    def __init__(self, model_name: str = "gpt-4.1", temperature: float = 0.7):
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            model_kwargs={"response_format": {"type": "json_object"}}
        )
        self.base_prompt = self._load_base_prompt()
    
    def _load_base_prompt(self) -> str:
        """Load therapy base prompt from file."""
        prompt_path = PROMPTS_DIR / "therapy.md"
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    
    def _build_system_prompt(self, classification: ConflictClassification) -> str:
        """
        Build complete system prompt with classification and playbooks.
        
        Format:
        - Base therapy.md prompt
        - Classification injected
        - Playbooks appended
        """
        # Load playbooks
        playbooks_content = load_selected_playbooks(classification)
        
        prompt = self.base_prompt
        prompt = prompt.replace("{resolvability}", classification.resolvability.value)
        prompt = prompt.replace("{domain}", classification.domain.value)
        prompt = prompt.replace("{nature}", classification.nature.value)
        prompt = prompt.replace("{form}", classification.form.value)
        prompt = prompt.replace("{threat_level}", classification.threat_level.value)
        prompt = prompt.replace("{PLAYBOOK_CONTENT_WILL_BE_INSERTED_HERE}", playbooks_content)
        
        return prompt
    
    def _build_lc_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
    ):
        """
        Convert stored history (dicts or LangChain BaseMessage) to LangChain messages.
        LangGraph with add_messages may convert dicts into HumanMessage/AIMessage, so
        we accept both shapes here.
        """
        lc_messages = [SystemMessage(content=system_prompt)]
        
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
    
    def process(
        self, 
        messages: List[Dict[str, str]],
        classification: ConflictClassification
    ) -> AgentResponse:
        """
        Process conversation with specialized approach.
        
        Args:
            messages: Full conversation history
            classification: Conflict classification from onboarding
        
        Returns:
            AgentResponse with therapeutic messages
        """
        # Build system prompt with playbooks
        system_prompt = self._build_system_prompt(classification)
        
        lc_messages = self._build_lc_messages(messages, system_prompt)
        
        # Get response from LLM
        response = self.llm.invoke(lc_messages)
        response_text = response.content.strip()
        
        # Parse JSON response
        try:
            import json
            response_data = json.loads(response_text)
            
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
                handoff=False,  # Therapy agent doesn't hand off
                classification=None
            )
            
        except json.JSONDecodeError:
            # Fallback: treat as plain text
            print(f"Warning: Therapy agent returned non-JSON: {response_text[:100]}")
            return AgentResponse(
                messages=[Message(
                    recipient="user_1",
                    type=MessageType.OTHER,
                    text=response_text
                )],
                handoff=False
            )


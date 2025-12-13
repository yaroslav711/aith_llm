"""LangGraph workflow for multi-agent mediation system."""
from typing import Dict, List, Annotated, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from src.models.schemas import GraphState, ConflictClassification
from src.agents.onboarding import OnboardingAgent
from src.agents.therapy import TherapyAgent


class MediatorState(TypedDict):
    """State for mediator workflow."""
    session_id: str
    messages: Annotated[List[Dict[str, str]], add_messages]
    current_agent: str
    classification: ConflictClassification | None
    last_response: Dict | None


# Initialize agents
onboarding_agent = OnboardingAgent()
therapy_agent = TherapyAgent()


def onboarding_node(state: MediatorState) -> MediatorState:
    """Execute onboarding agent."""
    response = onboarding_agent.process(state["messages"])
    
    # Update state
    new_state = {
        **state,
        "last_response": response.model_dump(),
    }
    
    # Check for handoff
    if response.handoff and response.classification:
        new_state["current_agent"] = "therapy"
        new_state["classification"] = response.classification
    
    return new_state


def therapy_node(state: MediatorState) -> MediatorState:
    """Execute therapy agent with specialized approach."""
    classification = state.get("classification")
    
    if not classification:
        raise ValueError("Therapy agent requires classification")
    
    # Ensure we have a ConflictClassification instance (session may store dict)
    if isinstance(classification, dict):
        classification = ConflictClassification.model_validate(classification)
    
    response = therapy_agent.process(
        state["messages"],
        classification
    )
    
    # Update state
    return {
        **state,
        "last_response": response.model_dump(),
        "classification": classification,
    }


def route_agent(state: MediatorState) -> str:
    """Decide which agent to use after onboarding node."""
    # After onboarding runs, check if handoff occurred
    last_resp = state.get("last_response")
    
    # If onboarding triggered handoff, go to therapy
    if last_resp and last_resp.get("handoff"):
        return "therapy"
    
    # Otherwise stay in onboarding (return END via edge)
    return "onboarding"


def should_continue(state: MediatorState) -> str:
    """Decide if workflow should continue or end."""
    # If we have a response, we're done for this turn
    if state.get("last_response"):
        return END
    return "continue"


# Build the graph
def build_mediator_graph():
    """Build LangGraph workflow."""
    workflow = StateGraph(MediatorState)
    
    # Add nodes
    workflow.add_node("onboarding", onboarding_node)
    workflow.add_node("therapy", therapy_node)
    
    # Determine entry point based on current_agent
    def router_entry(state: MediatorState) -> str:
        """Route to correct agent based on session state."""
        current = state.get("current_agent", "onboarding")
        if current == "therapy":
            return "therapy"
        return "onboarding"
    
    # Set conditional entry
    workflow.set_conditional_entry_point(
        router_entry,
        {
            "onboarding": "onboarding",
            "therapy": "therapy",
        }
    )
    
    # Conditional routing from onboarding
    workflow.add_conditional_edges(
        "onboarding",
        route_agent,
        {
            "onboarding": END,  # Stay in onboarding (no handoff)
            "therapy": "therapy",  # Hand off to therapy
        }
    )
    
    # Therapy always ends
    workflow.add_edge("therapy", END)
    
    return workflow.compile()


# Global graph instance
mediator_graph = build_mediator_graph()


async def process_message(
    session_id: str,
    messages: List[Dict[str, str]],
    current_agent: str = "onboarding",
    classification: ConflictClassification | None = None,
) -> Dict:
    """
    Process a message through the mediator workflow.
    
    Args:
        session_id: Session identifier
        messages: Full conversation history
        current_agent: Current agent ("onboarding" or "therapy")
        classification: Conflict classification (if available)
    
    Returns:
        Dict with response and updated state
    """
    initial_state = MediatorState(
        session_id=session_id,
        messages=messages,
        current_agent=current_agent,
        classification=classification,
        last_response=None,
    )
    
    # Run the graph
    result = await mediator_graph.ainvoke(initial_state)
    
    return {
        "response": result.get("last_response"),
        "current_agent": result.get("current_agent"),
        "classification": result.get("classification"),
    }


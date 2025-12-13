"""FastAPI server for AI Mediator with LangGraph multi-agent system."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Load environment early so API keys are available during agent init
load_dotenv()

# Import new agent system
from src.agents.graph import process_message
from src.models.schemas import ConflictClassification

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
PROMPTS_DIR = BASE_DIR / "prompts"

app = FastAPI(title="AI Mediator")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

MODEL_OPTIONS = [
    {"id": "gpt-4.1", "name": "GPT-4.1", "supports_reasoning": False},
    {"id": "gpt-4o", "name": "GPT-4o", "supports_reasoning": False},
]


def get_default_settings() -> Dict:
    return {
        "temperature": float(os.getenv("DEFAULT_TEMPERATURE", "0.7")),
        "model": os.getenv("DEFAULT_MODEL", "gpt-4.1"),
    }


# Session storage
sessions: Dict[str, Dict] = {}


class ChatRequest(BaseModel):
    message: str
    prompt_file: str = "prompts/onboarding.md"  # Not used anymore, kept for compatibility
    session_id: Optional[str] = None
    temperature: Optional[float] = None
    user_role: str = "user_1"
    model: Optional[str] = None


class RegenerateRequest(BaseModel):
    session_id: str
    prompt_file: str
    user_role: str
    temperature: Optional[float] = None
    model: Optional[str] = None


class ClearRequest(BaseModel):
    session_id: str


class PromptUpdateRequest(BaseModel):
    prompt_file: str
    content: str


def resolve_prompt_path(prompt_path: str) -> Path:
    """Resolve prompt file path."""
    if prompt_path.startswith("prompts/"):
        prompt_path = prompt_path[len("prompts/"):]
    
    target = PROMPTS_DIR / prompt_path
    target = target.resolve()
    
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Prompt file not found: {prompt_path}")
    
    try:
        target.relative_to(PROMPTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid prompt path")
    
    return target


def create_session(session_id: str) -> Dict:
    """Create new session."""
    session = {
        "session_id": session_id,
        "current_agent": "onboarding",
        "messages": [],  # Full conversation history
        "ui_messages": {"user_1": [], "user_2": []},  # UI messages per user
        "classification": None,
        "settings": get_default_settings(),
        "created_at": datetime.now().isoformat(),
    }
    return session


def parse_agent_response(response_data: Dict, fallback_recipient: str) -> List[Dict]:
    """Parse response from agent into UI messages."""
    responses = []
    
    if not response_data:
        return responses
    
    messages = response_data.get("messages", [])
    for msg in messages:
        responses.append({
            "recipient": msg.get("recipient", fallback_recipient),
            "text": msg.get("text", ""),
            "type": msg.get("type", "other"),
        })
    
    return responses


def append_ui_messages(session: Dict, responses: List[Dict]):
    """Append agent responses to UI messages."""
    timestamp = datetime.now().isoformat()
    for resp in responses:
        recipient = resp.get("recipient", "user_1")
        if recipient in session["ui_messages"]:
            session["ui_messages"][recipient].append({
                "role": "assistant",
                "content": resp.get("text", ""),
                "type": resp.get("type", "other"),
                "timestamp": timestamp,
            })


@app.get("/")
async def index():
    """Serve main UI."""
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return FileResponse(html_file)
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/api/models")
async def list_models():
    """List available models."""
    return {"models": MODEL_OPTIONS}


@app.get("/api/prompts")
async def list_prompts():
    """List available prompts."""
    prompts = []
    if PROMPTS_DIR.exists():
        for file in PROMPTS_DIR.rglob("*.md"):
            if "archive" in str(file) or "playbooks" in str(file):
                continue
            rel_path = file.relative_to(BASE_DIR)
            prompts.append({"name": str(rel_path), "path": str(rel_path)})
        prompts.sort(key=lambda x: x["path"])
    return {"prompts": prompts}


@app.get("/api/prompts/{prompt_path:path}")
async def get_prompt(prompt_path: str):
    """Get prompt content."""
    path = resolve_prompt_path(prompt_path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return {"content": content, "path": prompt_path}


@app.post("/api/prompts/{prompt_path:path}")
async def update_prompt(prompt_path: str, request: PromptUpdateRequest):
    """Update prompt content."""
    path = resolve_prompt_path(prompt_path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(request.content)
    return {"status": "updated", "path": prompt_path}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Process chat message through multi-agent system."""
    session_id = request.session_id or f"session_{datetime.now().timestamp()}"
    
    # Get or create session
    if session_id not in sessions:
        sessions[session_id] = create_session(session_id)
    
    session = sessions[session_id]
    
    # Update settings if provided
    if request.temperature is not None:
        session["settings"]["temperature"] = request.temperature
    if request.model is not None:
        session["settings"]["model"] = request.model
    
    # Add user message to history
    user_message = f"[{request.user_role}]: {request.message}"
    session["messages"].append({"role": "user", "content": user_message})
    
    # Add to UI messages
    session["ui_messages"][request.user_role].append({
        "role": "user",
        "content": request.message,
        "timestamp": datetime.now().isoformat(),
    })
    
    try:
        # Process through LangGraph
        result = await process_message(
            session_id=session_id,
            messages=session["messages"],
            current_agent=session["current_agent"],
            classification=session["classification"],
        )
        
        response_data = result.get("response")
        
        # Update session state
        if result.get("current_agent"):
            session["current_agent"] = result["current_agent"]
        
        if result.get("classification"):
            # Convert to dict for JSON serialization
            classification = result["classification"]
            if isinstance(classification, ConflictClassification):
                session["classification"] = classification.model_dump()
            else:
                session["classification"] = classification
        
        # Parse responses
        responses = parse_agent_response(response_data, request.user_role)
        
        # Debug: log if no responses were parsed
        if not responses:
            print(f"WARNING: No responses parsed from response_data: {response_data}")
        
        # Add assistant message to history
        if response_data:
            # Store raw JSON response
            session["messages"].append({
                "role": "assistant",
                "content": json.dumps(response_data, ensure_ascii=False)
            })
        
        # Add to UI messages
        append_ui_messages(session, responses)
        
        # Calculate usage (mock for now)
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        
        return {
            "session_id": session_id,
            "responses": responses,
            "raw_response": json.dumps(response_data, ensure_ascii=False),
            "usage": usage,
            "agent_status": session["current_agent"],
            "conflict_type": session["classification"]["domain"] if session.get("classification") else None,
        }
        
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {
            "session_id": session_id,
            "error": str(exc),
            "responses": [{
                "recipient": request.user_role,
                "text": f"Ошибка: {str(exc)}",
                "type": "error",
            }],
        }


@app.post("/api/regenerate")
async def regenerate(request: RegenerateRequest):
    """Regenerate last response."""
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[request.session_id]
    
    # Remove last assistant message
    for idx in range(len(session["messages"]) - 1, -1, -1):
        if session["messages"][idx]["role"] == "assistant":
            session["messages"].pop(idx)
            break
    
    # Remove from UI messages (both users)
    for user_key in ["user_1", "user_2"]:
        if session["ui_messages"][user_key]:
            for idx in range(len(session["ui_messages"][user_key]) - 1, -1, -1):
                if session["ui_messages"][user_key][idx]["role"] == "assistant":
                    session["ui_messages"][user_key].pop(idx)
                    break
    
    try:
        # Process through LangGraph
        result = await process_message(
            session_id=request.session_id,
            messages=session["messages"],
            current_agent=session["current_agent"],
            classification=session["classification"],
        )
        
        response_data = result.get("response")
        responses = parse_agent_response(response_data, request.user_role)
        
        # Add new messages
        if response_data:
            session["messages"].append({
                "role": "assistant",
                "content": json.dumps(response_data, ensure_ascii=False)
            })
        
        append_ui_messages(session, responses)
        
        return {
            "session_id": request.session_id,
            "responses": responses,
            "raw_response": json.dumps(response_data, ensure_ascii=False),
        }
        
    except Exception as exc:
        return {
            "session_id": request.session_id,
            "error": str(exc),
            "responses": [{
                "recipient": request.user_role,
                "text": f"Ошибка: {str(exc)}",
                "type": "error",
            }],
        }


@app.post("/api/clear")
async def clear_history(request: ClearRequest):
    """Clear session history."""
    if request.session_id in sessions:
        del sessions[request.session_id]
    return {"status": "cleared", "session_id": request.session_id}


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """Get session history."""
    if session_id not in sessions:
        return {"messages": {"user_1": [], "user_2": []}}
    return {"messages": sessions[session_id]["ui_messages"]}


@app.get("/api/settings/{session_id}")
async def get_settings(session_id: str):
    """Get session settings."""
    if session_id not in sessions:
        return get_default_settings()
    return sessions[session_id]["settings"]


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


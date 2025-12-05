import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
PROMPTS_DIR = BASE_DIR / "prompts"

app = FastAPI(title="AI Mediator")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

MODEL_OPTIONS = [
    {"id": "gpt-4.1", "name": "GPT-4.1", "supports_reasoning": False},
    {"id": "gpt-5.1", "name": "GPT-5.1 (o-series)", "supports_reasoning": True},
]


def get_default_settings() -> Dict[str, float]:
    return {
        "temperature": float(os.getenv("DEFAULT_TEMPERATURE", "0.1")),
        "top_p": float(os.getenv("DEFAULT_TOP_P", "0.9")),
        "frequency_penalty": float(os.getenv("DEFAULT_FREQUENCY_PENALTY", "0.4")),
        "presence_penalty": float(os.getenv("DEFAULT_PRESENCE_PENALTY", "0.2")),
        "model": os.getenv("DEFAULT_MODEL", "gpt-4.1"),
        "reasoning_effort": os.getenv("DEFAULT_REASONING_EFFORT", "medium"),
    }


sessions: Dict[str, Dict] = {}
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class ChatRequest(BaseModel):
    message: str
    prompt_file: str
    session_id: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    user_role: str = "user_1"
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None


class RegenerateRequest(BaseModel):
    session_id: str
    prompt_file: str
    user_role: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None


class ClearRequest(BaseModel):
    session_id: str


class PromptUpdateRequest(BaseModel):
    prompt_file: str
    content: str


class ApplySettingsRequest(BaseModel):
    prompt_file: str
    prompt_content: str
    session_id: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None


def resolve_prompt_path(prompt_path: str) -> Path:
    # Если путь начинается с "prompts/", убираем этот префикс
    if prompt_path.startswith("prompts/"):
        prompt_path = prompt_path[len("prompts/"):]
    
    # Всегда ищем файл в PROMPTS_DIR
    target = PROMPTS_DIR / prompt_path
    target = target.resolve()
    
    # Проверяем что файл существует
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Prompt file not found: {prompt_path}")
    
    # Проверяем что путь внутри PROMPTS_DIR
    try:
        target.relative_to(PROMPTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid prompt path")
    
    return target


def create_session(prompt_file: str) -> Dict:
    session = {
        "prompt_file": prompt_file,
        "messages": [],
        "ui_messages": {"user_1": [], "user_2": []},
        "settings": get_default_settings(),
        "last_response": [],
    }
    return session


def update_settings(session: Dict, request_data: Dict):
    settings = session["settings"]
    for key in ["temperature", "top_p", "frequency_penalty", "presence_penalty", "model", "reasoning_effort"]:
        value = request_data.get(key)
        if value is not None:
            settings[key] = value


def parse_agent_response(payload: str, fallback_recipient: str) -> List[Dict]:
    responses: List[Dict] = []
    try:
        parsed = json.loads(payload)
        if "messages" in parsed:
            for msg in parsed["messages"]:
                responses.append(
                    {
                        "recipient": msg.get("recipient", fallback_recipient),
                        "text": msg.get("text", ""),
                        "type": msg.get("type", "other"),
                    }
                )
    except json.JSONDecodeError:
        pass

    if not responses:
        responses.append({"recipient": fallback_recipient, "text": payload, "type": "other"})
    return responses


def append_ui_messages(session: Dict, responses: List[Dict]):
    timestamp = datetime.now().isoformat()
    for resp in responses:
        recipient = resp.get("recipient", "user_1")
        if recipient in session["ui_messages"]:
            session["ui_messages"][recipient].append(
                {
                    "role": "assistant",
                    "content": resp.get("text", ""),
                    "type": resp.get("type", "other"),
                    "timestamp": timestamp,
                }
            )


def call_model(session: Dict, prompt_file: str):
    prompt_path = resolve_prompt_path(prompt_file)
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    messages = [{"role": "system", "content": system_prompt}] + session["messages"]
    settings = session["settings"]
    response = client.chat.completions.create(
        model=settings["model"],
        messages=messages,
        temperature=settings["temperature"],
        top_p=settings["top_p"],
        frequency_penalty=settings["frequency_penalty"],
        presence_penalty=settings["presence_penalty"],
        max_tokens=1000,
    )
    assistant_content = response.choices[0].message.content
    session["messages"].append({"role": "assistant", "content": assistant_content})
    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }
    return assistant_content, usage


@app.get("/")
async def index():
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return FileResponse(html_file)
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/api/models")
async def list_models():
    return {"models": MODEL_OPTIONS}


@app.get("/api/prompts")
async def list_prompts():
    prompts = []
    if PROMPTS_DIR.exists():
        for file in PROMPTS_DIR.rglob("*.md"):
            if "archive" in str(file):
                continue
            rel_path = file.relative_to(BASE_DIR)
            prompts.append({"name": str(rel_path), "path": str(rel_path)})
        prompts.sort(key=lambda x: x["path"])
    return {"prompts": prompts}


@app.get("/api/prompts/{prompt_path:path}")
async def get_prompt(prompt_path: str):
    path = resolve_prompt_path(prompt_path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return {"content": content, "path": prompt_path}


@app.post("/api/prompts/{prompt_path:path}")
async def update_prompt(prompt_path: str, request: PromptUpdateRequest):
    path = resolve_prompt_path(prompt_path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(request.content)
    return {"status": "updated", "path": prompt_path}


@app.post("/api/apply-settings")
async def apply_settings(request: ApplySettingsRequest):
    session_id = request.session_id or f"session_{datetime.now().timestamp()}"
    session = sessions.get(session_id) or create_session(request.prompt_file)
    sessions[session_id] = session

    path = resolve_prompt_path(request.prompt_file)
    with open(path, "w", encoding="utf-8") as f:
        f.write(request.prompt_content)

    session["prompt_file"] = request.prompt_file
    update_settings(session, request.model_dump())

    return {"status": "applied", "session_id": session_id, "settings": session["settings"]}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id or f"session_{datetime.now().timestamp()}"
    session = sessions.get(session_id)
    if not session:
        session = create_session(request.prompt_file)
        sessions[session_id] = session

    session["prompt_file"] = request.prompt_file
    update_settings(session, request.model_dump())

    user_message = f"[{request.user_role}]: {request.message}"
    session["messages"].append({"role": "user", "content": user_message})

    session["ui_messages"][request.user_role].append(
        {"role": "user", "content": request.message, "timestamp": datetime.now().isoformat()}
    )

    try:
        assistant_response, usage = call_model(session, request.prompt_file)
        responses = parse_agent_response(assistant_response, request.user_role)
        session["last_response"] = responses
        append_ui_messages(session, responses)

        return {
            "session_id": session_id,
            "responses": responses,
            "raw_response": assistant_response,
            "usage": usage,
        }
    except Exception as exc:
        return {
            "session_id": session_id,
            "error": str(exc),
            "responses": [
                {
                    "recipient": request.user_role,
                    "text": f"Ошибка: {str(exc)}",
                    "type": "error",
                }
            ],
        }


@app.post("/api/regenerate")
async def regenerate(request: RegenerateRequest):
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]
    update_settings(session, request.model_dump())
    session["prompt_file"] = request.prompt_file

    # Удаляем последнее сообщение ассистента из истории
    for idx in range(len(session["messages"]) - 1, -1, -1):
        if session["messages"][idx]["role"] == "assistant":
            session["messages"].pop(idx)
            break

    # Удаляем сообщения из UI
    removed = session.get("last_response", [])
    removed_recipients = []
    for resp in removed:
        recipient = resp.get("recipient")
        if recipient:
            removed_recipients.append(recipient)
            if recipient in session["ui_messages"] and session["ui_messages"][recipient]:
                session["ui_messages"][recipient].pop()

    try:
        assistant_response, usage = call_model(session, request.prompt_file)
        responses = parse_agent_response(assistant_response, request.user_role)
        session["last_response"] = responses
        append_ui_messages(session, responses)
        return {
            "session_id": request.session_id,
            "responses": responses,
            "raw_response": assistant_response,
            "usage": usage,
            "removed_messages": removed_recipients,
        }
    except Exception as exc:
        return {
            "session_id": request.session_id,
            "error": str(exc),
            "responses": [
                {
                    "recipient": request.user_role,
                    "text": f"Ошибка: {str(exc)}",
                    "type": "error",
                }
            ],
        }


@app.post("/api/clear")
async def clear_history(request: ClearRequest):
    if request.session_id in sessions:
        del sessions[request.session_id]
    return {"status": "cleared", "session_id": request.session_id}


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    if session_id not in sessions:
        return {"messages": {"user_1": [], "user_2": []}}
    return {"messages": sessions[session_id]["ui_messages"]}


@app.get("/api/settings/{session_id}")
async def get_settings(session_id: str):
    if session_id not in sessions:
        return get_default_settings()
    return sessions[session_id]["settings"]


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


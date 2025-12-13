import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on sys.path so `import src...` works when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv


@dataclass
class TurnRecord:
    turn_idx: int
    user_role: str
    user_text: str
    agent_before: str
    agent_status: str
    handoff_detected: bool
    agent_messages: List[Dict[str, Any]]
    raw_response: Dict[str, Any]


@dataclass
class RunMetrics:
    scenario_id: str
    run_id: str
    total_turns: int
    schema_valid_turns: int
    schema_valid_rate: float
    recipient_correct_msgs: int
    recipient_total_msgs: int
    recipient_correct_rate: float
    double_messaging_violations: int
    handoff_turn_idx: Optional[int]
    turn_to_handoff: Optional[int]
    latency_ms_p50: float
    latency_ms_p95: float


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = int(round((len(xs) - 1) * p))
    return float(xs[k])


def load_scenarios(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("scenarios", [])


def normalize_user_message(user_role: str, text: str) -> str:
    # Mirror app.py format so prompts see the same content.
    return f"[{user_role}]: {text}"


def compute_no_double_messaging(
    waiting_for_reply: Dict[str, bool],
    agent_messages: List[Dict[str, Any]],
) -> int:
    violations = 0
    for m in agent_messages:
        r = m.get("recipient")
        if r in ("user_1", "user_2"):
            if waiting_for_reply.get(r, False):
                violations += 1
            waiting_for_reply[r] = True
    return violations


def compute_recipient_correctness(agent_messages: List[Dict[str, Any]]) -> Tuple[int, int]:
    ok = 0
    total = 0
    for m in agent_messages:
        total += 1
        if m.get("recipient") in ("user_1", "user_2"):
            ok += 1
    return ok, total


async def run_scenario_once(
    scenario: Dict[str, Any],
    run_id: str,
    process_message,
    AgentResponse,
) -> Tuple[RunMetrics, List[TurnRecord]]:
    session_id = f"eval_{scenario['id']}_{run_id}"
    current_agent = "onboarding"
    classification = None
    messages: List[Dict[str, str]] = []

    waiting_for_reply = {"user_1": False, "user_2": False}
    handoff_turn_idx: Optional[int] = None

    schema_valid_turns = 0
    recipient_ok_msgs = 0
    recipient_total_msgs = 0
    double_messaging_violations = 0
    latencies_ms: List[float] = []
    transcript: List[TurnRecord] = []

    for turn_idx, turn in enumerate(scenario.get("turns", []), start=1):
        user_role = turn["user_role"]
        user_text = turn["text"]

        # user replied -> allow next assistant message to that user
        waiting_for_reply[user_role] = False

        messages.append({"role": "user", "content": normalize_user_message(user_role, user_text)})

        agent_before = current_agent
        t0 = time.perf_counter()
        result = await process_message(
            session_id=session_id,
            messages=messages,
            current_agent=current_agent,
            classification=classification,
        )
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

        response_data = result.get("response") or {}
        agent_status = result.get("current_agent") or current_agent
        handoff_detected = agent_before != "therapy" and agent_status == "therapy"

        # turn-to-handoff: first turn where agent becomes therapy
        # IMPORTANT: graph may run onboarding->therapy in the same call and return therapy response
        # (handoff flag won't be visible in response_data). So we measure by agent transition.
        if handoff_turn_idx is None and handoff_detected:
            handoff_turn_idx = turn_idx

        # schema validity: validate AgentResponse structure
        try:
            AgentResponse.model_validate(response_data)
            schema_valid_turns += 1
        except Exception:
            pass

        agent_messages = response_data.get("messages", []) if isinstance(response_data, dict) else []

        ok, total = compute_recipient_correctness(agent_messages)
        recipient_ok_msgs += ok
        recipient_total_msgs += total

        double_messaging_violations += compute_no_double_messaging(waiting_for_reply, agent_messages)

        transcript.append(
            TurnRecord(
                turn_idx=turn_idx,
                user_role=user_role,
                user_text=user_text,
                agent_before=agent_before,
                agent_status=agent_status,
                handoff_detected=handoff_detected,
                agent_messages=agent_messages,
                raw_response=response_data,
            )
        )

        # update rolling state for next turn
        current_agent = agent_status
        classification = result.get("classification") or classification
        if response_data:
            messages.append({"role": "assistant", "content": json.dumps(response_data, ensure_ascii=False)})

    total_turns = len(scenario.get("turns", []))
    schema_rate = (schema_valid_turns / total_turns) if total_turns else 0.0
    recipient_rate = (recipient_ok_msgs / recipient_total_msgs) if recipient_total_msgs else 1.0

    metrics = RunMetrics(
        scenario_id=scenario["id"],
        run_id=run_id,
        total_turns=total_turns,
        schema_valid_turns=schema_valid_turns,
        schema_valid_rate=schema_rate,
        recipient_correct_msgs=recipient_ok_msgs,
        recipient_total_msgs=recipient_total_msgs,
        recipient_correct_rate=recipient_rate,
        double_messaging_violations=double_messaging_violations,
        handoff_turn_idx=handoff_turn_idx,
        turn_to_handoff=handoff_turn_idx,
        latency_ms_p50=percentile(latencies_ms, 0.50),
        latency_ms_p95=percentile(latencies_ms, 0.95),
    )

    return metrics, transcript


async def main_async(args: argparse.Namespace) -> int:
    # Always load .env from project root (cwd may differ when running eval script)
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    if not (PROJECT_ROOT / ".env").exists():
        print(f"WARNING: .env not found at {PROJECT_ROOT / '.env'}")
    if not __import__("os").getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is not set. Put it into project-root .env or export it in your shell."
        )

    # Import after env is loaded: graph.py initializes agents at import time.
    from src.agents.graph import process_message  # noqa: WPS433
    from src.models.schemas import AgentResponse  # noqa: WPS433

    scenarios = load_scenarios(Path(args.scenarios))
    if not scenarios:
        raise SystemExit(f"No scenarios found in {args.scenarios}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = out_dir / f"summary_{ts}.json"
    transcript_path = out_dir / f"transcript_{ts}.jsonl"

    all_metrics: List[Dict[str, Any]] = []
    with transcript_path.open("w", encoding="utf-8") as tf:
        for s in scenarios:
            for i in range(args.runs):
                run_id = f"{i+1}"
                try:
                    metrics, transcript = await run_scenario_once(s, run_id, process_message, AgentResponse)
                    all_metrics.append(asdict(metrics))

                    # Write transcript entries as JSONL for manual scoring later
                    tf.write(
                        json.dumps(
                            {
                                "scenario_id": s["id"],
                                "run_id": run_id,
                                "description": s.get("description", ""),
                                "turns": [asdict(t) for t in transcript],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                except Exception as e:
                    # Persist partial results and continue
                    tf.write(
                        json.dumps(
                            {
                                "scenario_id": s.get("id"),
                                "run_id": run_id,
                                "description": s.get("description", ""),
                                "error": repr(e),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

                # Write summary incrementally so crashes still leave a usable report
                summary_path.write_text(
                    json.dumps({"metrics": all_metrics}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    print(f"Wrote summary: {summary_path}")
    print(f"Wrote transcripts (for manual helpfulness scoring): {transcript_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scenarios", default=str(PROJECT_ROOT / "eval" / "scenarios.json"))
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--out-dir", default=str(PROJECT_ROOT / "eval" / "out"))
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())



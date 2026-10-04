"""Controlled WebSocket app-server peer; it never runs a model or project code."""

import json
import os
import sys
from pathlib import Path

from websockets.frames import Frame, Opcode
from websockets.http11 import Request
from websockets.server import ServerProtocol

root = Path(os.environ["STOP_REVIEW_TEST_ROOT"])
options = json.loads((root / "options.json").read_text())
protocol = ServerProtocol()
child = options.get("child", "reviewer")
state_path = root / ("child-turn.json" if child == "reviewer" else child + "-turn.json")
child_turn = {"id": options.get("review_turn", "review-turn"), "status": "inProgress", "items": []}
stopped = options.get("stopped", False)


def flush():
    for data in protocol.data_to_send():
        if data:
            sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def send(message):
    protocol.send_text(json.dumps(message).encode())
    flush()


def handle(request):
    global stopped
    with (root / "wire.jsonl").open("a") as stream:
        stream.write(json.dumps(request) + "\n")
    method = request.get("method")
    if method is None or method == "initialized":
        return
    params = request.get("params", {})
    result = {}
    if options.get("goals_disabled") and method.startswith("thread/goal/"):
        send({"id": request["id"], "error": {"code": -32600, "message": "goals feature is disabled"}})
        return
    if options.get("rpc_error") == method:
        send({"id": request["id"], "error": {"code": -32600, "message": "controlled error"}})
        return
    if method == "thread/read":
        result = {"thread": {
            "id": options.get("returned_id", params["threadId"]), "sessionId": "shared-session",
            "parentThreadId": options.get("parent"), "source": options.get("source", "appServer"),
            "model": "configured-model", "modelProvider": "provider",
            "status": {"type": "idle" if stopped else "active"},
        }}
    elif method == "thread/turns/list":
        if params["threadId"] == child and params["threadId"] != "main":
            state = state_path
            result = {"data": [json.loads(state.read_text())] if state.exists() else []}
        else:
            result = {"data": [{"id": options.get("current_turn", "main-turn"), "status": "inProgress"}]}
    elif method == "thread/fork":
        result = {"thread": {"id": child, "forkedFromId": options.get("fork_parent", "main")},
                  "model": options.get("fork_model", "actual-model"),
                  "modelProvider": options.get("fork_provider", "provider")}
    elif method == "thread/goal/clear":
        result = {"cleared": False}
    elif method == "thread/goal/get":
        result = {"goal": options.get("goal")}
    elif method == "turn/start":
        if params["threadId"] != child:
            raise AssertionError("Only the reviewer may receive turn/start")
        if not options.get("hide_started_turn"):
            state_path.write_text(json.dumps(child_turn))
        if not options.get("drop_start_reply"):
            response_turn = dict(child_turn)
            if options.get("invalid_start_status"):
                response_turn.pop("status")
            send({"id": request["id"], "result": {} if options.get("malformed_start") else {"turn": response_turn}})
        if options.get("request_tool"):
            send({"id": "tool-call", "method": "item/tool/call", "params": {
                "threadId": child, "turnId": "review-turn", "tool": "write", "arguments": {},
            }})
        if options.get("hold"):
            (root / "review-started").touch()
            return
        if options.get("foreign_output"):
            send({"method": "item/completed", "params": {
                "threadId": "foreign", "turnId": "review-turn",
                "item": {"type": "agentMessage", "text": "foreign invalid output"},
            }})
        output = options.get("output", json.dumps({
            "status": "completed", "reason": "The requested result is supported by the recorded test result.",
            "next_steps": [],
        }))
        send({"method": "item/completed", "params": {
            "threadId": child, "turnId": "review-turn",
            "item": {"type": "agentMessage", "text": output},
        }})
        if options.get("usage"):
            send({"method": "thread/tokenUsage/updated", "params": {
                "threadId": child, "tokenUsage": options["usage"],
            }})
        child_turn["status"] = options.get("outcome", "completed")
        state_path.write_text(json.dumps(child_turn))
        send({"method": "turn/completed", "params": {"threadId": child, "turn": child_turn}})
        stopped = options.get("stop_during_review", False)
        return
    elif method == "turn/interrupt":
        if params != {"threadId": child, "turnId": "review-turn"}:
            raise AssertionError("Cancellation must address only the exact reviewer turn")
        send({"id": request["id"], "result": {}})
        if not options.get("ignore_interrupt"):
            child_turn["status"] = "interrupted"
            state_path.write_text(json.dumps(child_turn))
            send({"method": "turn/completed", "params": {"threadId": child, "turn": child_turn}})
        return
    send({"id": request["id"], "result": result})


while data := os.read(sys.stdin.fileno(), 65536):
    protocol.receive_data(data)
    for event in protocol.events_received():
        if isinstance(event, Request):
            protocol.send_response(protocol.accept(event))
            flush()
        elif isinstance(event, Frame) and event.opcode is Opcode.TEXT:
            handle(json.loads(event.data))
    flush()

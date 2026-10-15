"""Shared test helpers: import path, fictitious exports, fake MemPalace CLI."""

import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

FAKE_MP = os.path.join(HERE, "fake_mempalace.py")


def claude_conv(uuid, name, updated, n_pairs=1, created="2026-01-10T09:00:00Z"):
    msgs = []
    for i in range(n_pairs):
        q = f"question {i} about {name}"
        msgs.append({"sender": "human", "text": q, "content": [{"type": "text", "text": q}]})
        msgs.append({"sender": "assistant", "text": "", "content": [{"type": "text", "text": f"answer {i}"}]})
    return {"uuid": uuid, "name": name, "created_at": created, "updated_at": updated, "chat_messages": msgs}


def chatgpt_conv(cid, title, update_time):
    # root -> user -> (assistant "a", abandoned branch | assistant "b", current)
    def node(nid, parent, children, role=None, text=None):
        msg = None if role is None else {"author": {"role": role}, "content": {"parts": [text]}}
        return {"id": nid, "parent": parent, "children": children, "message": msg}

    return {
        "conversation_id": cid,
        "title": title,
        "create_time": 1767225600.0,
        "update_time": update_time,
        "current_node": "b",
        "mapping": {
            "root": node("root", None, ["u"]),
            "u": node("u", "root", ["a", "b"], "user", "how do I bake bread?"),
            "a": node("a", "u", [], "assistant", "abandoned answer"),
            "b": node("b", "u", [], "assistant", "final answer"),
        },
    }


def write_zip(path, conversations, inner="conversations-000/conversations.json"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(inner, json.dumps(conversations))
        zf.writestr("users.json", "[]")
    return path


def fake_cmd():
    return [sys.executable, FAKE_MP]

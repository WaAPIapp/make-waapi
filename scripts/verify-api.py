#!/usr/bin/env python3
"""Exercise every module's HTTP call against the live API.

This does not run Make. It reads each module's own `communication.iml.json`,
substitutes the parameters, and issues exactly the request the deployed
definition describes — so a wrong path, a wrong field name or a mishandled
error is caught here rather than in a customer's scenario.

What it cannot cover: Make's evaluation of the IML expressions themselves.
That needs one scenario run in the Make UI, and it is the only step left
after this passes.

    python3 scripts/verify-api.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
BASE = "https://waapi.app/api/v1"

QR_INSTANCE = 119        # not connected — the error path
LIVE_INSTANCE = 11087    # connected
RECIPIENT = "41763070877@c.us"   # the only number these tests may message

results: list[tuple[bool, str, str]] = []


def strip_comments(text: str) -> str:
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


# Make fills {{webhook.url}} with the scenario's own address. The harness has
# to stand in for it, otherwise the literal expression is posted as the
# subscription URL and the API rejects it — which looks like a broken attach.
STAND_IN_HOOK_URL = "https://hook.eu1.make.com/waapi-verify-placeholder"


def resolve(node, params: dict):
    """Substitute {{parameters.x}} the way Make would, and drop empty values."""
    if isinstance(node, str):
        if node.strip() == "{{webhook.url}}":
            return STAND_IN_HOOK_URL
        match = re.fullmatch(r"\{\{parameters\.(\w+)\}\}", node.strip())
        if match:
            return params.get(match.group(1))
        return re.sub(r"\{\{parameters\.(\w+)\}\}", lambda m: str(params.get(m.group(1), "")), node)
    if isinstance(node, dict):
        out = {k: resolve(v, params) for k, v in node.items()}
        return {k: v for k, v in out.items() if v is not None}
    if isinstance(node, list):
        return [resolve(v, params) for v in node]
    return node


def call(iml_path: Path, params: dict, token: str):
    spec = json.loads(strip_comments(iml_path.read_text()))
    resolved = resolve(spec["url"], params)
    # Connections and webhooks carry an absolute URL because they do not
    # inherit the app's base; modules and RPCs stay relative.
    url = resolved if resolved.startswith("http") else BASE + resolved
    method = resolve(spec.get("method", "GET"), params)
    body = resolve(spec.get("body"), params) if "body" in spec else None

    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("accept", "application/json")
    request.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode() or "{}"), url, body
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw), url, body
        except json.JSONDecodeError:
            return error.code, {"raw": raw[:200]}, url, body


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append((ok, label, detail))
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")


def main() -> int:
    token = (ROOT / ".secrets" / "waapi-token").read_text().strip()

    # --- RPC: the instance dropdown ----------------------------------------
    print("RPC — instance dropdown")
    status, body, _, _ = call(SRC / "rpcs/list-instances/communication.iml.json", {}, token)
    names = [i.get("name") for i in body.get("instances", [])]
    check("lists instances", status == 200 and bool(names), f"{len(names)} found: {names}")
    check("iterates body.instances, not body.data", "instances" in body and "data" not in body)

    # --- Webhooks: attach then detach, for each event set -------------------
    print("\nWebhooks — attach and detach (no messages are sent)")
    for hook in ("new-message", "message-status", "instance-status"):
        params = {"instanceId": LIVE_INSTANCE}
        status, body, _, sent = call(SRC / f"webhooks/{hook}/attach.iml.json", params, token)
        sub = (body.get("data") or {}).get("id")
        check(f"{hook}: attach", status in (200, 201) and bool(sub),
              f"events={sent.get('events')} source={sent.get('source')} id={sub}")
        if not sub:
            continue
        status, body, _, _ = call(
            SRC / f"webhooks/{hook}/detach.iml.json",
            {}, token) if False else call_detach(hook, LIVE_INSTANCE, sub, token)
        check(f"{hook}: detach", status in (200, 204), f"HTTP {status}")

    # --- Actions: one message each, only to the permitted recipient ---------
    print(f"\nActions — sending to {RECIPIENT} on instance {LIVE_INSTANCE}")
    cases = [
        ("send-a-message", {"instanceId": LIVE_INSTANCE, "chatId": RECIPIENT,
                            "message": "WaAPI Make app test — text module."}),
        ("send-media", {"instanceId": LIVE_INSTANCE, "chatId": RECIPIENT,
                        "mediaUrl": "https://waapi.app/apple-touch-icon.png",
                        "mediaCaption": "WaAPI Make app test — media module."}),
        ("send-a-location", {"instanceId": LIVE_INSTANCE, "chatId": RECIPIENT,
                             "latitude": 47.3769, "longitude": 8.5417,
                             "title": "WaAPI Make app test"}),
    ]
    for module, params in cases:
        status, body, _, _ = call(SRC / f"modules/{module}/communication.iml.json", params, token)
        ok = status == 200 and body.get("status") == "success"
        check(f"{module}", ok, f"HTTP {status}, status={body.get('status')}")

    # --- Universal module: a read-only action, no message -------------------
    print("\nUniversal module")
    status, body, url, _ = call(
        SRC / "modules/make-an-api-call/communication.iml.json",
        {"url": f"/instances/{LIVE_INSTANCE}/client/action/get-contacts", "method": "POST", "body": {}},
        token)
    check("make-an-api-call reaches an unwrapped action", status == 200 and body.get("status") == "success",
          f"HTTP {status}")

    # --- The error path Make's review asks for ------------------------------
    print(f"\nError path — instance {QR_INSTANCE} is not connected")
    status, body, _, _ = call(SRC / "modules/send-a-message/communication.iml.json",
                              {"instanceId": QR_INSTANCE, "chatId": RECIPIENT,
                               "message": "This must not be delivered."}, token)
    envelope = body.get("status")
    surfaced = status >= 400 or envelope == "error"
    check("a disconnected instance does not look like success", surfaced,
          f"HTTP {status}, status={envelope}")
    base = json.loads(strip_comments((SRC / "general/base.iml.json").read_text()))
    check("base treats status=error as invalid", "status != 'error'" in json.dumps(base.get("response", {})))

    print()
    failed = [r for r in results if not r[0]]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


def call_detach(hook: str, instance_id: int, subscription_id, token: str):
    """detach.iml.json addresses {{webhook.*}}, which only Make can fill."""
    spec = json.loads(strip_comments((SRC / f"webhooks/{hook}/detach.iml.json").read_text()))
    # attach now stores the finished URL, so detach has a single placeholder.
    resolved = spec["url"].replace(
        "{{webhook.detachUrl}}",
        f"{BASE}/instances/{instance_id}/webhooks/{subscription_id}")
    url = resolved if resolved.startswith("http") else BASE + resolved
    request = urllib.request.Request(url, method=spec["method"])
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, {}, url, None
    except urllib.error.HTTPError as error:
        return error.code, {"raw": error.read().decode()[:200]}, url, None


if __name__ == "__main__":
    sys.exit(main())

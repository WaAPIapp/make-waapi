#!/usr/bin/env python3
"""Deploy the local app definition to Make.

Deploying is not publishing: the app stays private and every component
remains removable until the app is published. Run it as often as needed.

    MAKE_ZONE=eu1.make.com python3 scripts/deploy.py

Reads the API token from the `apikeyFile` named in makecomapp.json.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Section name per code type, taken from Make's own component-code-def.ts
# (integromat/vscode-apps-sdk). The local file name and the API section name
# are not the same string, which is the one thing worth getting from the
# source rather than guessing.
SECTION = {
    "communication": "api",
    "params": "parameters",
    "staticParams": "parameters",
    "mappableParams": "expect",
    "interface": "interface",
    "samples": "samples",
    "attach": "attach",
    "detach": "detach",
    "update": "update",
    "requiredScope": "scope",
    "scope": "scope",
    "epoch": "epoch",
}

# 10 = instant trigger, 4 = action, 12 = universal. From the Create Module
# schema; the enum is not guessable from the module type names.
TYPE_ID = {"instant_trigger": 10, "action": 4, "search": 9, "trigger": 1, "universal": 12, "responder": 11}


def content_type_for(file_rel: str) -> str:
    """Make validates the body against the section's expected type.

    A `.json` section sent as jsonc is rejected as "Invalid content-type", and
    the Markdown readme sent as jsonc is rejected as "Not valid JSONC" -- two
    different errors for the same mistake.
    """
    if file_rel.endswith(".md"):
        return "text/markdown"
    if file_rel.endswith(".iml.json"):
        return "application/jsonc"
    return "application/json"


def request(method: str, path: str, token: str, zone: str, body=None, raw: str | None = None,
            ctype_override: str | None = None):
    url = f"https://{zone}/api/v2{path}"
    if raw is not None:
        data, ctype = raw.encode(), (ctype_override or "application/jsonc")
    elif body is not None:
        data, ctype = json.dumps(body).encode(), "application/json"
    else:
        data, ctype = None, "application/json"
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Token {token}")
    req.add_header("Content-Type", ctype)
    # Without an explicit User-Agent, Make's edge answers 403 "error code: 1010"
    # to urllib's default one -- for every path except POST /sdk/apps, which is
    # what made it look like a permissions problem on the app rather than a
    # blocked client.
    req.add_header("User-Agent", "waapi-make-deploy/1.0")
    try:
        with urllib.request.urlopen(req) as response:
            text = response.read().decode()
            return response.status, (json.loads(text) if text.strip().startswith(("{", "[")) else text)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:400]


def main() -> int:
    doc = json.loads((SRC / "makecomapp.json").read_text())
    origin = doc["origins"][0]
    app, version = origin["appId"], origin["appVersion"]
    zone = os.environ.get("MAKE_ZONE") or origin["baseUrl"].split("//")[1].split("/")[0]
    token = (SRC / origin["apikeyFile"]).resolve().read_text().strip()

    if "-FILL-ME-" in app:
        raise SystemExit("origins[0].appId still carries the placeholder")

    failures: list[str] = []


    # Connections and webhooks get a server-generated name, so "create" never
    # collides and a second run silently produces duplicates instead of an
    # error. The mapping from local id to remote name is therefore the only
    # thing that makes a re-run safe -- and duplicates are removable only
    # while the app is unpublished.
    mapping = origin.setdefault("idMapping", {})

    def remote_name(kind: str, local_id: str) -> str | None:
        for entry in mapping.get(kind, []):
            if entry.get("local") == local_id:
                return entry.get("remote")
        return None

    def remember(kind: str, local_id: str, remote: str) -> None:
        entries = mapping.setdefault(kind, [])
        for entry in entries:
            if entry.get("local") == local_id:
                entry["remote"] = remote
                return
        entries.append({"local": local_id, "remote": remote})

    def put_section(path: str, file_rel: str, label: str) -> None:
        content = (SRC / file_rel).read_text()
        status, body = request("PUT", path, token, zone, raw=content,
                               ctype_override=content_type_for(file_rel))
        ok = 200 <= status < 300
        print(f"  {'ok  ' if ok else 'FAIL'} {label}  ({status})")
        if not ok:
            failures.append(f"{label}: {body}")

    print(f"App {app} v{version} on {zone}\n")

    # --- app-level code -----------------------------------------------------
    print("General:")
    for code, section in (("base", "base"), ("common", "common"), ("groups", "groups")):
        put_section(f"/sdk/apps/{app}/{version}/{section}", doc["generalCodeFiles"][code], f"app/{section}")
    put_section(f"/sdk/apps/{app}/{version}/readme", doc["generalCodeFiles"]["readme"], "app/readme")

    # --- connection (not versioned in the API) ------------------------------
    print("\nConnection:")
    remote_ids: dict[str, str] = {}
    for cid, meta in doc["components"]["connection"].items():
        name = remote_name("connection", cid)
        if name:
            print(f"  ok   exists {cid} -> {name}")
        else:
            status, body = request("POST", f"/sdk/apps/{app}/connections", token, zone,
                                   {"name": cid, "label": meta["label"], "type": meta["connectionType"]})
            if not 200 <= status < 300:
                failures.append(f"connection {cid}: {body}")
                print(f"  FAIL create {cid} ({status}) {body}")
                continue
            name = body.get("appConnection", body.get("connection", {})).get("name", cid)
            remember("connection", cid, name)
            print(f"  ok   create {cid} -> {name}")
        remote_ids[cid] = name
        for code, file_rel in meta["codeFiles"].items():
            if code in SECTION:
                put_section(f"/sdk/apps/connections/{name}/{SECTION[code]}", file_rel, f"connection/{code}")

    # --- rpcs ---------------------------------------------------------------
    print("\nRPCs:")
    for rid, meta in doc["components"]["rpc"].items():
        payload = {"name": rid, "label": meta["label"]}
        if meta.get("connection"):
            payload["connection"] = remote_ids.get(meta["connection"], meta["connection"])
        if remote_name("rpc", rid):
            print(f"  ok   exists {rid}")
        else:
            status, body = request("POST", f"/sdk/apps/{app}/{version}/rpcs", token, zone, payload)
            if not 200 <= status < 300:
                failures.append(f"rpc {rid}: {body}")
                print(f"  FAIL create {rid} ({status}) {body}")
                continue
            remember("rpc", rid, rid)
            print(f"  ok   create {rid}")
        for code, file_rel in meta["codeFiles"].items():
            if code in SECTION:
                put_section(f"/sdk/apps/{app}/{version}/rpcs/{rid}/{SECTION[code]}", file_rel, f"rpc/{rid}/{code}")

    # --- webhooks (not versioned) -------------------------------------------
    print("\nWebhooks:")
    for wid, meta in doc["components"]["webhook"].items():
        payload = {"name": wid, "label": meta["label"], "type": meta["webhookType"]}
        if meta.get("connection"):
            payload["connection"] = remote_ids.get(meta["connection"], meta["connection"])
        name = remote_name("webhook", wid)
        if name:
            print(f"  ok   exists {wid} -> {name}")
        else:
            status, body = request("POST", f"/sdk/apps/{app}/webhooks", token, zone, payload)
            if not 200 <= status < 300:
                failures.append(f"webhook {wid}: {body}")
                print(f"  FAIL create {wid} ({status}) {body}")
                continue
            name = body.get("appWebhook", body.get("webhook", {})).get("name", wid)
            remember("webhook", wid, name)
            print(f"  ok   create {wid} -> {name}")
        remote_ids[wid] = name
        for code, file_rel in meta["codeFiles"].items():
            if code in SECTION:
                put_section(f"/sdk/apps/webhooks/{name}/{SECTION[code]}", file_rel, f"webhook/{wid}/{code}")

    # --- modules ------------------------------------------------------------
    print("\nModules:")
    for mid, meta in doc["components"]["module"].items():
        payload = {
            "name": mid,
            "label": meta["label"],
            "description": meta.get("description", ""),
            "typeId": TYPE_ID[meta["moduleType"]],
            "moduleInitMode": "blank",
        }
        if meta.get("connection"):
            payload["connection"] = remote_ids.get(meta["connection"], meta["connection"])
        if meta.get("webhook"):
            payload["webhook"] = remote_ids.get(meta["webhook"], meta["webhook"])
        if meta.get("actionCrud"):
            payload["crud"] = meta["actionCrud"]
        if remote_name("module", mid):
            print(f"  ok   exists {mid}")
        else:
            status, body = request("POST", f"/sdk/apps/{app}/{version}/modules", token, zone, payload)
            if not 200 <= status < 300:
                failures.append(f"module {mid}: {body}")
                print(f"  FAIL create {mid} ({status}) {body}")
                continue
            remember("module", mid, mid)
            print(f"  ok   create {mid}")
        for code, file_rel in meta["codeFiles"].items():
            if code in SECTION:
                put_section(f"/sdk/apps/{app}/{version}/modules/{mid}/{SECTION[code]}", file_rel, f"module/{mid}/{code}")

    (SRC / "makecomapp.json").write_text(json.dumps(doc, indent=4) + "\n")

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print("  -", f)
        return 1
    print("Deployed without errors. The app is still private and unpublished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

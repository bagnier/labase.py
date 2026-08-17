#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Symbol rename through pyright's language server, over stdio.

Why this exists rather than the built-in LSP tool, and why pyright rather than ty:
SKILL.md, next to this file. Stdlib only — the server is the repo's pinned pyright.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
SERVER = ROOT / ".venv/bin/pyright-langserver"


class Server:
    """A pyright-langserver speaking LSP over stdio."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [str(SERVER), "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=str(ROOT),
        )
        assert self.proc.stdin and self.proc.stdout
        self.stdin, self.stdout = self.proc.stdin, self.proc.stdout
        self.next_id = 1
        self.responses: dict[int, dict] = {}
        self.analysed: set[str] = set()
        self.lock = threading.Condition()
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.stdin.flush()

    def _read_loop(self) -> None:
        while True:
            length = 0
            while (header := self.stdout.readline()) not in (b"\r\n", b""):
                if header.lower().startswith(b"content-length:"):
                    length = int(header.split(b":")[1])
            if not header:
                return
            msg = json.loads(self.stdout.read(length))
            method = msg.get("method")
            if method and "id" in msg:
                # Answer every server->client request. Leaving `client/registerCapability`
                # unanswered is what hangs Claude Code's own LSP client (issue #52693).
                self._send({"jsonrpc": "2.0", "id": msg["id"],
                            "result": [{}] if method == "workspace/configuration" else None})
            elif method == "textDocument/publishDiagnostics":
                with self.lock:
                    self.analysed.add(msg["params"]["uri"])
                    self.lock.notify_all()
            elif "id" in msg:
                with self.lock:
                    self.responses[msg["id"]] = msg
                    self.lock.notify_all()

    def request(self, method: str, params: dict, timeout: float = 120.0) -> dict:
        rid = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        with self.lock:
            if not self.lock.wait_for(lambda: rid in self.responses, timeout=timeout):
                sys.exit(f"pyright did not answer {method} within {timeout:.0f}s")
            return self.responses.pop(rid)

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def start(self, target: Path) -> None:
        self.request("initialize", {
            "processId": None,
            "rootUri": ROOT.as_uri(),
            "workspaceFolders": [{"uri": ROOT.as_uri(), "name": ROOT.name}],
            "capabilities": {
                "workspace": {"workspaceEdit": {"documentChanges": True}, "configuration": True,
                              "workspaceFolders": True},
                "textDocument": {"rename": {"prepareSupport": True}},
            },
        })
        self.notify("initialized", {})
        self.notify("textDocument/didOpen", {"textDocument": {
            "uri": target.as_uri(), "languageId": "python", "version": 1,
            "text": target.read_text()}})
        # pyright emits no progress notification, so the first diagnostics for the document
        # are the only readiness signal it gives. Asked before it, a rename answers from a
        # partial index: measured at 2 edits instead of 6. Waiting costs no round trip.
        with self.lock:
            self.lock.wait_for(lambda: target.as_uri() in self.analysed, timeout=30.0)

    def stop(self) -> None:
        self.request("shutdown", {})
        self.notify("exit", {})


def edits_of(result: dict | None) -> dict[Path, list[dict]]:
    if not result:
        return {}
    changes = result.get("changes") or {
        d["textDocument"]["uri"]: d["edits"] for d in result.get("documentChanges", [])
    }
    return {Path(uri.removeprefix("file://")): edits for uri, edits in changes.items()}


def signature(edits: dict[Path, list[dict]]) -> set:
    return {(str(f), e["range"]["start"]["line"], e["range"]["start"]["character"])
            for f, es in edits.items() for e in es}


def rename_stable(srv: Server, target: Path, line: int, char: int, new_name: str) -> dict:
    """Ask until two consecutive answers agree.

    A cold pyright under-reports: measured on this repo, `findReferences` returned 2 sites
    on the first call and 12 once warm. Agreement between two answers is the cheap guard.
    """
    params = {"textDocument": {"uri": target.as_uri()},
              "position": {"line": line, "character": char}, "newName": new_name}
    previous = None
    for attempt in range(3):
        edits = edits_of(srv.request("textDocument/rename", params).get("result"))
        if previous is not None and signature(edits) == signature(previous):
            return edits
        if attempt:
            print(f"  index still cold, asking again ({attempt + 1}/3)", file=sys.stderr)
        previous = edits
    return previous or {}


def apply(edits: dict[Path, list[dict]]) -> None:
    """Rewrite each file from its content on disk, last edit first."""
    for path, file_edits in edits.items():
        lines = path.read_text().splitlines(keepends=True)
        for e in sorted(file_edits, key=lambda e: (e["range"]["start"]["line"],
                                                   e["range"]["start"]["character"]), reverse=True):
            start, end = e["range"]["start"], e["range"]["end"]
            row = lines[start["line"]]
            lines[start["line"]] = row[:start["character"]] + e["newText"] + row[end["character"]:]
        path.write_text("".join(lines))


parser = argparse.ArgumentParser(description="Rename a Python symbol through pyright.")
parser.add_argument("file", help="file holding the definition")
parser.add_argument("line", type=int, help="line of the symbol (1-based, as an editor shows it)")
parser.add_argument("character", type=int, help="column of the symbol (1-based)")
parser.add_argument("new_name", help="new name")
parser.add_argument("--dry-run", action="store_true", help="list the edits without writing them")
args = parser.parse_args()

if not SERVER.exists():
    sys.exit(f"pyright-langserver not found: {SERVER} — run `uv sync`")
target = Path(args.file).resolve()
if not target.exists():
    sys.exit(f"file not found: {target}")

srv = Server()
srv.start(target)
edits = rename_stable(srv, target, args.line - 1, args.character - 1, args.new_name)
srv.stop()

if not edits:
    sys.exit(f"pyright renames nothing at {args.file}:{args.line}:{args.character} "
             "— is the position off a symbol?")

total = sum(len(e) for e in edits.values())
print(f"{total} edits across {len(edits)} files"
      f"{' (dry-run, nothing written)' if args.dry_run else ''}")
for path, file_edits in sorted(edits.items()):
    print(f"  {path.relative_to(ROOT)}")
    for e in sorted(file_edits, key=lambda e: e["range"]["start"]["line"]):
        print(f"    {e['range']['start']['line'] + 1}:{e['range']['start']['character'] + 1}")

if not args.dry_run:
    apply(edits)

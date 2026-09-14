#!/usr/bin/env python3
"""Interactive demo app for Athena financial-tracking (Epic 10) + gateway probe."""
import html, json, os, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

PORT     = int(os.getenv("PORT", "8080"))
ENDPOINT = os.getenv("LLM_ENDPOINT", "")
MODEL    = os.getenv("LLM_MODEL_NAME", "")
TOKEN    = os.getenv("LLM_API_TOKEN", "")
SCHEME   = os.getenv("LLM_SCHEME", "http")
PATH     = os.getenv("LLM_PATH", "/v1/chat/completions")
MAXTOK   = int(os.getenv("MAX_TOKENS", "128"))

stats = {"calls": 0, "errors": 0, "in_tokens": 0, "out_tokens": 0}

def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), *a, flush=True)

def call_gateway(prompt, path):
    url = f"{SCHEME}://{ENDPOINT}{path}"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAXTOK,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return "", None, f"HTTP {e.code}: {e.read()[:400].decode('utf-8','replace')}"
    except Exception as e:
        return "", None, f"{type(e).__name__}: {e}"
    try:
        reply = data["choices"][0]["message"]["content"]
    except Exception:
        reply = json.dumps(data)[:2000]
    return reply, data.get("usage"), None

def probe():
    url = f"{SCHEME}://{ENDPOINT}/openapi.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            spec = json.loads(resp.read().decode())
        rows = [f"{m.upper():5} {p}" for p, ms in spec.get("paths", {}).items() for m in ms]
        return "\n".join(sorted(rows)) or "(no paths in openapi.json)"
    except Exception as e:
        return f"could not read {url}\n{type(e).__name__}: {e}\n(try /docs in-cluster)"

def page(prompt="", path=PATH, reply="", usage=None, error=""):
    esc = html.escape
    usage_html = f"<pre>usage: {esc(json.dumps(usage))}</pre>" if usage else ""
    reply_html = f"<h3>Reply</h3><pre style='white-space:pre-wrap'>{esc(reply)}</pre>{usage_html}" if reply else ""
    error_html = f"<p style='color:#c00'><b>Error:</b> {esc(error)}</p>" if error else ""
    return f"""<!doctype html><meta charset=utf-8>
<title>Athena Cost Demo</title>
<body style="font-family:system-ui;max-width:720px;margin:40px auto;padding:0 16px">
<h2>Athena Cost Demo</h2>
<p style="color:#555">model: <b>{esc(MODEL or '(unset)')}</b> ·
endpoint: <b>{esc(ENDPOINT or '(unset)')}</b><br>
calls: {stats['calls']} · errors: {stats['errors']} ·
tokens in/out: {stats['in_tokens']}/{stats['out_tokens']} ·
<a href="/probe">probe gateway routes</a></p>
<form method=post action="/chat">
  <label>Request path:
    <input name=path value="{esc(path)}" style="width:100%;margin:4px 0 8px">
  </label>
  <textarea name=prompt rows=4 style="width:100%" placeholder="Type a prompt and press Send">{esc(prompt)}</textarea>
  <button type=submit style="margin-top:8px;padding:8px 16px">Send</button>
</form>
{error_html}{reply_html}
</body>""".encode()

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, json.dumps({"ok": True, **stats}).encode(), "application/json")
        if self.path.startswith("/probe"):
            return self._send(200, ("<pre style='font-family:ui-monospace'>"
                + html.escape(probe()) + "</pre><p><a href='/'>back</a></p>").encode())
        self._send(200, page())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        form = parse_qs(raw)
        prompt = (form.get("prompt", [""])[0]).strip()
        path = (form.get("path", [PATH])[0]).strip() or PATH
        if not prompt:
            return self._send(200, page(path=path, error="Please enter a prompt."))
        reply, usage, error = call_gateway(prompt, path)
        stats["calls"] += 1
        if error:
            stats["errors"] += 1; log("gateway error:", error)
        else:
            if usage:
                stats["in_tokens"]  += int(usage.get("prompt_tokens", 0) or 0)
                stats["out_tokens"] += int(usage.get("completion_tokens", 0) or 0)
            log("gateway ok usage=", usage)
        self._send(200, page(prompt=prompt, path=path, reply=reply, usage=usage, error=error))

    def log_message(self, *a): pass

if __name__ == "__main__":
    log(f"serving on :{PORT} model={MODEL} endpoint={ENDPOINT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

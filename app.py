#!/usr/bin/env python3
"""Interactive one-file demo app for Athena financial-tracking (Epic 10).

Serves a tiny web UI on $PORT. Each time you submit a prompt it calls the
Amberd LLM gateway, so the gateway's token/duration counters attribute usage
-> cost to this app's namespace. Deploy with "Expose public service" ON to
reach it at https://<instance_name>.amberd.ai.

Env (LLM_ENDPOINT / LLM_MODEL_NAME are injected by Athena at deploy time;
provide LLM_API_TOKEN and any override as container Parameters):
  LLM_ENDPOINT   gateway host:port, e.g. amberd-llm-gateway.tier2.svc:8010
  LLM_MODEL_NAME model to request, e.g. qwen3-6 / gpt-4o / claude-sonnet-5
  LLM_API_TOKEN  bearer token for the gateway (if required)
  LLM_SCHEME     http (default) | https
  LLM_PATH       request path (default /v1/chat/completions)
  MAX_TOKENS     max tokens per reply (default 128)
  PORT           listen port (default 8080)
"""
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

def call_gateway(prompt):
    """Return (reply_text, usage_dict, error_str)."""
    url = f"{SCHEME}://{ENDPOINT}{PATH}"
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

def page(prompt="", reply="", usage=None, error=""):
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
tokens in/out: {stats['in_tokens']}/{stats['out_tokens']}</p>
<form method=post action="/chat">
  <textarea name=prompt rows=4 style="width:100%" placeholder="Type a prompt and press Send">{esc(prompt)}</textarea>
  <button type=submit style="margin-top:8px;padding:8px 16px">Send</button>
</form>
{error_html}{reply_html}
</body>""".encode()

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, json.dumps({"ok": True, **stats}).encode(),
                              "application/json")
        self._send(200, page())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        prompt = ""
        if self.headers.get("Content-Type", "").startswith("application/json"):
            try: prompt = json.loads(raw).get("prompt", "")
            except Exception: prompt = ""
        else:
            prompt = (parse_qs(raw).get("prompt", [""])[0]).strip()
        if not prompt:
            return self._send(200, page(error="Please enter a prompt."))
        reply, usage, error = call_gateway(prompt)
        stats["calls"] += 1
        if error:
            stats["errors"] += 1
            log("gateway error:", error)
        else:
            if usage:
                stats["in_tokens"]  += int(usage.get("prompt_tokens", 0) or 0)
                stats["out_tokens"] += int(usage.get("completion_tokens", 0) or 0)
            log("gateway ok usage=", usage)
        self._send(200, page(prompt=prompt, reply=reply, usage=usage, error=error))

    def log_message(self, *a): pass

if __name__ == "__main__":
    log(f"serving on :{PORT} model={MODEL} endpoint={ENDPOINT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

import base64
import http.server
import json
import os
import re
import stat
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOT_SECRET = set("DAILY_CAP RAMP_START RAMP_STEP PAUSE_BOUNCE_RATE PAUSE_MIN_SENDS SIGNAL_MAX_AGE_DAYS "
                 "POSTAL_ADDRESS AD_DISCLOSURE OPT_OUT_LINE GOOGLE_OAUTH_CLIENT_FILE".split())


def test_every_settings_env_var_is_in_secrets_txt():
    src = (ROOT / "gtm/config.py").read_text()
    names = set(re.findall(r'\b(?:s|n)\("([A-Z0-9_]+)"', src)) | set(re.findall(r'_keys\(env, "([A-Z0-9_]+)"', src))
    listed = {l.split("#")[0].strip().rstrip("?") for l in (ROOT / "deploy/secrets.txt").read_text().splitlines()}
    assert names and not (names - NOT_SECRET - listed)


def test_unit_restarts_always_and_loads_the_env_file():
    unit = (ROOT / "deploy/gtm-worker.service").read_text()
    for line in ("Restart=always", "EnvironmentFile=-/run/gtm/env", "ExecStartPre=+/usr/bin/python3 /opt/gtm/deploy/fetch_secrets.py", "TimeoutStartSec=120",
                 "ExecStart=/opt/gtm/.venv/bin/python -m gtm.cli worker"):
        assert line in unit


def _serve(secrets):
    """Local stand-in for the metadata server and Secret Manager. secrets: name -> (status, body)."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path.startswith("/computeMetadata") == (self.headers.get("Metadata-Flavor") == "Google")
            if self.path.endswith("/token"):
                code, body = 200, {"access_token": "tok"}
            elif self.path.endswith("/project-id"):
                code, body = 200, "proj"
            else:
                assert self.headers["Authorization"] == "Bearer tok" and "/projects/proj/" in self.path
                name = self.path.split("/secrets/")[1].split("/")[0]
                code, body = secrets.get(name, (404, {"error": {"message": "NOT_FOUND"}}))
            data = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
            self.send_response(code); self.end_headers(); self.wfile.write(data)
        log_message = lambda *a: None
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _ok(v):
    return 200, {"payload": {"data": base64.b64encode(v.encode()).decode()}}


def _run_fetch(tmp_path, secrets, listing):
    srv = _serve(secrets)
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/secrets.txt").write_text(listing)
    script = tmp_path / "deploy/fetch_secrets.py"
    script.write_text((ROOT / "deploy/fetch_secrets.py").read_text())
    out = tmp_path / "run/env"
    url = f"http://127.0.0.1:{srv.server_port}"
    try:
        r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                           env={**os.environ, "GTM_SM_BASE_URL": url, "GTM_METADATA_BASE_URL": url,
                                "GTM_ENV_OUT": str(out), "GTM_TOKEN_DIR": str(tmp_path / "tok")})
    finally:
        srv.shutdown()
    return r, out


def test_fetch_writes_env_file_and_gmail_token(tmp_path):
    secrets = {"A": _ok('x"y\\z'), "gmail-token": _ok('{"t": 1}')}
    r, out = _run_fetch(tmp_path, secrets, "A\nOPT?  # c\n")
    assert r.returncode == 0, r.stderr
    assert out.read_text() == 'A="x\\"y\\\\z"\n' and stat.S_IMODE(out.stat().st_mode) == 0o600
    assert not [p for p in out.parent.iterdir() if p != out]
    tok = tmp_path / "tok/token_primary.json"
    assert tok.read_text() == '{"t": 1}' and stat.S_IMODE(tok.stat().st_mode) == 0o600


def test_fetch_fails_loudly_on_a_missing_required_secret(tmp_path):
    r, out = _run_fetch(tmp_path, {}, "SUPABASE_URL\n")
    assert r.returncode != 0 and "required secret SUPABASE_URL is missing (NOT_FOUND)" in r.stderr and not out.exists()


def test_fetch_skips_optional_secret_only_on_not_found(tmp_path):
    r, out = _run_fetch(tmp_path, {}, "OPT?\n")
    assert r.returncode == 0 and out.exists()


def test_fetch_fails_on_other_errors_with_name_and_cause_never_the_value(tmp_path):
    secrets = {"OK": _ok("s3cret-value"), "OPT": (403, {"error": {"message": "PERMISSION_DENIED: nope"}})}
    r, out = _run_fetch(tmp_path, secrets, "OK\nOPT?\n")
    assert r.returncode != 0 and "OPT" in r.stderr and "403" in r.stderr and "PERMISSION_DENIED" in r.stderr
    assert "s3cret-value" not in r.stderr + r.stdout and not out.exists()

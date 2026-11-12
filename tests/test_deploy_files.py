import os
import re
import subprocess
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
    for line in ("Restart=always", "EnvironmentFile=-/run/gtm/env", "ExecStartPre=+/opt/gtm/deploy/fetch_secrets.sh",
                 "ExecStart=/opt/gtm/.venv/bin/python -m gtm.cli worker"):
        assert line in unit


def test_fetch_script_fails_loudly_on_a_missing_required_secret(tmp_path):
    out = tmp_path / "env"
    r = subprocess.run(["bash", str(ROOT / "deploy/fetch_secrets.sh")], capture_output=True, text=True,
                       env={**os.environ, "GCLOUD": "false", "GTM_ENV_OUT": str(out), "GTM_TOKEN_DIR": str(tmp_path)})
    assert r.returncode != 0 and "SUPABASE_URL" in r.stderr and not out.exists()


def _run_fetch(tmp_path, stderr, secrets):
    stub = tmp_path / "gcloud"
    stub.write_text(f'#!/usr/bin/env bash\necho "{stderr}" >&2\nexit 1\n')
    stub.chmod(0o755)
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/secrets.txt").write_text(secrets)
    script = tmp_path / "deploy/fetch_secrets.sh"
    script.write_text((ROOT / "deploy/fetch_secrets.sh").read_text())
    out = tmp_path / "run/env"
    return subprocess.run(["bash", str(script)], capture_output=True, text=True,
                          env={**os.environ, "GCLOUD": str(stub), "GTM_ENV_OUT": str(out),
                               "GTM_TOKEN_DIR": str(tmp_path / "tok")}), out


def test_fetch_skips_optional_secret_only_on_not_found(tmp_path):
    r, out = _run_fetch(tmp_path, "ERROR: NOT_FOUND: Secret [x] not found", "OPT?\n")
    assert r.returncode == 0 and out.exists()


def test_fetch_fails_on_other_gcloud_errors_with_name_and_cause(tmp_path):
    r, out = _run_fetch(tmp_path, "PERMISSION_DENIED: nope", "OPT?\n")
    assert r.returncode != 0 and "OPT" in r.stderr and "PERMISSION_DENIED" in r.stderr and not out.exists()

#!/usr/bin/python3
"""Copy Secret Manager values into /run/gtm/env (root-only) before each worker start.
One process, stdlib only (Debian 12 python3.11): gcloud per secret was too slow on the e2-micro."""
import base64, json, os, pwd, sys, tempfile, urllib.error, urllib.request
from pathlib import Path

SM = os.environ.get("GTM_SM_BASE_URL", "https://secretmanager.googleapis.com")
MD = os.environ.get("GTM_METADATA_BASE_URL", "http://metadata.google.internal")
OUT = Path(os.environ.get("GTM_ENV_OUT", "/run/gtm/env"))
TOKEN_DIR = Path(os.environ.get("GTM_TOKEN_DIR", "/opt/gtm/.secrets"))
LIST = Path(__file__).resolve().with_name("secrets.txt")


def die(msg):
    sys.exit(f"fetch_secrets: {msg}")


def get(url, headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
        return r.read()


def meta(path):
    return get(f"{MD}/computeMetadata/v1/{path}", {"Metadata-Flavor": "Google"}).decode()


def main():
    try:
        auth = {"Authorization": "Bearer " + json.loads(meta("instance/service-accounts/default/token"))["access_token"]}
        project = meta("project/project-id").strip()
    except Exception as e:
        die(f"metadata server: {e}")

    def fetch(name):
        """Value, or None on 404; any other failure exits naming the secret and the error, never a value."""
        try:
            body = get(f"{SM}/v1/projects/{project}/secrets/{name}/versions/latest:access", auth)
            return base64.b64decode(json.loads(body)["payload"]["data"]).decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            die(f"{name}: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        except Exception as e:
            die(f"{name}: {type(e).__name__}: {e}")

    lines = []
    for line in LIST.read_text().splitlines():
        name = "".join(line.split("#")[0].split())
        if not name:
            continue
        optional = name.endswith("?")
        name = name.rstrip("?")
        v = fetch(name)
        if v is not None:
            lines.append('%s="%s"\n' % (name, v.replace("\\", "\\\\").replace('"', '\\"')))
        elif not optional:
            die(f"required secret {name} is missing (NOT_FOUND)")
    token = fetch("gmail-token")  # optional Gmail OAuth token; mailbox name from GTM_MAILBOX

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=OUT.parent, prefix=".env.")  # mkstemp is mode 600
    with os.fdopen(fd, "w") as f:
        f.write("".join(lines))
    os.replace(tmp, OUT)
    if token is not None:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        dest = TOKEN_DIR / f"token_{os.environ.get('GTM_MAILBOX', 'primary')}.json"
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
        if os.geteuid() == 0:
            try:
                uid = pwd.getpwnam("gtm").pw_uid
                for p in (TOKEN_DIR, dest):
                    os.chown(p, uid, -1)
            except KeyError:
                pass


main()

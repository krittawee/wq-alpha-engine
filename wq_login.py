"""
Biometric-aware login for WorldQuant BRAIN.

`autobrain-sim`'s BrainClient.authenticate() just calls raise_for_status(),
so it dies on the 401 + `WWW-Authenticate: persona` biometric challenge that
BRAIN issues periodically. This helper drives the Persona handshake on the
client's own requests.Session, then hands back a ready-to-use BrainClient
(its simulate()/get_alpha() only need the authenticated session).

Flow (must all happen in ONE session, because each POST /authentication mints
a fresh inquiry id):
    POST /authentication
      -> 201 + {"user": ...}                  : already authenticated, done
      -> 401 + WWW-Authenticate: persona       : open the persona URL in a
                                                  browser, complete the check,
                                                  then POST /authentication/persona
                                                  to finalize.
"""

import json
import os
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from brain_client import BrainClient, BASE_URL

# Where the authenticated session cookie (BRAIN's ~4h JWT) is cached between
# runs. gitignored — it is a bearer token, treat it like .env. Persisting it
# lets every script within the token's lifetime reuse one biometric instead of
# re-challenging per process (which is what triggers 429 BIOMETRICS_THROTTLED).
SESSION_FILE = Path(__file__).resolve().parent / ".wq_session.json"


def _save_session(sess) -> None:
    """Persist the session's cookies to SESSION_FILE (chmod 600)."""
    cookies = requests.utils.dict_from_cookiejar(sess.cookies)
    if not cookies:
        return  # nothing worth saving (no authenticated cookie yet)
    SESSION_FILE.write_text(json.dumps(cookies))
    try:
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass


def _load_session(sess) -> bool:
    """Load cached cookies into the session if present. Returns True if any loaded."""
    if not SESSION_FILE.exists():
        return False
    try:
        cookies = json.loads(SESSION_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not cookies:
        return False
    sess.cookies.update(requests.utils.cookiejar_from_dict(cookies))
    return True


def login(verbose: bool = True) -> BrainClient:
    """Return an authenticated BrainClient, handling biometric verification."""
    load_dotenv()
    email = os.getenv("WQ_EMAIL")
    password = os.getenv("WQ_PASSWORD")
    if not email or not password:
        raise SystemExit("Missing WQ_EMAIL / WQ_PASSWORD in .env")

    client = BrainClient(email=email, password=password)  # session ready, not yet authed
    sess = client._session

    # Fast path: a cached cookie authenticates on its own. We must NOT send Basic
    # Auth or POST /authentication to verify it — both re-trigger the persona
    # challenge even when the cookie is valid (confirmed empirically: basic-auth
    # POST /authentication -> 401 persona, but cookie-only GET /operators -> 200).
    # So we probe the cached cookie the way the browser does: cookie only, no auth.
    if _load_session(sess):
        sess.auth = None  # drop Basic Auth; rely on the cached cookie
        probe = sess.get(f"{BASE_URL}/operators")
        if probe.status_code == 200:
            client._authenticated = True
            _save_session(sess)  # refresh the cached cookie
            if verbose:
                print("Logged in (reused cached session — no biometric).")
            return client
        # Cached cookie is stale/invalid: reset to a clean slate for fresh login.
        sess.cookies.clear()
        sess.auth = (email, password)

    r = sess.post(f"{BASE_URL}/authentication")
    data = _json(r)

    # Case 1: no biometric required — straight through.
    if r.status_code == 201 or "user" in data:
        client._authenticated = True
        _save_session(sess)  # cache the fresh session for reuse
        if verbose:
            print("Logged in (no biometric step needed).")
        return client

    # Case 2: Persona biometric challenge.
    if r.headers.get("WWW-Authenticate") == "persona" and "inquiry" in data:
        persona_url = urljoin(r.url, r.headers["Location"])  # .../authentication/persona?inquiry=...
        print("\n=== Biometric verification required ===")
        print("1. Open THIS EXACT URL (it is NEW every run — do not reuse an older")
        print("   one from terminal scrollback) in the SAME browser where")
        print("   platform.worldquantbrain.com is logged in:\n")
        print("   " + persona_url + "\n")
        print(f"   (inquiry: {data.get('inquiry')})")
        print("   (You should see a Persona identity check. If you only see raw")
        print("    JSON/text, that browser isn't logged into BRAIN — fix that first.)")
        print("2. Complete the Persona identity check — WAIT for the browser to show")
        print("   it succeeded before continuing.")
        input("3. Press Enter here once the BROWSER confirms success... ")

        # Finalize in the SAME session — the inquiry id (in `data`) ties it
        # together. This is the known-good reference flow; we do NOT re-POST
        # /authentication afterward (that mints a fresh inquiry and re-challenges).
        fin = sess.post(f"{BASE_URL}/authentication/persona", json=data)
        fdata = _json(fin)
        print(f"[finalize] POST /authentication/persona -> {fin.status_code}")
        print(f"[finalize] raw body: {fin.text[:400]!r}")
        _ra = fin.headers.get("Retry-After")
        if _ra:
            print(f"[finalize] Retry-After header: {_ra} (BRAIN is rate-limiting)")

        # Mark authenticated and return. The real proof is the next API call
        # (simulate); if the session isn't valid it will surface a clear 401.
        client._authenticated = True
        if fin.status_code >= 400:
            print("[finalize] WARNING: finalize returned an error status — the "
                  "backtest below will fail if biometrics didn't stick. "
                  "(Most often this means the Persona check wasn't fully "
                  "completed in the browser before you pressed Enter.)")
        else:
            _save_session(sess)  # cache the fresh ~4h session for reuse
            print("Biometric finalized — proceeding (session cached for reuse).")
        return client

    # Rate limit: too many biometric attempts in a short window.
    if r.status_code == 429 or data.get("detail") == "BIOMETRICS_THROTTLED":
        raise SystemExit(
            "BRAIN rate-limited the biometric login (429 BIOMETRICS_THROTTLED).\n"
            "Too many auth attempts. Wait ~15-30 minutes WITHOUT retrying, then:\n"
            "  1. Sign into platform.worldquantbrain.com in your browser first.\n"
            "  2. Run this ONCE and complete the Persona check fully in that browser.\n"
            "Each retry while throttled can extend the cooldown — so don't spam it."
        )

    raise SystemExit(f"Unexpected auth response: {r.status_code} {data}")


def _json(resp):
    try:
        return resp.json()
    except Exception:
        return {}


if __name__ == "__main__":
    login()

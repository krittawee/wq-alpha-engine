import getpass
import json
import logging
import os
import fcntl
import threading
import time
from contextlib import contextmanager
from functools import partial
from multiprocessing.pool import ThreadPool
from pathlib import Path
from typing import Literal, Optional, Union
from urllib.parse import urljoin

import pandas as pd
import requests
import tqdm
from helpful_functions import (
    expand_dict_columns,
    save_pnl,
    save_simulation_result,
    save_yearly_stats,
)

DEV = False

_UNSET = object()

Category = Optional[
    Literal[
        "PRICE_REVERSION",
        "PRICE_MOMENTUM",
        "VOLUME",
        "FUNDAMENTAL",
        "ANALYST",
        "PRICE_VOLUME",
        "RELATION",
        "SENTIMENT",
    ]
]


class SingleSession(requests.Session):
    _instance = None
    _lock = threading.Lock()
    _relogin_lock = threading.Lock()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, *args, **kwargs):
        if not self._initialized:
            super(SingleSession, self).__init__(*args, **kwargs)
            self._initialized = True

    def get_relogin_lock(self):
        return self._relogin_lock


def setup_logger() -> logging.Logger:
    """
    This function sets up a logger that writes log messages to the console and,
    if the global variable DEV is set to True, also to a file named 'ace.log'.

    Returns:
        logger (logging.Logger): The configured logger object.

    The logger's name is set to 'ace.log'. The level of the logger and the console handler
    is set to INFO if DEV is True, and WARNING otherwise. The format for the log messages
    is: 'asctime' - 'name' - 'levelname' - 'message'.
    """
    logger = logging.getLogger("ace")
    level = logging.DEBUG if DEV else logging.INFO

    logger.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    file_handler = logging.FileHandler("ace.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()


DEFAULT_CONFIG = {
    "get_pnl": False,
    "get_stats": False,
    "save_pnl_file": False,
    "save_stats_file": False,
    "save_result_file": False,
    "check_submission": False,
    "check_self_corr": False,
    "check_prod_corr": False,
}

brain_api_url = os.environ.get("BRAIN_API_URL", "https://api.worldquantbrain.com")

SESSION_CACHE_PATH = os.path.join(os.path.expanduser("~"), "secrets", "brain-session.json")
SESSION_LOCK_PATH = os.path.join(os.path.expanduser("~"), "secrets", "brain-session.lock")

# Multi-container session/cred backend (mirrors web/server/ace_api/session_store.py
# — keep the key/env names in sync). Local CLI default = file + ~/secrets.
REDIS_SESSION_KEY = "brain:session"


def _session_backend_is_redis() -> bool:
    return os.environ.get("BRAIN_SESSION_BACKEND", "file").lower() == "redis"


def _session_redis():
    import redis  # local import: only needed on the redis backend
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


@contextmanager
def _session_login_lock():
    """Cross-process lock so only one process performs the login flow."""
    os.makedirs(os.path.dirname(SESSION_LOCK_PATH), exist_ok=True)
    fd = open(SESSION_LOCK_PATH, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        finally:
            fd.close()


def _read_cached_cookies() -> dict:
    """The cached cookie jar from Redis (multi-container) or the file (default)."""
    if _session_backend_is_redis():
        raw = _session_redis().get(REDIS_SESSION_KEY)
        return json.loads(raw) if raw else {}
    if not os.path.exists(SESSION_CACHE_PATH):
        return {}
    with open(SESSION_CACHE_PATH) as f:
        return json.load(f) or {}


def _save_session_cookies(s: "SingleSession") -> None:
    cookies = {c.name: c.value for c in s.cookies}
    if _session_backend_is_redis():
        _session_redis().set(REDIS_SESSION_KEY, json.dumps(cookies))
        logger.debug("Session cookies saved to Redis.")
        return
    os.makedirs(os.path.dirname(SESSION_CACHE_PATH), exist_ok=True)
    with open(SESSION_CACHE_PATH, "w") as f:
        json.dump(cookies, f)
    logger.debug("Session cookies saved to cache.")


def _load_session_cookies(s: "SingleSession") -> str:
    """Load cached cookies into ``s``. Returns a tri-state (all truthy except ""):

    - ``"live"``      — cookie present AND verified against BRAIN (expiry > 0).
    - ``"unverified"``— cookie present but the check failed *transiently*
                        (network/parse). We keep it rather than trigger a relogin
                        storm on a blip, but we do NOT know it's good.
    - ``""``          — no cookie, or BRAIN said it's expired (401/204). Caller
                        must do a fresh login.

    The distinction exists so callers don't print "restored — no face scan
    needed" over a cookie that's merely *assumed* good and may 401 on the next
    call (the contradictory-log bug).
    """
    try:
        cookies = _read_cached_cookies()
        if not cookies:
            return ""
        s.cookies.update(cookies)
        remaining = check_session_timeout(s)
        if remaining > 0:
            logger.info(f"Restored session from cache ({remaining}s remaining).")
            return "live"
        if remaining < 0:
            # Transient failure — keep cookies but flag them unverified.
            logger.debug("Session timeout check failed transiently — using cached cookies (unverified).")
            return "unverified"
        logger.info("Cached session expired — need fresh login.")
        s.cookies.clear()
        return ""
    except Exception as e:
        logger.debug(f"Could not restore session cache: {e}")
        s.cookies.clear()
        return ""


def get_credentials() -> tuple[str, str]:
    """
    Retrieve or prompt for platform credentials.

    This function attempts to read credentials from a JSON file in the user's home directory.
    If the file doesn't exist or is empty, it prompts the user to enter credentials and saves them.

    Returns:
        tuple: A tuple containing the email and password.

    Raises:
        json.JSONDecodeError: If the credentials file exists but contains invalid JSON.
    """

    # Multi-container (Railway): creds come from BRAIN_EMAIL/BRAIN_PASSWORD env;
    # no ~/secrets file is shared across containers. Falls back to the legacy
    # BRAIN_CREDENTIAL_* names. Local CLI default keeps the file behaviour below.
    if _session_backend_is_redis() or os.environ.get("BRAIN_EMAIL"):
        email = os.environ.get("BRAIN_EMAIL") or os.environ.get("BRAIN_CREDENTIAL_EMAIL")
        password = os.environ.get("BRAIN_PASSWORD") or os.environ.get("BRAIN_CREDENTIAL_PASSWORD")
        if email and password:
            return (email, password)

    credential_email = os.environ.get("BRAIN_CREDENTIAL_EMAIL")
    credential_password = os.environ.get("BRAIN_CREDENTIAL_PASSWORD")

    credentials_folder_path = os.path.join(os.path.expanduser("~"), "secrets")
    credentials_file_path = os.path.join(credentials_folder_path, "platform-brain.json")

    if Path(credentials_file_path).exists() and os.path.getsize(credentials_file_path) > 2:
        with open(credentials_file_path) as file:
            data = json.loads(file.read())
    else:
        os.makedirs(credentials_folder_path, exist_ok=True)
        if credential_email and credential_password:
            email = credential_email
            password = credential_password
        else:
            email = input("Email:\n")
            password = getpass.getpass(prompt="Password:")
        data = {"email": email, "password": password}
        with open(credentials_file_path, "w") as file:
            json.dump(data, file)
    return (data["email"], data["password"])


class BiometricAuthRequired(RuntimeError):
    """Raised when BRAIN needs a persona/biometric face-scan that cannot be
    satisfied in this process (no TTY) or is currently throttled by BRAIN.

    This is a FATAL, non-retryable condition: callers (e.g. the sim pipeline)
    must abort rather than re-call start_session in a loop — repeated attempts
    hammer /authentication and trip BRAIN's BIOMETRICS_THROTTLED lockout.
    """


class DailySignInLimit(BiometricAuthRequired):
    """Raised when BRAIN refuses further logins for the day ("exceeded the number
    of sign-ins allowed today") OR our own storm-guard trips first.

    Subclasses BiometricAuthRequired so every existing `except BiometricAuthRequired`
    handler already treats it as a pause-don't-storm wall. Sign-ins are capped per
    UTC day; retrying before the reset only wastes attempts (and can extend the
    block). Reuse the cached session; wait for the UTC reset.
    """


# Sign-in storm guard. BRAIN caps credential sign-ins per UTC day; a misclassified
# response or a fast 401 loop could burn that quota in seconds (and the old
# 401→wipe-creds→recurse path did exactly that). We refuse to fire more than
# _SIGNIN_MAX_IN_WINDOW real credential POSTs within _SIGNIN_WINDOW_S. Normal
# periodic refresh (sessions last hours) never trips this.
_SIGNIN_LOCK = threading.Lock()
_SIGNIN_TIMES: list = []
_SIGNIN_WINDOW_S = int(os.environ.get("BRAIN_SIGNIN_WINDOW_S", "180"))
_SIGNIN_MAX_IN_WINDOW = int(os.environ.get("BRAIN_MAX_SIGNINS", "3"))


def _note_signin_attempt() -> None:
    """Record one real credential sign-in; raise DailySignInLimit on a storm."""
    now = time.time()
    with _SIGNIN_LOCK:
        _SIGNIN_TIMES.append(now)
        _SIGNIN_TIMES[:] = [t for t in _SIGNIN_TIMES if now - t < _SIGNIN_WINDOW_S]
        n = len(_SIGNIN_TIMES)
    if n > _SIGNIN_MAX_IN_WINDOW:
        raise DailySignInLimit(
            f"Sign-in storm guard tripped: {n} credential sign-ins within "
            f"{_SIGNIN_WINDOW_S}s (max {_SIGNIN_MAX_IN_WINDOW}). Stopping to protect "
            "BRAIN's per-day sign-in quota — reuse the cached session instead. "
            "Tune with BRAIN_MAX_SIGNINS / BRAIN_SIGNIN_WINDOW_S."
        )


def _auth_detail(resp) -> str:
    try:
        return ((resp.json() or {}).get("detail") or resp.text or "")[:200]
    except ValueError:
        return (resp.text or "")[:200]


def _looks_like_signin_limit(resp) -> bool:
    """True if the response body is BRAIN's daily sign-in-cap message."""
    d = _auth_detail(resp).lower()
    return any(k in d for k in (
        "sign-in", "sign in", "signin", "allowed today", "try again tomorrow",
    ))


def start_session(force: bool = False) -> SingleSession:
    """
    Start a new session with the WorldQuant BRAIN platform.

    This function authenticates the user, handles biometric authentication if required,
    and creates a new session.

    Returns:
        SingleSession: An authenticated session object.

    Raises:
        requests.exceptions.RequestException: If there's an error during the authentication process.
    """

    s = SingleSession()
    s.cookies.clear()
    _start_session_called_at = time.time()

    # Try restoring from cached cookies before doing a full login
    if not force:
        cached = _load_session_cookies(s)
        if cached == "live":
            print("✅ Session restored from cache.")
            return s
        if cached == "unverified":
            # Don't over-promise: we couldn't confirm the cookie. Say so, so a
            # subsequent 401 reads as consistent, not contradictory.
            print("↺ Using cached session (couldn't verify — will re-auth if BRAIN rejects it).")
            return s

    # Serialize login across processes — only one runs the persona flow,
    # the rest pick up the refreshed cache once it's saved.
    with _session_login_lock():
        s.cookies.clear()
        # Re-check cache under the lock. If we were forced (cookies known bad),
        # only trust a cache that's been refreshed since this call started.
        cache_mtime_before = (
            os.path.getmtime(SESSION_CACHE_PATH)
            if os.path.exists(SESSION_CACHE_PATH) else 0
        )
        if force:
            # Only accept cache if another process refreshed it after we knew ours was bad.
            if cache_mtime_before > _start_session_called_at and _load_session_cookies(s):
                print("✅ Session restored from cache (refreshed by another process).")
                return s
        else:
            cached = _load_session_cookies(s)
            if cached == "live":
                print("✅ Session restored from cache.")
                return s
            if cached == "unverified":
                print("↺ Using cached session (couldn't verify — will re-auth if BRAIN rejects it).")
                return s

        s.auth = get_credentials()
        _note_signin_attempt()  # storm guard — raises before we can burn the daily quota
        r = s.post(brain_api_url + "/authentication")
        logger.debug(f"New session created (ID: {id(s)}) with authentication response: {r.status_code}, {r.json()}")
        # BRAIN's per-day sign-in cap can arrive with any status code — check the
        # message before anything else so we never mislabel it or retry into it.
        if _looks_like_signin_limit(r):
            raise DailySignInLimit(
                f"BRAIN daily sign-in limit reached (HTTP {r.status_code}: {_auth_detail(r)}). "
                "Sign-ins are capped per UTC day — STOP now and retry only after the UTC "
                "reset. Retrying sooner just wastes attempts; the session won't mint."
            )
        if r.status_code == requests.status_codes.codes.too_many_requests:
            # 429 here is usually BIOMETRICS_THROTTLED — BRAIN throttling the
            # persona challenge after too many (often incomplete) attempts. It is
            # NOT a transient per-request rate limit and won't clear by retrying;
            # retrying only deepens the lockout. Treat as fatal so callers abort.
            detail = ""
            try:
                detail = (r.json() or {}).get("detail") or r.text[:200]
            except ValueError:
                detail = r.text[:200]
            raise BiometricAuthRequired(
                f"BRAIN authentication throttled (HTTP 429: {detail}). This is "
                "BRAIN's biometric/persona throttle — it must age out and cannot be "
                "cleared by retrying. Stop all login attempts; once it lifts, "
                "re-authenticate via the web console (⚠ LOGIN) and complete the face scan."
            )
        if r.status_code == requests.status_codes.codes.unauthorized:
            if r.headers["WWW-Authenticate"] == "persona":
                persona_url = urljoin(r.url, r.headers["Location"])
                # Biometric (persona) verification needs a human + a browser. In a
                # headless worker (no TTY) input() would hit EOF and crash the run,
                # so fail with an actionable message instead — the supported path is
                # to re-auth through the web console, which caches the session.
                try:
                    _interactive = os.isatty(0)
                except OSError:
                    _interactive = False
                if not _interactive:
                    raise BiometricAuthRequired(
                        "BRAIN session needs biometric (persona) re-verification, but "
                        "this process is non-interactive. Re-authenticate via the web "
                        "console (the ⚠ LOGIN button) — or open this URL, complete the "
                        "face scan, then retry:\n" + persona_url
                    )
                print(
                    "Complete biometrics authentication and press any key to continue: \n"
                    + persona_url
                    + "\n"
                )
                while True:
                    input()
                    check = s.post(persona_url)
                    if check.status_code == 201:
                        print("✅ Biometrics verified — session is valid.")
                        _save_session_cookies(s)
                        break
                    # Not verified — get a fresh link and prompt again
                    print("❌ Biometrics not verified yet.")
                    r = s.post(brain_api_url + "/authentication")
                    if r.status_code == requests.status_codes.codes.unauthorized and r.headers.get("WWW-Authenticate") == "persona":
                        persona_url = urljoin(r.url, r.headers["Location"])
                        print(
                            "Here is a new link:\n"
                            + persona_url
                            + "\n"
                            + "Complete it and press any key to continue.\n"
                        )
                    elif r.status_code == 201:
                        print("✅ Session is now valid.")
                        _save_session_cookies(s)
                        break
                    else:
                        print(
                            "Authentication is not complete. Please try again and press any key when completed.\n"
                        )
            else:
                # 401 that isn't a persona challenge. Could be bad credentials OR an
                # account/rate message (e.g. the daily sign-in cap) delivered as a 401.
                # NEVER blindly wipe creds + recurse here — that recursion is itself a
                # sign-in storm (each call POSTs /authentication) and nukes saved creds.
                if _looks_like_signin_limit(r):
                    raise DailySignInLimit(
                        f"BRAIN refused sign-in (401: {_auth_detail(r)}). Daily sign-in "
                        "cap — stop and retry after the UTC reset."
                    )
                try:
                    _interactive = os.isatty(0)
                except OSError:
                    _interactive = False
                if not _interactive:
                    # Headless: don't wipe creds, don't recurse — surface and stop.
                    raise DailySignInLimit(
                        f"BRAIN sign-in rejected (401: {_auth_detail(r)}). Not re-prompting "
                        "in a non-interactive run; check credentials / wait for the UTC reset."
                    )
                logger.error("\nIncorrect email or password\n")
                with open(
                    os.path.join(os.path.expanduser("~"), "secrets/platform-brain.json"),
                    "w",
                ) as file:
                    json.dump({}, file)
                return start_session()
        else:
            # Successful login without biometrics — save cookies too
            _save_session_cookies(s)
    return s


def check_session_timeout(s: SingleSession) -> int:
    """
    Check if the current session has timed out.

    Args:
        s (SingleSession): The current session object.

    Returns:
        int: The number of seconds until the session expires, or 0 if the session has expired or an error occurred.
    """

    authentication_url = brain_api_url + "/authentication"
    try:
        resp = s.get(authentication_url)
    except Exception as e:
        logger.debug(f"Session timeout check network error — treating as transient: {e}")
        return -1
    if resp.status_code == 401:
        return 0
    # A dead `t` cookie makes BRAIN answer GET /authentication with 204 No Content
    # (or any empty body) instead of 401. That is an EXPIRED session, not a
    # transient blip — treating it as transient is what makes us "restore from
    # cache" a cookie that then 401s on the very next call.
    if resp.status_code == 204 or not resp.content:
        logger.debug(f"Session timeout check: status={resp.status_code}, empty body — session expired.")
        return 0
    try:
        result = resp.json()["token"]["expiry"]
        logger.debug(f"Session (ID: {id(s)}) timeout check result: {result}")
        return result
    except Exception as e:
        logger.debug(
            f"Session timeout check parse error (status={resp.status_code}, "
            f"len={len(resp.content)}) — treating as transient: {e}"
        )
        return -1


def generate_alpha(
    regular: Optional[str] = None,
    selection: Optional[str] = None,
    combo: Optional[str] = None,
    alpha_type: Literal["REGULAR", "SUPER"] = "REGULAR",
    region: str = "USA",
    universe: str = "TOP3000",
    delay: Literal[0, 1] = 1,
    decay: int = 0,
    neutralization: str = "INDUSTRY",
    truncation: float = 0.08,
    pasteurization: Literal["ON", "OFF"] = "ON",
    test_period: str = "P0Y0M0D",
    unit_handling: Literal["VERIFY"] = "VERIFY",
    nan_handling: Literal["ON", "OFF"] = "OFF",
    max_trade: Literal["ON", "OFF"] = "OFF",
    selection_handling: str = "POSITIVE",
    selection_limit: int = 100,
    visualization: bool = False,
) -> dict:
    """
    Generate an alpha dictionary for simulation. If alpha_type='REGULAR',
    function generates alpha dictionary using regular input. If alpha_type='SUPER',
    function generates alpha dictionary using selection and combo inputs.

    Args:
        regular (str, optional): The regular alpha expression.
        selection (str, optional): The selection expression for super alphas.
        combo (str, optional): The combo expression for super alphas.
        alpha_type (str, optional): The type of alpha ("REGULAR" or "SUPER"). Defaults to "REGULAR".
        region (str, optional): The region for the alpha. Defaults to "USA".
        universe (str, optional): The universe for the alpha. Defaults to "TOP3000".
        delay (int, optional): The delay for the alpha. Defaults to 1.
        decay (int, optional): The decay for the alpha. Defaults to 0.
        neutralization (str, optional): The neutralization method. Defaults to "INDUSTRY".
        truncation (float, optional): The truncation value. Defaults to 0.08.
        pasteurization (str, optional): The pasteurization setting. Defaults to "ON".
        test_period (str, optional): The test period. Defaults to "P0Y0M0D".
        unit_handling (str, optional): The unit handling method. Defaults to "VERIFY".
        nan_handling (str, optional): The NaN handling method. Defaults to "OFF".
        max_trade (str, optional): The max trade method. Defaults to "OFF".
        selection_handling (str, optional): The selection handling method for super alphas. Defaults to "POSITIVE".
        selection_limit (int, optional): The selection limit for super alphas. Defaults to 100.
        visualization (bool, optional): Whether to include visualization. Defaults to False.

    Returns:
        dict: A dictionary containing the alpha configuration for simulation.

    Raises:
        ValueError: If an invalid alpha_type is provided.
    """

    settings = {
        "instrumentType": "EQUITY",
        "region": region,
        "universe": universe,
        "delay": delay,
        "decay": decay,
        "neutralization": neutralization,
        "truncation": truncation,
        "pasteurization": pasteurization,
        "testPeriod": test_period,
        "unitHandling": unit_handling,
        "nanHandling": nan_handling,
        "maxTrade": max_trade,
        "language": "FASTEXPR",
        "visualization": visualization,
    }
    if alpha_type == "REGULAR":
        simulation_data = {
            "type": alpha_type,
            "settings": settings,
            "regular": regular,
        }
    elif alpha_type == "SUPER":
        simulation_data = {
            "type": alpha_type,
            "settings": {
                **settings,
                "selectionHandling": selection_handling,
                "selectionLimit": selection_limit,
            },
            "combo": combo,
            "selection": selection,
        }
    else:
        logger.error("alpha_type should be REGULAR or SUPER")
        return {}
    return simulation_data


def check_session_and_relogin(s: SingleSession) -> SingleSession:
    """
    Checks for session timeout and if less than 2000 seconds are remaining,
    it attempts to start a new session.

    Parameters:
        s (SingleSession): The current session object.

    Returns:
        s (SingleSession): The original session object if it hasn't timed out,
        otherwise a new session object.

    If the remaining session time is less than 2000 seconds, the function
    attempts to start a new session using the `start_session()` function.
    If `start_session()` fails on the first attempt, it waits for 100 seconds
    and then tries again. The function then returns the new session object.
    """
    with s.get_relogin_lock():
        remaining = check_session_timeout(s)
        if 0 <= remaining < 2000:
            logger.debug('Session less than 2000 seconds')
            try:
                s = start_session()
            except BiometricAuthRequired:
                raise  # fatal — no point waiting + retrying a biometric wall
            except Exception:
                logger.info('Trying re-login, wait 100 seconds')
                time.sleep(100)
                s = start_session()
        logger.debug(f"Session (ID: {id(s)}) after check and relogin")
    return s


def start_simulation(s: SingleSession, simulate_data: Union[list[dict], dict]) -> requests.Response:
    """
    Start a simulation with the provided simulation data.

    Args:
        s (SingleSession): An authenticated session object.
        simulate_data (dict): A dictionary containing the simulation parameters.

    Returns:
        requests.Response: The response object from the simulation start request.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """
    simulate_response = s.post(brain_api_url + "/simulations", json=simulate_data)
    return simulate_response


def simulation_progress(
    s: SingleSession,
    simulate_response: requests.Response,
) -> dict:
    """
    Monitor the progress of a simulation and return the result when complete.

    Args:
        s (SingleSession): An authenticated session object.
        simulate_response (requests.Response): The response from starting the simulation.

    Returns:
        dict: A dictionary containing the completion status and simulation result.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API requests.
    """
    if simulate_response.status_code // 100 != 2:
        logger.warning(f'Simulation failed. {simulate_response.text}, Status code: {simulate_response.status_code}')
        return {"completed": False, "result": {}}

    simulation_progress_url = simulate_response.headers["Location"]
    error_flag = False
    retry_count = 0
    while True:
        simulation_progress_response = s.get(simulation_progress_url)
        if simulation_progress_response.status_code // 100 != 2:
            logger.error(
                f'Simulation {simulation_progress_url}, Status code: {simulation_progress_response.status_code}, Retry'
            )
            time.sleep(30)
            retry_count += 1
            if retry_count <= 2:
                continue
            else:
                logger.error(
                    f'Simulation {simulation_progress_url} failed, Status code: {simulation_progress_response.status_code}'
                )
                error_flag = True
                break
        if simulation_progress_response.headers.get("Retry-After", 0) == 0:
            if simulation_progress_response.json().get("status", "ERROR") == "ERROR":
                error_flag = True
            break

        time.sleep(float(simulation_progress_response.headers["Retry-After"]))

    if error_flag:
        logger.error(f"Simulation failed. {simulation_progress_response.json()}")
        return {"completed": False, "result": {}}

    alpha = simulation_progress_response.json().get("alpha", 0)
    if alpha == 0:
        logger.warning(
            f'Simulation {simulation_progress_response.json().get("id")} failed. {simulation_progress_response.json()}'
        )
        return {"completed": False, "result": {}}
    simulation_result = get_simulation_result_json(s, alpha)
    if len(simulation_result) == 0:
        return {"completed": False, "result": {}}
    return {"completed": True, "result": simulation_result}


def get_simulation_result_json(s: SingleSession, alpha_id: str) -> dict:
    """
    Retrieve the full simulation result for a specific alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.

    Returns:
        dict: A dictionary containing the full simulation result.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """
    if alpha_id is None:
        return {}
    while True:
        result = s.get(brain_api_url + "/alphas/" + alpha_id)
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    try:
        return result.json()
    except Exception:
        logger.error(f"alpha_id {alpha_id}, {result.headers}, {result.text}, {result.status_code}")
        return {}
    return s.get(brain_api_url + "/alphas/" + alpha_id).json()


def multisimulation_progress(
    s: SingleSession,
    simulate_response: requests.Response,
) -> dict:
    """
    Monitor the progress of multiple simulations and return the results when complete.

    Args:
        s (SingleSession): An authenticated session object.
        simulate_response (requests.Response): The response from starting the simulations.

    Returns:
        dict: A dictionary containing the completion status and simulation results.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API requests.
    """
    if simulate_response.status_code // 100 != 2:
        logger.warning(f'Simulation failed. {simulate_response.text}, Status code: {simulate_response.status_code}')
        return {"completed": False, "result": {}}

    simulation_progress_url = simulate_response.headers["Location"]
    error_flag = False
    while True:
        simulation_progress_response = s.get(simulation_progress_url)
        if simulation_progress_response.status_code // 100 != 2:
            time.sleep(30)
        if simulation_progress_response.headers.get("Retry-After", 0) == 0:
            if simulation_progress_response.json().get("status", "ERROR") == "ERROR":
                error_flag = True
            break

        time.sleep(float(simulation_progress_response.headers["Retry-After"]))

    children = simulation_progress_response.json().get("children", 0)

    if error_flag:
        if children == 0:
            logger.error(f"Simulation failed. {simulation_progress_response.json()}")
            return {"completed": False, "result": {}}
        for child in children:
            child_progress = s.get(brain_api_url + "/simulations/" + child)
            logger.error(f"Child Simulation failed: {child_progress.json()}")
        return {"completed": False, "result": {}}

    if len(children) == 0:
        logger.warning(
            f'Multi-Simulation {simulation_progress_response.json().get("id")} failed. {simulation_progress_response.json()}'
        )
        return {"completed": False, "result": {}}
    children_list = []
    for child in children:
        child_progress = s.get(brain_api_url + "/simulations/" + child)
        alpha = child_progress.json().get("alpha", 0)
        if alpha == 0:
            logger.warning(f'Child-Simulation {child_progress.json().get("id")} failed. {child_progress.json()}')
            return {"completed": False, "result": {}}
        child_result = get_simulation_result_json(s, alpha)
        children_list.append(child_result)
    return {"completed": True, "result": children_list}


def get_prod_corr(s: SingleSession, alpha_id: str) -> pd.DataFrame:
    """
    Retrieve the production correlation data for a specific alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.

    Returns:
        pandas.DataFrame: A DataFrame containing the production correlation data.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """

    while True:
        result = s.get(brain_api_url + "/alphas/" + alpha_id + "/correlations/prod")
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    if result.json().get("records", 0) == 0:
        logger.warning(f"Failed to get production correlation for alpha_id {alpha_id}. {result.json()}")
        return pd.DataFrame()
    columns = [dct["name"] for dct in result.json()["schema"]["properties"]]
    prod_corr_df = pd.DataFrame(result.json()["records"], columns=columns).assign(alpha_id=alpha_id)
    prod_corr_df["alpha_max_prod_corr"] = result.json()["max"]
    prod_corr_df["alpha_min_prod_corr"] = result.json()["min"]

    return prod_corr_df


def check_prod_corr_test(s: SingleSession, alpha_id: str, threshold: float = 0.7) -> pd.DataFrame:
    """
    Check if the alpha's production correlation passes a specified threshold.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.
        threshold (float, optional): The correlation threshold. Defaults to 0.7.

    Returns:
        pandas.DataFrame: A DataFrame containing the test result.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """

    prod_corr_df = get_prod_corr(s, alpha_id)
    if prod_corr_df.empty:
        result = [
            {
                "test": "PROD_CORRELATION",
                "result": "NONE",
                "limit": threshold,
                "value": None,
                "alpha_id": alpha_id,
            }
        ]
    else:
        value = prod_corr_df[prod_corr_df.alphas > 0]["max"].max()
        result = [
            {
                "test": "PROD_CORRELATION",
                "result": "PASS" if value <= threshold else "FAIL",
                "limit": threshold,
                "value": value,
                "alpha_id": alpha_id,
            }
        ]
    return pd.DataFrame(result)


def get_self_corr(s: SingleSession, alpha_id: str) -> pd.DataFrame:
    """
    Retrieve the self-correlation data for a specific alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.

    Returns:
        pandas.DataFrame: A DataFrame containing the self-correlation data.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """

    while True:
        result = s.get(brain_api_url + "/alphas/" + alpha_id + "/correlations/self")
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    if result.json().get("records", 0) == 0:
        logger.warning(f"Failed to get self correlation for alpha_id {alpha_id}. {result.json()}")
        return pd.DataFrame()

    records_len = len(result.json()["records"])
    if records_len == 0:
        logger.warning(f"No self correlation for alpha_id {alpha_id}")
        return pd.DataFrame()

    columns = [dct["name"] for dct in result.json()["schema"]["properties"]]
    self_corr_df = pd.DataFrame(result.json()["records"], columns=columns).assign(alpha_id=alpha_id)
    self_corr_df["alpha_max_self_corr"] = result.json()["max"]
    self_corr_df["alpha_min_self_corr"] = result.json()["min"]

    return self_corr_df


def check_self_corr_test(s: SingleSession, alpha_id: str, threshold: float = 0.7) -> pd.DataFrame:
    """
    Check if the alpha's self-correlation passes a specified threshold.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.
        threshold (float, optional): The correlation threshold. Defaults to 0.7.

    Returns:
        pandas.DataFrame: A DataFrame containing the test result.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """

    self_corr_df = get_self_corr(s, alpha_id)
    if self_corr_df.empty:
        result = [
            {
                "test": "SELF_CORRELATION",
                "result": "PASS",
                "limit": threshold,
                "value": 0,
                "alpha_id": alpha_id,
            }
        ]
    else:
        value = self_corr_df["correlation"].max()
        result = [
            {
                "test": "SELF_CORRELATION",
                "result": "PASS" if value < threshold else "FAIL",
                "limit": threshold,
                "value": value,
                "alpha_id": alpha_id,
            }
        ]
    return pd.DataFrame(result)


def get_check_submission(s: SingleSession, alpha_id: str) -> pd.DataFrame:
    """
    Retrieve the submission check results for a specific alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.

    Returns:
        pandas.DataFrame: A DataFrame containing the submission check results.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """

    while True:
        result = s.get(brain_api_url + "/alphas/" + alpha_id + "/check")
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    if result.json().get("is", 0) == 0:
        logger.warning(f"Cant check submission alpha_id {alpha_id}. {result.json()}")
        return pd.DataFrame()

    checks_df = pd.DataFrame(result.json()["is"]["checks"]).assign(alpha_id=alpha_id)

    return checks_df


def simulate_multi_alpha(
    s: SingleSession,
    simulate_data_list: list,
) -> list[dict]:
    """
    Simulate a list of alphas using multi-simulation.

    This function checks the session timeout, starts a new session if necessary,
    initiates the simulation, monitors its progress, and sets alpha properties
    upon completion.

    Args:
        s (SingleSession): An authenticated session object.
        simulate_data (dict): A list of dictionaries, each containing the simulation parameters for the alpha.
            These should include all necessary information such as alpha type, settings, and expressions.

    Returns:
        list: A list of dictionaries, each containing:
            - 'alpha_id' (str): The ID of the simulated alpha if successful, None otherwise.
            - 'simulate_data' (dict): The original simulation data provided.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API requests.
    """

    s = check_session_and_relogin(s)
    if len(simulate_data_list) == 1:
        return [simulate_single_alpha(s, simulate_data_list[0])]
    simulate_response = start_simulation(s, simulate_data_list)
    simulation_result = multisimulation_progress(s, simulate_response)

    if not simulation_result["completed"]:
        return [{"alpha_id": None, "simulate_data": x} for x in simulate_data_list]
    result = [
        {
            "alpha_id": x["id"],
            "simulate_data": {
                "type": x["type"],
                "settings": x["settings"],
                "regular": x["regular"]["code"],
            },
        }
        for x in simulation_result["result"]
    ]
    # _ = [set_alpha_properties(s, x["id"]) for x in simulation_result["result"]]
    return result


def get_specified_alpha_stats(
    s: SingleSession,
    alpha_id: Union[str, None],
    simulate_data: dict,
    get_pnl: bool = False,
    get_stats: bool = False,
    save_pnl_file: bool = False,
    save_stats_file: bool = False,
    save_result_file: bool = False,
    check_submission: bool = False,
    check_self_corr: bool = False,
    check_prod_corr: bool = False,
) -> dict:
    """
    Retrieve and process specified statistics for a given alpha.

    Args:
        s (SingleSession): The authenticated session object.
        alpha_id (str): The ID of the alpha to retrieve statistics for.
        simulate_data (dict): The original simulation data for the alpha.
        get_pnl (bool, optional): Whether to retrieve PnL data. Defaults to False.
        get_stats (bool, optional): Whether to retrieve yearly stats. Defaults to False.
        save_pnl_file (bool, optional): Whether to save PnL data to a file. Defaults to False.
        save_stats_file (bool, optional): Whether to save yearly stats to a file. Defaults to False.
        save_result_file (bool, optional): Whether to save the simulation result to a file. Defaults to False.
        check_submission (bool, optional): Whether to perform submission checks. Defaults to False.
        check_self_corr (bool, optional): Whether to check self-correlation. Defaults to False.
        check_prod_corr (bool, optional): Whether to check production correlation. Defaults to False.

    Returns:
        dict: A dictionary containing various statistics and information about the alpha.

    Raises:
        requests.exceptions.RequestException: If there's an error retrieving data from the API.
    """
    pnl = None
    stats = None
    s = check_session_and_relogin(s)
    logger.debug(f"Session (ID: {id(s)}) used in get_specified_alpha_stats for alpha_id: {alpha_id}")
    if alpha_id is None:
        return {
            "alpha_id": None,
            "simulate_data": simulate_data,
            "is_stats": None,
            "pnl": pnl,
            "stats": stats,
            "is_tests": None,
            "train": None,
            "test": None,
        }

    result = get_simulation_result_json(s, alpha_id)
    try:
        region = result["settings"]["region"]
        is_stats = pd.DataFrame([{key: value for key, value in result['is'].items() if key != 'checks'}]).assign(
            alpha_id=alpha_id
        )
    except Exception as e:
        logger.error(f"Failed to retrieve simulation result for alpha_id {alpha_id}: {result}, {e}")
    train = result["train"]
    test = result["test"]
    is_stats = pd.DataFrame([{key: value for key, value in result["is"].items() if key != "checks"}]).assign(
        alpha_id=alpha_id
    )

    if get_pnl:
        pnl = get_alpha_pnl(s, alpha_id)
        if save_pnl_file:
            save_pnl(pnl, alpha_id, region)

    if get_stats:
        stats = get_alpha_yearly_stats(s, alpha_id)
        if save_stats_file:
            save_yearly_stats(stats, alpha_id, region)

    if save_result_file:
        save_simulation_result(result)

    is_tests = pd.DataFrame(result["is"]["checks"]).assign(alpha_id=alpha_id)

    if check_submission:
        is_tests = get_check_submission(s, alpha_id)

        return {
            "alpha_id": alpha_id,
            "simulate_data": simulate_data,
            "is_stats": is_stats,
            "pnl": pnl,
            "stats": stats,
            "is_tests": is_tests,
            "train": train,
            "test": test,
        }

    if check_self_corr and not check_submission:
        self_corr_test = check_self_corr_test(s, alpha_id)
        is_tests = (
            pd.concat([is_tests, pd.DataFrame([self_corr_test])], ignore_index=True)
            .drop_duplicates(subset=["test"], keep="last")
            .reset_index(drop=True)
        )
    if check_prod_corr and not check_submission:
        prod_corr_test = check_prod_corr_test(s, alpha_id)
        is_tests = (
            pd.concat([is_tests, pd.DataFrame([prod_corr_test])], ignore_index=True)
            .drop_duplicates(subset=["test"], keep="last")
            .reset_index(drop=True)
        )

    return {
        "alpha_id": alpha_id,
        "simulate_data": simulate_data,
        "is_stats": is_stats,
        "pnl": pnl,
        "stats": stats,
        "is_tests": is_tests,
        "train": train,
        "test": test,
    }


def simulate_single_alpha(
    s: SingleSession,
    simulate_data: dict,
) -> dict:
    """
    Simulate a single alpha using the provided session and simulation data.

    This function checks the session timeout, starts a new session if necessary,
    initiates the simulation, monitors its progress, and sets alpha properties
    upon completion.

    Args:
        s (SingleSession): An authenticated session object.
        simulate_data (dict): A dictionary containing the simulation parameters for the alpha.
            This should include all necessary information such as alpha type, settings, and expressions.

    Returns:
        dict: A dictionary containing:
            - 'alpha_id' (str): The ID of the simulated alpha if successful, None otherwise.
            - 'simulate_data' (dict): The original simulation data provided.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API requests.
    """

    s = check_session_and_relogin(s)
    simulate_response = start_simulation(s, simulate_data)
    simulation_result = simulation_progress(s, simulate_response)

    if not simulation_result["completed"]:
        return {"alpha_id": None, "simulate_data": simulate_data}
    return {
        "alpha_id": simulation_result["result"]["id"],
        "simulate_data": simulate_data,
    }


def simulate_alpha_list(
    s: SingleSession,
    alpha_list: list,
    limit_of_concurrent_simulations: int = 3,
    simulation_config: dict = DEFAULT_CONFIG,
) -> list:
    """
    Simulate a list of alphas concurrently.

    Args:
        s (SingleSession): The authenticated session object.
        alpha_list (list): A list of alpha configurations to simulate.
        limit_of_concurrent_simulations (int, optional): The maximum number of concurrent simulations. Defaults to 3.
        simulation_config (dict, optional): Configuration for the simulation. Defaults to DEFAULT_CONFIG.

    Returns:
        list: A list of dictionaries containing simulation results for each alpha.

    Raises:
        requests.exceptions.RequestException: If there's an error during the simulation process.
    """
    if (limit_of_concurrent_simulations < 1) or (limit_of_concurrent_simulations > 8):
        logger.warning("Limit of concurrent simulation should be 1..8, will be set to 3")
        limit_of_concurrent_simulations = 3

    result_list = []

    with ThreadPool(limit_of_concurrent_simulations) as pool:
        with tqdm.tqdm(total=len(alpha_list)) as pbar:
            for result in pool.imap_unordered(partial(simulate_single_alpha, s), alpha_list):
                result_list.append(result)
                pbar.update()

    stats_list_result = []

    def func(x):
        return get_specified_alpha_stats(s, x["alpha_id"], x["simulate_data"], **simulation_config)

    with ThreadPool(3) as pool:
        for result in pool.map(func, result_list):
            stats_list_result.append(result)

    return _delete_duplicates_from_result(stats_list_result)


def simulate_alpha_list_multi(
    s: SingleSession,
    alpha_list: list,
    limit_of_concurrent_simulations: int = 3,
    limit_of_multi_simulations: int = 10,
    simulation_config: dict = DEFAULT_CONFIG,
) -> list:
    """
    Simulate a list of alphas using multi-simulation when possible.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_list (list): A list of alpha configurations to simulate.
        limit_of_concurrent_simulations (int, optional): The maximum number of concurrent simulation batches. Defaults to 3.
        limit_of_multi_simulations (int, optional): The maximum number of alphas in a multi-simulation. Defaults to 3.
        simulation_config (dict, optional): Configuration for the simulation. Defaults to DEFAULT_CONFIG.

    Returns:
        list: A list of dictionaries containing simulation results for each alpha.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API requests.
    """
    if (limit_of_multi_simulations < 2) or (limit_of_multi_simulations > 10):
        logger.warning("Limit of multi-simulation should be 2..10, will be set to 10")
        limit_of_multi_simulations = 10
    if (limit_of_concurrent_simulations < 1) or (limit_of_concurrent_simulations > 8):
        logger.warning("Limit of concurrent simulation should be 1..8, will be set to 3")
        limit_of_concurrent_simulations = 3
    if any(d["type"] == "SUPER" for d in alpha_list):
        logger.warning("Multi-Simulation is not supported for SuperAlphas, single concurrent simulations will be used")
        return simulate_alpha_list(
            s,
            alpha_list,
            limit_of_concurrent_simulations=3,
            simulation_config=simulation_config,
        )

    tasks = [
        alpha_list[i : i + limit_of_multi_simulations] for i in range(0, len(alpha_list), limit_of_multi_simulations)
    ]
    result_list = []

    with ThreadPool(limit_of_concurrent_simulations) as pool:
        with tqdm.tqdm(total=len(tasks)) as pbar:
            for result in pool.imap_unordered(partial(simulate_multi_alpha, s), tasks):
                result_list.append(result)
                pbar.update()
    result_list_flat = [item for sublist in result_list for item in sublist]

    stats_list_result = []

    def func(x):
        return get_specified_alpha_stats(s, x["alpha_id"], x["simulate_data"], **simulation_config)

    with ThreadPool(3) as pool:
        for result in pool.map(func, result_list_flat):
            stats_list_result.append(result)

    return _delete_duplicates_from_result(stats_list_result)


def _delete_duplicates_from_result(result: list) -> list:
    """
    Remove duplicate alpha results from the simulation output.

    Args:
        result (list): A list of dictionaries containing simulation results.

    Returns:
        list: A deduplicated list of simulation results.
    """
    alpha_id_lst = []
    result_new = []
    for x in result:
        if x["alpha_id"] is not None:
            if x["alpha_id"] not in alpha_id_lst:
                result_new.append(x)
                alpha_id_lst.append(x["alpha_id"])
        else:
            result_new.append(x)
    return result_new


def set_alpha_properties(
    s: SingleSession,
    alpha_id: str,
    name: Union[str, object] = _UNSET,
    color: Union[str, object] = _UNSET,
    category: Union[Category, object] = _UNSET,
    regular_desc: Union[str, object] = _UNSET,
    selection_desc: Union[str, object] = _UNSET,
    combo_desc: Union[str, object] = _UNSET,
    osmosis_points: Union[int, object] = _UNSET,
    tags: Union[list[str], object] = _UNSET,
) -> requests.Response:
    """
    Update the properties of an alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha to update.
        name (str, optional): The new name for the alpha. If not ptovided - is not changed.
            If set to None - description is removed.
        color (str, optional): The new color for the alpha. If not ptovided - is not changed.
            If set to None - color is removed.
        category (str, optional): Alpha category. If not ptovided - is not changed.
            If set to None - category is removed.
        regular_desc (str, optional): Description for regular alpha. If not ptovided - is not changed.
            If set to None - description is removed.
        selection_desc (str, optional): Description for the selection part of a super alpha. If not ptovided - is not changed.
        combo_desc (str, optional): Description for the combo part of a super alpha. If not ptovided - is not changed.
        osmosis_points (int, optional): Osmosis points, int from 1 to 100_000. If not ptovided - is not changed.
            If set to None - points are removed.
        tags (list, optional): List of tags to apply to the alpha. If not ptovided - is not changed.
            If set to empty list - [] tags are removed.

    Returns:
        requests.Response: The response object from the API call.
    """

    if osmosis_points is not _UNSET and osmosis_points is not None:
        if not isinstance(osmosis_points, int):
            raise TypeError(f"osmosis_points must be int or None, got {type(osmosis_points)!r}")
        if not (1 <= osmosis_points <= 100_000):
            raise ValueError(f"osmosis_points must be between 1 and 100000, got {osmosis_points}")
    option_map = {
        "name": name,
        "color": color,
        "category": category,
        "tags": tags,
        "osmosisPoints": osmosis_points,
        "regular": {"description": regular_desc} if regular_desc is not _UNSET else _UNSET,
        "selection": {"description": selection_desc} if selection_desc is not _UNSET else _UNSET,
        "combo": {"description": combo_desc} if combo_desc is not _UNSET else _UNSET,
    }
    params = {k: v for k, v in option_map.items() if v is not _UNSET}
    response = s.patch(brain_api_url + "/alphas/" + alpha_id, json=params)

    return response


def submit_alpha(s: SingleSession, alpha_id: str) -> requests.Response:
    """
    Submit an alpha for production consideration.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha to submit.

    Returns:
        requests.Response: The response object from the API call.
    """
    result = s.post(brain_api_url + "/alphas/" + alpha_id + "/submit")
    return result


def _get_alpha_pnl(
    s: SingleSession,
    alpha_id: str,
    pnl_type: str = "pnl",
) -> pd.DataFrame:
    """
    Retrieve the PnL data for a specific alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.
        pnl_type (str): 'pnl' to get cumulative pnl, 'daily-pnl' to get daily pnl.

    Returns:
        pandas.DataFrame: A DataFrame containing the PnL data for the alpha.
    """

    while True:
        result = s.get(brain_api_url + "/alphas/" + alpha_id + f"/recordsets/{pnl_type}")
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    pnl = result.json()
    if pnl.get("records", 0) == 0:
        return pd.DataFrame()
    columns = [dct["name"] for dct in pnl["schema"]["properties"]]
    pnl_df = (
        pd.DataFrame(pnl["records"], columns=columns)
        .assign(alpha_id=alpha_id, date=lambda x: pd.to_datetime(x.date, format="%Y-%m-%d"))
        .set_index("date")
    )
    return pnl_df


def get_alpha_pnl(s: SingleSession, alpha_id: str) -> pd.DataFrame:
    """
    Retrieve the cumulative PnL data for a specific alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.

    Returns:
        pandas.DataFrame: A DataFrame containing the PnL data for the alpha.
    """

    return _get_alpha_pnl(s, alpha_id, "pnl")


def get_alpha_yearly_stats(s: SingleSession, alpha_id: str) -> pd.DataFrame:
    """
    Retrieve the yearly statistics for a specific alpha.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.

    Returns:
        pandas.DataFrame: A DataFrame containing the yearly statistics for the alpha.
    """

    while True:
        result = s.get(brain_api_url + "/alphas/" + alpha_id + "/recordsets/yearly-stats")
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    stats = result.json()

    if stats.get("records", 0) == 0:
        return pd.DataFrame()
    columns = [dct["name"] for dct in stats["schema"]["properties"]]
    yearly_stats_df = pd.DataFrame(stats["records"], columns=columns).assign(alpha_id=alpha_id)
    return yearly_stats_df


def _check_rate_limit(response: requests.Response) -> None:
    """Sleep based on rate-limit headers."""

    header_keys = {
        "limit_minute": "x-ratelimit-limit-minute",
        "remaining_minute": "x-ratelimit-remaining-minute",
        "limit_second": "x-ratelimit-limit-second",
        "remaining_second": "x-ratelimit-remaining-second",
    }
    parsed = {}
    for key, header_name in header_keys.items():
        val = response.headers.get(header_name)
        if val is None:
            logger.warning(f"Failed to parse rate-limit values: missing header {header_name}")
            return
        try:
            parsed[key] = int(val)
        except (ValueError, TypeError):
            parsed[key] = 30
            logger.warning(f"Failed to parse rate-limit values: cannot convert {header_name}={val} to int")
            return
    logger.debug(
        f"""
        Rate limit:
        remaining_minute={parsed["remaining_minute"]},
        limit_minute={parsed["limit_minute"]};
        remaining_second={parsed["remaining_second"]},
        limit_second={parsed["limit_second"]}
        """
    )
    if parsed["remaining_second"] < 1:
        logger.debug(f"Status code: {response.status_code}, sleep 1 sec")
        time.sleep(1)
    if parsed["remaining_minute"] <= 1:
        logger.info(f"Rate limit {parsed["limit_minute"]} reached (per minute). Sleeping for a minute...")
        time.sleep(60)


def get_datasets(
    s: SingleSession,
    instrument_type: str = "EQUITY",
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    theme: Optional[bool] = None,
) -> pd.DataFrame:
    """
    Retrieve available datasets based on specified parameters.

    Args:
        s (SingleSession): An authenticated session object.
        instrument_type (str, optional): The type of instrument. Defaults to "EQUITY".
        region (str, optional): The region. Defaults to "USA".
        delay (int, optional): The delay. Defaults to 1.
        universe (str, optional): The universe. Defaults to "TOP3000".
        theme (bool | None, optional):
            - True  -> return only datasets that are in a theme
            - False -> return only datasets that are not in a theme
            - None  -> ignore theme filter (all datasets)
          Defaults to None.

    Returns:
        pandas.DataFrame: A DataFrame containing information about available datasets.
    """
    url = (
        brain_api_url
        + "/data-sets?"
        + f"instrumentType={instrument_type}&region={region}&delay={delay}&universe={universe}"
    )
    if theme is not None:
        theme_str = "true" if theme else "false"
        url += f"&theme={theme_str}"
    result = s.get(url)
    _check_rate_limit(result)
    datasets_df = pd.DataFrame(result.json()["results"])
    datasets_df = expand_dict_columns(datasets_df)
    return datasets_df


def get_datafields(
    s: SingleSession,
    instrument_type: str = "EQUITY",
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    search: str = "",
) -> pd.DataFrame:
    """
    Retrieve available datafields based on specified parameters.

    Args:
        s (SingleSession): An authenticated session object.
        instrument_type (str, optional): The type of instrument. Defaults to "EQUITY".
        region (str): The region. Defaults to "USA".
        delay (int): The delay. Defaults to 1.
        universe (str): The universe. Defaults to "TOP3000".
        search (str, optional): A search string to filter datafields. Defaults to "".

    Returns:
        pandas.DataFrame: A DataFrame containing information about available datafields.
    """

    base = (
        brain_api_url
        + "/data-fields?"
        + f"&instrumentType={instrument_type}"
        + f"&region={region}"
        + f"&delay={delay}"
        + f"&universe={universe}"
    )

    if len(search) == 0:
        logger.info(f"Getting fields for: region={region}, delay={delay}, universe={universe}")
        result = s.get(base)
        logger.debug(f"Get datafields, status_code:{result.status_code}")
        _check_rate_limit(result)
        data = result.json()
        if "results" not in data:
            logger.warning(f"No 'results' key for region={region}, universe={universe}, delay={delay}. Response: {data}")
            return pd.DataFrame()
        datafields = data["results"]

    else:
        logger.info(
            f"Getting fields for: region={region}, delay={delay}, universe={universe}, search key word: {search}"
        )
        url_template = base + "&limit=50" + f"&search={search}" + "&offset=0"
        result = s.get(url_template)
        _check_rate_limit(result)
        data = result.json()
        if "results" not in data:
            logger.warning(f"No 'results' key for region={region}, universe={universe}, delay={delay}, search={search}. Response: {data}")
            return pd.DataFrame()
        datafields = data["results"]

    datafields_df = pd.DataFrame(datafields)
    datafields_df = expand_dict_columns(datafields_df)
    return datafields_df


def get_operators(s: SingleSession) -> pd.DataFrame:
    """
    Fetches and processes the list of operators from the WorldQuant Brain API.

    This function retrieves the operators from the provided session `s`,
    explodes the 'scope' column (which contains lists) into separate rows,
    and returns the resulting DataFrame.

    Args:
    s (SingleSession): An authenticated session object.

    Returns:
    pd.DataFrame: A DataFrame containing the operators with each scope entry
    as a separate row.
    """
    df = pd.DataFrame(s.get(brain_api_url + "/operators").json())
    return df.explode('scope').reset_index(drop=True)


def get_instrument_type_region_delay(s: SingleSession) -> pd.DataFrame:
    """
    Retrieves and organizes instrument type, region, and delay data into a DataFrame.

    Parameters:
        s (SingleSession): The session object used for making the API call.

    Returns:
        df (pd.DataFrame): A DataFrame containing the instrument type, region, delay, universe, and neutralization data.

    The function fetches the settings options from the simulations endpoint and extracts the 'Instrument type',
    'Region', 'Universe', 'Delay', and 'Neutralization' data. It then organizes this data into a list of dictionaries,
    each containing the instrument type, region, delay, universe, and neutralization for a particular combination
    of instrument type, region, and delay. This list is then converted into a DataFrame and returned.
    """

    settings_options = s.options(brain_api_url + '/simulations').json()['actions']['POST']['settings']['children']
    data = [
        {settings_options[key]['label']: settings_options[key]['choices']}
        for key in settings_options.keys()
        if settings_options[key]['type'] == 'choice'
    ]

    instrument_type_data = {}
    region_data = {}
    universe_data = {}
    delay_data = {}
    neutralization_data = {}

    for item in data:
        if 'Instrument type' in item:
            instrument_type_data = item['Instrument type']
        elif 'Region' in item:
            region_data = item['Region']['instrumentType']
        elif 'Universe' in item:
            universe_data = item['Universe']['instrumentType']
        elif 'Delay' in item:
            delay_data = item['Delay']['instrumentType']
        elif 'Neutralization' in item:
            neutralization_data = item['Neutralization']['instrumentType']

    data_list = []

    for instrument_type in instrument_type_data:
        for region in region_data[instrument_type['value']]:
            for delay in delay_data[instrument_type['value']]['region'][region['value']]:
                row = {'InstrumentType': instrument_type['value'], 'Region': region['value'], 'Delay': delay['value']}
                row['Universe'] = [
                    item['value'] for item in universe_data[instrument_type['value']]['region'][region['value']]
                ]
                row['Neutralization'] = [
                    item['value'] for item in neutralization_data[instrument_type['value']]['region'][region['value']]
                ]
                data_list.append(row)

    df = (
        pd.DataFrame(data_list)
        .sort_values(
            by=['InstrumentType', 'Region', 'Delay'],
            ascending=False,
        )
        .reset_index(drop=True)
    )
    return df


def performance_comparison(
    s: SingleSession, alpha_id: str, team_id: Optional[str] = None, competition: Optional[str] = None
) -> dict:
    """
    Retrieve performance comparison data for merged performance check.

    Args:
        s (SingleSession): An authenticated session object.
        alpha_id (str): The ID of the alpha.
        team_id (str, optional): The ID of the team for comparison. Defaults to None.
        competition (str, optional): The ID of the competition for comparison. Defaults to None.

    Returns:
        dict: A dictionary containing the performance comparison data.

    Raises:
        requests.exceptions.RequestException: If there's an error in the API request.
    """
    if competition is not None:
        part_url = f"competitions/{competition}"
    elif team_id is not None:
        part_url = f"teams/{team_id}"
    else:
        part_url = "users/self"
    while True:
        result = s.get(brain_api_url + f"/{part_url}/alphas/" + alpha_id + "/before-and-after-performance")
        if "retry-after" in result.headers:
            time.sleep(float(result.headers["Retry-After"]))
        else:
            break
    if result.json().get("stats", 0) == 0:
        logger.warning(f"Cant get performance comparison for alpha_id {alpha_id}. {result.json()}")
        return {}
    if result.status_code != 200:
        logger.warning(f"Cant get performance comparison for alpha_id {alpha_id}. {result.json()}")
        return {}

    return result.json()

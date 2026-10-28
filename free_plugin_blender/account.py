"""Your Claude subscription, through Claude Code's own sign-in (`claude auth`).

The chat never sees a token: Claude Code stores the login, and `claude -p`
uses it. This module only reads the status and runs the login/logout commands
in the background, so the UI can show "Connected: Claude Pro" and a Connect
button instead of asking for an API key.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time

from . import chat

INSTALL_URL = "https://claude.com/claude-code"
INSTALL_COMMAND = "curl -fsSL https://claude.ai/install.sh | bash"
_URL = re.compile(r"https://\S+")


class _Account:
    def __init__(self):
        self.checked = 0.0
        self.checking = False
        self.logged_in = None  # None: unknown yet
        self.email = ""
        self.plan = ""
        self.method = ""
        self.login_running = False
        self.login_process: subprocess.Popen | None = None
        self.login_output: list[str] = []
        self.login_url = ""
        self.message = ""


account = _Account()


def _run(arguments, timeout=30):
    executable = chat.claude_executable()
    if executable is None:
        raise FileNotFoundError("Claude Code is not installed")
    return subprocess.run([executable, *arguments], capture_output=True, text=True, timeout=timeout,
                          env=chat.subprocess_env())


def refresh(force=False):
    """Read `claude auth status` in the background (at most every 30 s unless forced)."""
    if account.checking or (not force and time.time() - account.checked < 30):
        return
    if chat.claude_executable() is None:
        account.logged_in, account.checked = None, time.time()
        return
    account.checking = True

    def work():
        try:
            result = _run(["auth", "status", "--json"])
            data = json.loads(result.stdout or "{}")
            account.logged_in = bool(data.get("loggedIn"))
            account.email = data.get("email") or ""
            account.plan = (data.get("subscriptionType") or "").title()
            account.method = data.get("authMethod") or ""
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            account.logged_in = None
            account.message = f"Could not read the Claude status: {error}"
        finally:
            account.checked, account.checking = time.time(), False
            chat.state.dirty = True

    threading.Thread(target=work, name="free-plugin:auth-status", daemon=True).start()


def label() -> str:
    if chat.claude_executable() is None:
        return "Claude Code not installed"
    if account.logged_in is None:
        return "Claude: checking…"
    if not account.logged_in:
        return "Claude: not connected"
    plan = f"Claude {account.plan}" if account.plan else "Claude"
    return f"{plan} · {account.email}" if account.email else plan


def ready() -> bool:
    return chat.claude_executable() is not None and account.logged_in is not False


def login():
    """Start `claude auth login --claudeai`; it opens the browser and waits for you."""
    if account.login_running:
        return "Sign-in already in progress"
    executable = chat.claude_executable()
    if executable is None:
        return "Install Claude Code first"
    account.login_running, account.login_output, account.login_url = True, [], ""
    account.message = "Finish signing in in your browser…"
    try:
        process = subprocess.Popen(
            [executable, "auth", "login", "--claudeai"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, env=chat.subprocess_env(),
        )
    except OSError as error:
        account.login_running, account.message = False, f"Could not start the sign-in: {error}"
        return account.message
    account.login_process = process

    def follow():
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            account.login_output = (account.login_output + [line])[-6:]
            match = _URL.search(line)
            if match and not account.login_url:
                account.login_url = match.group(0)
            chat.state.dirty = True
        process.wait()
        account.login_running, account.login_process = False, None
        account.message = "Connected." if process.returncode == 0 else "Sign-in did not complete."
        refresh(force=True)

    threading.Thread(target=follow, name="free-plugin:auth-login", daemon=True).start()
    return None


def send_code(code: str):
    """Some sign-in flows ask to paste a code back into the terminal."""
    process = account.login_process
    if process is None or process.stdin is None:
        return "No sign-in waiting for a code"
    process.stdin.write(code.strip() + "\n")
    process.stdin.flush()
    return None


def cancel_login():
    if account.login_process is not None and account.login_process.poll() is None:
        account.login_process.terminate()


def logout():
    try:
        _run(["auth", "logout"])
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    account.logged_in, account.email, account.plan = False, "", ""
    refresh(force=True)
    return None

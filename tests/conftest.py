"""Run the real service as a subprocess, the way an operator starts it."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Service:
    def __init__(self, env: dict[str, str], args: list[str]) -> None:
        self.env = env
        self.args = args
        self.port = int(args[args.index("--port") + 1]) if "--port" in args else int(env["PORT"])
        self.proc: subprocess.Popen | None = None

    def start(self) -> "Service":
        started = time.monotonic()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "app", *self.args],
            cwd=ROOT, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        while time.monotonic() - started < 5:
            if self.proc.poll() is not None:
                raise AssertionError(f"service exited early: {self.proc.stderr.read()}")
            try:
                self.request("GET", "/health")
                return self
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise AssertionError("service did not answer /health within 5 seconds")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

    def restart(self) -> None:
        self.stop()
        self.start()

    def request(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers.get_content_type(), resp.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get_content_type(), error.read().decode()

    def get_json(self, path: str):
        status, _, body = self.request("GET", path)
        return status, json.loads(body)

    def post_json(self, path: str, payload: dict):
        status, _, body = self.request("POST", path, payload)
        return status, json.loads(body)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "standup.db"


@pytest.fixture
def base_env(db_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in {"PORT", "STANDUP_DB", "FACTORY_RUNTIME_CANDIDATE"}}
    env["STANDUP_DB"] = str(db_path)
    return env


@pytest.fixture
def launch(base_env):
    services: list[Service] = []

    def _launch(extra_env: dict[str, str] | None = None, use_env_port: bool = False) -> Service:
        env = {**base_env, **(extra_env or {})}
        port = str(free_port())
        if use_env_port:
            env["PORT"] = port
            args: list[str] = []
        else:
            args = ["--port", port]
        service = Service(env, args)
        services.append(service)
        return service.start()

    yield _launch
    for service in services:
        service.stop()


@pytest.fixture
def service(launch) -> Service:
    return launch()

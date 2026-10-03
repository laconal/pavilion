import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

from pavilion.cli import app

runner = CliRunner()


USERS = """
from dataclasses import dataclass

from auth import AuthError, hash_password


@dataclass
class User:
    id: int
    hashed_password: str


class Users:
    def __init__(self):
        self.users = {"alice": User(1, hash_password("s3cret"))}

    def get_by_username(self, username):
        return self.users.get(username)


def fails(fn, *args):
    try:
        fn(*args)
    except AuthError:
        return True
    return False
"""

JWT_FLOW = USERS + """
import sys

import jwt

from auth import AuthService, InMemoryRevokedTokenStore

auth = AuthService(Users(), InMemoryRevokedTokenStore())
assert fails(auth.login, "alice", "wrong")
assert fails(auth.login, "bob", "s3cret")

pair = auth.login("alice", "s3cret")
assert jwt.get_unverified_header(pair.access_token)["alg"] == sys.argv[1]
assert auth.authenticate(pair.access_token) == "1"
assert fails(auth.authenticate, pair.refresh_token)  # wrong token type
assert fails(auth.authenticate, pair.access_token[:-4] + "AAAA")  # bad signature

new = auth.refresh(pair.refresh_token)
assert fails(auth.refresh, pair.refresh_token)  # rotated
auth.logout(new.refresh_token)
assert fails(auth.refresh, new.refresh_token)  # revoked
auth.logout("garbage")  # no-op
print("ok")
"""

def run_generated(tmp_path, script, *args):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("hashing", ["argon2", "bcrypt"])
@pytest.mark.parametrize("algorithm", ["RS256", "ES256", "EdDSA"])
def test_jwt_asymmetric(tmp_path, algorithm, hashing):
    args = ["--transport", "header", "--strategy", "asymmetric", "--algorithm", algorithm]
    result = runner.invoke(app, ["add", "auth", *args, "--hashing", hashing])

    assert result.exit_code == 0, result.output
    assert {p.name for p in (tmp_path / "auth").iterdir()} == {
        "__init__.py", "passwords.py", "tokens.py", "service.py"
    }
    assert (tmp_path / "secrets" / "private.pem").exists()
    run_generated(tmp_path, JWT_FLOW, algorithm)


@pytest.mark.parametrize("hashing", ["argon2", "bcrypt"])
def test_jwt_symmetric(tmp_path, hashing):
    args = ["--transport", "header", "--strategy", "symmetric", "--hashing", hashing]
    result = runner.invoke(app, ["add", "auth", *args])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "secrets" / "jwt_secret").exists()
    assert not (tmp_path / "secrets" / "private.pem").exists()
    run_generated(tmp_path, JWT_FLOW, "HS256")


def test_defaults_without_a_terminal(tmp_path):
    result = runner.invoke(app, ["add", "auth"])

    assert result.exit_code == 0, result.output
    assert "JWT EdDSA via header (asymmetric), access 3h / refresh 24h, Argon2" in result.output
    assert "uv add 'pyjwt[crypto]' argon2-cffi" in result.output


def test_reuses_matching_keys(tmp_path):
    runner.invoke(app, ["add", "keys", "ES256"])
    private = (tmp_path / "secrets" / "private.pem").read_bytes()

    result = runner.invoke(app, ["add", "auth", "--algorithm", "ES256"])

    assert result.exit_code == 0, result.output
    assert "Using existing ES256 key pair" in result.output
    assert (tmp_path / "secrets" / "private.pem").read_bytes() == private


def test_mismatched_keys_fail_before_writing_anything(tmp_path):
    runner.invoke(app, ["add", "keys", "RS256"])

    result = runner.invoke(app, ["add", "auth", "--algorithm", "EdDSA"])

    assert result.exit_code == 1
    assert "is RS256, but EdDSA was selected" in result.output
    assert not (tmp_path / "auth").exists()


def test_refuses_to_overwrite_without_force(tmp_path):
    runner.invoke(app, ["add", "auth"])
    service = tmp_path / "auth" / "service.py"
    service.write_text("# edited\n")

    result = runner.invoke(app, ["add", "auth"])
    assert result.exit_code == 1
    assert service.read_text() == "# edited\n"

    result = runner.invoke(app, ["add", "auth", "--force"])
    assert result.exit_code == 0
    assert "class AuthService" in service.read_text()




SEPARATE_KEYS_CHECK = USERS + """
import sys
from pathlib import Path

import jwt

from auth import AuthService, InMemoryRevokedTokenStore

algorithm = sys.argv[1]
access, refresh = (
    ("jwt_secret", "jwt_secret_refresh") if algorithm == "HS256"
    else ("public.pem", "public_refresh.pem")
)
access_key = Path("secrets", access).read_bytes().strip()
refresh_key = Path("secrets", refresh).read_bytes().strip()

pair = AuthService(Users(), InMemoryRevokedTokenStore()).login("alice", "s3cret")
jwt.decode(pair.access_token, access_key, algorithms=[algorithm])
jwt.decode(pair.refresh_token, refresh_key, algorithms=[algorithm])
for token, wrong_key in [(pair.access_token, refresh_key), (pair.refresh_token, access_key)]:
    try:
        jwt.decode(token, wrong_key, algorithms=[algorithm])
    except jwt.InvalidSignatureError:
        continue
    raise SystemExit("token verified with the other token type's key")
print("ok")
"""


@pytest.mark.parametrize(
    ("args", "algorithm", "access_file", "refresh_file"),
    [
        (["--algorithm", "EdDSA"], "EdDSA", "private.pem", "private_refresh.pem"),
        (["--algorithm", "RS256", "--rsa-bits", "3072"], "RS256", "private.pem", "private_refresh.pem"),
        (["--strategy", "symmetric"], "HS256", "jwt_secret", "jwt_secret_refresh"),
    ],
)
def test_separate_refresh_keys(tmp_path, args, algorithm, access_file, refresh_file):
    result = runner.invoke(app, ["add", "auth", *args, "--refresh-keys", "separate"])

    assert result.exit_code == 0, result.output
    assert "separate refresh keys" in result.output
    assert f"secrets/{refresh_file}" in result.output
    assert not (tmp_path / "secrets" / "refresh").exists()
    access = (tmp_path / "secrets" / access_file).read_bytes()
    refresh = (tmp_path / "secrets" / refresh_file).read_bytes()
    assert access != refresh
    run_generated(tmp_path, JWT_FLOW, algorithm)
    run_generated(tmp_path, SEPARATE_KEYS_CHECK, algorithm)


def test_mismatched_refresh_keys_fail_before_writing_anything(tmp_path):
    runner.invoke(app, ["add", "keys", "RS256", "--refresh"])

    result = runner.invoke(
        app, ["add", "auth", "--algorithm", "EdDSA", "--refresh-keys", "separate"]
    )

    assert result.exit_code == 1
    assert "pavilion add keys EdDSA --refresh --force" in result.output
    assert not (tmp_path / "secrets" / "private.pem").exists()
    assert not (tmp_path / "auth").exists()



COOKIE_CHECK = USERS + """
from auth import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    AuthService,
    InMemoryRevokedTokenStore,
    cleared_cookies,
    token_cookies,
)

auth = AuthService(Users(), InMemoryRevokedTokenStore())
pair = auth.login("alice", "s3cret")
access, refresh = (cookie.kwargs for cookie in token_cookies(pair))

assert access == {
    "key": ACCESS_COOKIE, "value": pair.access_token, "max_age": 3 * 3600,
    "path": "/", "httponly": True, "secure": True, "samesite": "lax",
}
assert refresh == {
    "key": REFRESH_COOKIE, "value": pair.refresh_token, "max_age": 24 * 3600,
    "path": "/auth", "httponly": True, "secure": True, "samesite": "strict",
}
# What a request would carry back:
assert auth.authenticate(access["value"]) == "1"
auth.logout(refresh["value"])
assert fails(auth.refresh, refresh["value"])

for cookie in cleared_cookies():
    assert cookie.value == "" and cookie.max_age == 0
assert [c.path for c in cleared_cookies()] == ["/", "/auth"]  # same paths, or browsers keep them
print("ok")
"""


@pytest.mark.parametrize("args", [["--algorithm", "EdDSA"], ["--strategy", "symmetric"]])
def test_cookie_transport(tmp_path, args):
    result = runner.invoke(app, ["add", "auth", "--transport", "cookie", *args])

    assert result.exit_code == 0, result.output
    assert "via cookies" in result.output
    assert (tmp_path / "auth" / "cookies.py").exists()
    assert 'token_type' not in (tmp_path / "auth" / "service.py").read_text()
    run_generated(tmp_path, JWT_FLOW, "HS256" if "symmetric" in args else "EdDSA")
    run_generated(tmp_path, COOKIE_CHECK)


def test_header_transport_has_no_cookies_module(tmp_path):
    runner.invoke(app, ["add", "auth", "--transport", "header"])

    assert not (tmp_path / "auth" / "cookies.py").exists()
    assert 'token_type: str = "bearer"' in (tmp_path / "auth" / "service.py").read_text()


def test_force_removes_files_the_new_transport_does_not_use(tmp_path):
    runner.invoke(app, ["add", "auth", "--transport", "cookie"])

    result = runner.invoke(app, ["add", "auth", "--transport", "header"])
    assert result.exit_code == 1
    assert (tmp_path / "auth" / "cookies.py").exists()

    result = runner.invoke(app, ["add", "auth", "--transport", "header", "--force"])
    assert result.exit_code == 0, result.output
    assert "auth/cookies.py (removed" in result.output
    assert not (tmp_path / "auth" / "cookies.py").exists()
    run_generated(tmp_path, JWT_FLOW, "EdDSA")


TTL_CHECK = USERS + """
import sys

import jwt

from auth import AuthService, InMemoryRevokedTokenStore

pair = AuthService(Users(), InMemoryRevokedTokenStore()).login("alice", "s3cret")
for token, expected in [(pair.access_token, sys.argv[1]), (pair.refresh_token, sys.argv[2])]:
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == int(expected), (claims, expected)
print("ok")
"""


def test_custom_ttls(tmp_path):
    result = runner.invoke(app, ["add", "auth", "--access-ttl", "30m", "--refresh-ttl", "14d"])

    assert result.exit_code == 0, result.output
    assert "access 30m / refresh 14d" in result.output
    tokens = (tmp_path / "auth" / "tokens.py").read_text()
    assert "ACCESS_TOKEN_TTL = timedelta(minutes=30)" in tokens
    assert "REFRESH_TOKEN_TTL = timedelta(days=14)" in tokens
    run_generated(tmp_path, TTL_CHECK, str(30 * 60), str(14 * 86400))


def test_default_ttls_keep_hours(tmp_path):
    runner.invoke(app, ["add", "auth"])

    tokens = (tmp_path / "auth" / "tokens.py").read_text()
    assert "ACCESS_TOKEN_TTL = timedelta(hours=3)" in tokens
    assert "REFRESH_TOKEN_TTL = timedelta(hours=24)" in tokens
    run_generated(tmp_path, TTL_CHECK, str(3 * 3600), str(24 * 3600))


def test_bare_number_means_hours(tmp_path):
    result = runner.invoke(app, ["add", "auth", "--access-ttl", "1", "--refresh-ttl", "48"])

    assert result.exit_code == 0, result.output
    assert "ACCESS_TOKEN_TTL = timedelta(hours=1)" in (tmp_path / "auth" / "tokens.py").read_text()


@pytest.mark.parametrize("value", ["soon", "0h", "3w", "-1h"])
def test_rejects_invalid_ttl(value):
    result = runner.invoke(app, ["add", "auth", "--access-ttl", value])

    assert result.exit_code == 2
    assert "Invalid value for '--access-ttl'" in result.output


def test_refresh_ttl_must_outlive_access_ttl(tmp_path):
    # 48h access against the 24h refresh default
    result = runner.invoke(app, ["add", "auth", "--access-ttl", "48h"])

    assert result.exit_code == 2
    assert "Refresh token TTL (24h) must" in result.output
    assert not (tmp_path / "auth").exists()

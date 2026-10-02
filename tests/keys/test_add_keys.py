import stat

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from typer.testing import CliRunner

from pavilion.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    ("algorithm", "key_type"),
    [
        ("RS256", rsa.RSAPrivateKey),
        ("es256", ec.EllipticCurvePrivateKey),
        ("eddsa", ed25519.Ed25519PrivateKey),
    ],
)
def test_generates_key_pair(tmp_path, algorithm, key_type):
    result = runner.invoke(app, ["add", "keys", algorithm])

    assert result.exit_code == 0, result.output
    secrets = tmp_path / "secrets"
    private = load_pem_private_key((secrets / "private.pem").read_bytes(), password=None)
    public = load_pem_public_key((secrets / "public.pem").read_bytes())
    assert isinstance(private, key_type)
    assert private.public_key() == public


def test_private_key_is_private_and_ignored_by_git(tmp_path):
    runner.invoke(app, ["add", "keys", "ES256"])

    secrets = tmp_path / "secrets"
    assert stat.S_IMODE((secrets / "private.pem").stat().st_mode) == 0o600
    assert (secrets / ".gitignore").read_text() == "*\n!.gitignore\n"


def test_refuses_to_overwrite_without_force(tmp_path):
    runner.invoke(app, ["add", "keys", "ES256"])
    private = tmp_path / "secrets" / "private.pem"
    original = private.read_bytes()

    result = runner.invoke(app, ["add", "keys", "ES256"])
    assert result.exit_code == 1
    assert private.read_bytes() == original

    result = runner.invoke(app, ["add", "keys", "ES256", "--force"])
    assert result.exit_code == 0
    assert private.read_bytes() != original


def test_custom_directory(tmp_path):
    result = runner.invoke(app, ["add", "keys", "EdDSA", "--dir", "config/jwt"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "config" / "jwt" / "private.pem").exists()


def test_rejects_unknown_algorithm():
    result = runner.invoke(app, ["add", "keys", "HS256"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output


@pytest.mark.parametrize(("args", "bits"), [([], 2048), (["--rsa-bits", "3072"], 3072)])
def test_rsa_key_size(tmp_path, args, bits):
    result = runner.invoke(app, ["add", "keys", "RS256", *args])

    assert result.exit_code == 0, result.output
    assert f"RS256 ({bits}-bit)" in result.output
    private = load_pem_private_key((tmp_path / "secrets" / "private.pem").read_bytes(), None)
    assert private.key_size == bits


@pytest.mark.parametrize("bits", ["1024", "32768"])
def test_rejects_out_of_range_rsa_key_size(bits):
    result = runner.invoke(app, ["add", "keys", "RS256", "--rsa-bits", bits])

    assert result.exit_code == 2
    assert "Invalid value for '--rsa-bits'" in result.output


def test_rejects_rsa_key_size_for_other_algorithms(tmp_path):
    result = runner.invoke(app, ["add", "keys", "ES256", "--rsa-bits", "4096"])

    assert result.exit_code == 2
    assert "only applies to RS256" in result.output
    assert not (tmp_path / "secrets").exists()


def test_refresh_pair_sits_next_to_access_pair(tmp_path):
    runner.invoke(app, ["add", "keys", "ES256"])
    result = runner.invoke(app, ["add", "keys", "EdDSA", "--refresh"])

    assert result.exit_code == 0, result.output
    secrets = tmp_path / "secrets"
    assert {p.name for p in secrets.iterdir()} == {
        ".gitignore", "private.pem", "public.pem", "private_refresh.pem", "public_refresh.pem"
    }
    refresh = load_pem_private_key((secrets / "private_refresh.pem").read_bytes(), None)
    assert isinstance(refresh, ed25519.Ed25519PrivateKey)
    assert stat.S_IMODE((secrets / "private_refresh.pem").stat().st_mode) == 0o600

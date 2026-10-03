import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

from pavilion.cli import app
from pavilion.utils.scaffold import UTILS

runner = CliRunner()


def run_generated(tmp_path, script):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok", result.stdout


def add(*names, extra=()):
    for name in names:
        result = runner.invoke(app, ["add", "util", name, *extra])
        assert result.exit_code == 0, result.output
    return result


# --- the generated functions --------------------------------------------------------

PASSWORD_CHECK = """
import string
from unittest import mock

from utils import generate_password
from utils import passwords

alphabet = set(string.ascii_letters + string.digits + "!@#$%^&*-_=+?")

assert len(generate_password()) == 12
assert len(generate_password(32)) == 32
assert generate_password(0) == ""
samples = [generate_password(64) for _ in range(20)]
assert all(set(s) <= alphabet for s in samples)
assert len(set(samples)) == 20  # random, not repeated
assert len(set("".join(samples))) > 50  # draws from the whole alphabet

# The module stays reachable (not shadowed by the re-exported function), and the
# randomness comes from `secrets`:
with mock.patch("utils.passwords.secrets.choice", return_value="x"):
    assert passwords.generate_password(3) == "xxx"
print("ok")
"""


def test_generate_password(tmp_path):
    add("generate_password")

    assert {p.name for p in (tmp_path / "utils").iterdir()} == {"__init__.py", "passwords.py"}
    run_generated(tmp_path, PASSWORD_CHECK)


def test_tokens(tmp_path):
    add("generate_token", "generate_code", "hash_token")
    run_generated(tmp_path, """
    import re
    from unittest import mock

    from utils import generate_code, generate_token, hash_token

    token = generate_token()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)  # 32 bytes, URL-safe base64
    assert len(generate_token(16)) == 22
    assert len({generate_token() for _ in range(50)}) == 50

    assert re.fullmatch(r"[0-9]{6}", generate_code())
    assert re.fullmatch(r"[0-9]{4}", generate_code(4))
    with mock.patch("utils.tokens.secrets.randbelow", return_value=42):
        assert generate_code() == "000042"  # leading zeros kept

    assert hash_token("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert hash_token(token) == hash_token(token) != hash_token(token + "x")
    print("ok")
    """)


def test_masking(tmp_path):
    add("mask_email", "mask_secret")
    run_generated(tmp_path, """
    from utils import mask_email, mask_secret

    assert mask_email("maxpower@gmail.com") == "m***r@gmail.com"
    assert mask_email("ab@x.io") == "a***@x.io"
    assert mask_email("a@x.io") == "a***@x.io"
    assert mask_email("@x.io") == "***@x.io"
    assert mask_email("first.last+tag@sub.example.com") == "f***g@sub.example.com"
    assert mask_email("not-an-email") == "***"

    assert mask_secret("sk_live_51HxAbCdEf3a9") == "****f3a9"
    assert mask_secret("sk_live_51HxAbCdEf3a9", visible=6) == "****dEf3a9"
    assert mask_secret("short") == "****"  # shorter than 2 * visible: nothing shown
    assert mask_secret("") == "****"
    print("ok")
    """)


def test_retry(tmp_path):
    add("retry")
    run_generated(tmp_path, """
    import asyncio
    import logging
    from unittest import mock

    from utils import retry

    logging.basicConfig(level=logging.WARNING)

    # sync: succeeds on the third try, waits 0.5 then 1.0 (jitter off)
    calls = []

    @retry(attempts=3, jitter=False)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("down")
        return "up"

    with mock.patch("utils.retry.time.sleep") as sleep:
        assert flaky() == "up"
    assert len(calls) == 3
    assert [c.args[0] for c in sleep.call_args_list] == [0.5, 1.0]
    assert flaky.__name__ == "flaky"  # functools.wraps

    # gives up after `attempts` and re-raises the last error
    @retry(attempts=4, delay=1, backoff=10, max_delay=5, jitter=False)
    def always_down():
        raise TimeoutError("still down")

    with mock.patch("utils.retry.time.sleep") as sleep:
        try:
            always_down()
        except TimeoutError:
            pass
        else:
            raise SystemExit("no error")
    assert [c.args[0] for c in sleep.call_args_list] == [1, 5, 5]  # capped at max_delay

    # other exceptions aren't retried
    tries = []

    @retry(exceptions=ConnectionError)
    def bug():
        tries.append(1)
        raise ValueError("bug")

    try:
        bug()
    except ValueError:
        pass
    assert len(tries) == 1

    # jitter: a random part of the exponential delay
    @retry(attempts=2, delay=2)
    def once_flaky(state=[]):
        state.append(1)
        if len(state) == 1:
            raise ConnectionError
        return True

    with mock.patch("utils.retry.time.sleep") as sleep:
        once_flaky()
    assert 0 <= sleep.call_args.args[0] <= 2

    # async
    attempts = []

    @retry(attempts=3, jitter=False)
    async def flaky_async():
        attempts.append(1)
        if len(attempts) < 2:
            raise ConnectionError
        return 42

    with mock.patch("utils.retry.asyncio.sleep") as sleep:
        assert asyncio.run(flaky_async()) == 42
    assert sleep.await_args_list[0].args == (0.5,)

    try:
        retry(attempts=0)
    except ValueError:
        print("ok")
    """)


def test_retry_logs_each_retry(tmp_path):
    add("retry")
    script = """
    import logging
    from unittest import mock

    from utils import retry

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    state = []

    @retry(attempts=2, jitter=False)
    def flaky():
        state.append(1)
        if len(state) == 1:
            raise ConnectionError("down")

    with mock.patch("utils.retry.time.sleep"):
        flaky()
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "WARNING flaky failed (ConnectionError('down')), retry 1/1 in 0.50s" in result.stderr


def test_timing(tmp_path):
    add("timed")  # brings timer along
    run_generated(tmp_path, """
    import asyncio
    import logging
    import time

    from utils import timed, timer

    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logging.getLogger("utils.timing").addHandler(handler)
    logging.getLogger("utils.timing").setLevel(logging.INFO)

    with timer("sleep") as t:
        time.sleep(0.05)
    assert 0.04 < t.seconds < 1
    assert records[-1].getMessage().startswith("sleep took ")

    with timer("quiet", log=False):
        pass
    assert len(records) == 1

    @timed
    def compute(x):
        return x * 2

    @timed
    async def fetch():
        await asyncio.sleep(0.01)
        return "done"

    assert compute(21) == 42
    assert asyncio.run(fetch()) == "done"
    assert records[-2].getMessage().startswith("compute took ")
    assert records[-1].getMessage().startswith("fetch took ")
    assert compute.__name__ == "compute"

    try:
        with timer("boom") as t:
            raise RuntimeError
    except RuntimeError:
        pass
    assert records[-1].getMessage().startswith("boom took ")  # logged even on errors
    print("ok")
    """)


def test_slugify(tmp_path):
    add("slugify")
    run_generated(tmp_path, """
    from utils import slugify

    assert slugify("Hello, World! Ça va?") == "hello-world-ca-va"
    assert slugify("  Crème brûlée -- 2024  ") == "creme-brulee-2024"
    assert slugify("snake case please", "_") == "snake_case_please"
    assert slugify("Привет мир") == ""
    assert slugify("Привет мир", allow_unicode=True) == "привет-мир"
    assert slugify("O'zbekiston_Respublikasi", allow_unicode=True) == "o-zbekiston-respublikasi"
    assert slugify("") == ""
    print("ok")
    """)


def test_utcnow(tmp_path):
    add("utcnow")
    run_generated(tmp_path, """
    from datetime import UTC, datetime, timedelta

    from utils import utcnow

    now = utcnow()
    assert now.tzinfo is UTC
    assert abs(datetime.now(UTC) - now) < timedelta(seconds=5)
    print("ok")
    """)


# --- the command ---------------------------------------------------------------------


def test_utils_share_topic_modules(tmp_path):
    add("generate_token")
    result = add("generate_code")
    assert "Added generate_code() to utils/tokens.py" in result.output
    add("hash_token")

    tokens = (tmp_path / "utils" / "tokens.py").read_text()
    assert tokens.startswith(
        '"""Random tokens and codes, and hashing tokens for storage."""\n\n'
        "import hashlib\nimport secrets\n\n\n"
    )
    assert tokens.count('"""Random tokens') == 1
    assert [line for line in tokens.splitlines() if line.startswith("def ")] == [
        "def generate_token(nbytes: int = 32) -> str:",
        "def generate_code(digits: int = 6) -> str:",
        "def hash_token(token: str) -> str:",
    ]
    assert {p.name for p in (tmp_path / "utils").iterdir()} == {"__init__.py", "tokens.py"}


def test_init_reexports_everything_sorted(tmp_path):
    add("hash_token", "slugify", "generate_token", "timed")

    assert (tmp_path / "utils" / "__init__.py").read_text() == (
        '"""Utilities. Generated by `pavilion add util`, which adds new utilities here."""\n'
        "\n"
        "from .text import slugify as slugify\n"
        "from .timing import timed as timed\n"
        "from .timing import timer as timer\n"
        "from .tokens import generate_token as generate_token\n"
        "from .tokens import hash_token as hash_token\n"
    )


def test_timed_brings_timer(tmp_path):
    result = add("timed")

    assert "Generated utils/timing.py with timer(), timed()" in result.output
    timing = (tmp_path / "utils" / "timing.py").read_text()
    assert timing.count("logger = logging.getLogger(__name__)") == 1


def test_timed_reuses_an_existing_timer(tmp_path):
    add("timer")
    timing = tmp_path / "utils" / "timing.py"
    timing.write_text(timing.read_text().replace('"block"', '"my block"'))

    result = add("timed")

    assert "Added timed() to utils/timing.py" in result.output
    assert '"my block"' in timing.read_text()  # timer left as it was


def test_refuses_to_overwrite_without_force(tmp_path):
    add("generate_token", "hash_token")
    tokens = tmp_path / "utils" / "tokens.py"
    edited = tokens.read_text().replace("nbytes: int = 32", "nbytes: int = 64") + "\n# mine\n"
    tokens.write_text(edited)

    result = runner.invoke(app, ["add", "util", "hash_token"])
    assert result.exit_code == 1
    assert "hash_token is already in utils/tokens.py" in result.output
    assert tokens.read_text() == edited

    add("generate_token", extra=["--force"])
    text = tokens.read_text()
    assert "nbytes: int = 32" in text  # replaced with the template
    assert "def hash_token" in text and "# mine" in text  # everything else kept


def test_appends_to_a_user_written_module(tmp_path):
    (tmp_path / "utils").mkdir()
    (tmp_path / "utils" / "text.py").write_text(
        '"""My text helpers."""\n\nimport re\n\n\ndef shout(text: str) -> str:\n'
        '    return re.sub(r"\\s+", " ", text).upper()\n'
    )

    add("slugify")

    text = (tmp_path / "utils" / "text.py").read_text()
    assert text.startswith('"""My text helpers."""\n\nimport re\nimport unicodedata\n\n\n')
    assert "def shout" in text and "def slugify" in text
    run_generated(tmp_path, "from utils.text import shout, slugify\n"
                            "assert shout('a  b') == 'A B' and slugify('A B') == 'a-b'\n"
                            "print('ok')\n")


def test_list_utils():
    result = runner.invoke(app, ["add", "util", "list"])

    assert result.exit_code == 0, result.output
    names = [line.split()[0] for line in result.output.splitlines()[1:] if line.strip()]
    assert [n for n in names if n in UTILS] == list(UTILS)


def test_custom_directory(tmp_path):
    add("generate_password", extra=["-d", "app/utils"])

    assert (tmp_path / "app" / "utils" / "passwords.py").exists()


def test_existing_init_gets_an_export_line(tmp_path):
    (tmp_path / "utils").mkdir()
    (tmp_path / "utils" / "__init__.py").write_text("from .text import slugify as slugify\n")

    add("generate_password")

    assert (tmp_path / "utils" / "__init__.py").read_text() == (
        "from .passwords import generate_password as generate_password\n"
        "from .text import slugify as slugify\n"
    )


def test_unknown_util():
    result = runner.invoke(app, ["add", "util", "uuid7"])

    assert result.exit_code == 2
    assert "No such command 'uuid7'" in result.output


@pytest.mark.parametrize("name", list(UTILS))
def test_every_util_compiles_alone(tmp_path, name):
    add(name)
    run_generated(tmp_path, f"from utils import {name}\nprint('ok')\n")

import os
import subprocess
import sys
import textwrap

import pytest
from typer.testing import CliRunner

from pavilion.cli import app

runner = CliRunner()


def run_generated(tmp_path, script, database_url=None):
    """Run `script` against the generated package; it reads DATABASE_URL if given."""
    env = {**os.environ, "DATABASE_URL": database_url} if database_url else None
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


USER_MODEL_CHECK = """
import os

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Base, User
from models.user import normalize_login

engine = create_engine(os.environ["DATABASE_URL"])
Base.metadata.create_all(engine)

columns = {c["name"]: c for c in inspect(engine).get_columns("users")}
assert User.__tablename__ == "users"
assert set(columns) == {
    "id", "firstname", "lastname", "middlename", "login", "hashed_password", "active"
}
for name in ["firstname", "lastname", "middlename", "login", "hashed_password"]:
    assert columns[name]["type"].length == 255, name
assert columns["middlename"]["nullable"] is True
for name in ["firstname", "lastname", "login", "hashed_password", "active"]:
    assert columns[name]["nullable"] is False, name

with Session(engine) as session:
    user = User(firstname="Max", lastname="Power", login="MaxPower", hashed_password="h")
    session.add(user)
    session.commit()
    assert user.login == "maxpower"
    assert user.active is True
    assert user.middlename is None

    user.login = "MAX.Power"  # assignment is lowercased too
    session.commit()
    found = session.scalars(select(User).where(User.login == normalize_login("Max.POWER")))
    assert found.one() is user

    # server_default: rows inserted outside the ORM are active too
    session.execute(text(
        "INSERT INTO users (firstname, lastname, login, hashed_password) "
        "VALUES ('A', 'B', 'raw', 'h')"
    ))
    assert session.scalar(select(User.active).where(User.login == "raw")) is True

    session.add(User(firstname="X", lastname="Y", login="RAW", hashed_password="h"))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    else:
        raise SystemExit("duplicate login (after lowercasing) was accepted")
print("ok")
"""


def test_generates_user_model(tmp_path, database_url):
    result = runner.invoke(app, ["add", "model", "User", "--no-install"])

    assert result.exit_code == 0, result.output
    assert {p.name for p in (tmp_path / "models").iterdir()} == {
        "__init__.py", "base.py", "user.py"
    }
    run_generated(tmp_path, USER_MODEL_CHECK, database_url)


def test_model_name_is_case_insensitive(tmp_path):
    result = runner.invoke(app, ["add", "model", "user", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "models" / "user.py").exists()


def test_rejects_unknown_model():
    result = runner.invoke(app, ["add", "model", "Post", "--no-install"])

    assert result.exit_code == 2
    assert "No such command 'Post'" in result.output


def test_list_models():
    result = runner.invoke(app, ["add", "model", "list"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split() == ["Model", "File", "Description"]
    assert any(line.split()[:2] == ["User", "user.py"] for line in lines)
    assert any(line.split()[:2] == ["BaseFields", "base_fields.py"] for line in lines)


def test_without_a_model_name_shows_help_when_not_interactive(tmp_path):
    result = runner.invoke(app, ["add", "model"])

    assert result.exit_code == 0, result.output
    assert "list" in result.output and "BaseFields" in result.output
    assert not (tmp_path / "models").exists()


def test_options_work_with_any_name_case(tmp_path):
    result = runner.invoke(app, ["add", "model", "BASEFIELDS", "-d", "db/models", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "db" / "models" / "base_fields.py").exists()


def test_refuses_to_overwrite_without_force(tmp_path):
    runner.invoke(app, ["add", "model", "User", "--no-install"])
    user, base = tmp_path / "models" / "user.py", tmp_path / "models" / "base.py"
    user.write_text("# edited\n")
    base.write_text(base.read_text() + "# my base edit\n")

    result = runner.invoke(app, ["add", "model", "User", "--no-install"])
    assert result.exit_code == 1
    assert user.read_text() == "# edited\n"

    result = runner.invoke(app, ["add", "model", "User", "--no-install", "--force"])
    assert result.exit_code == 0, result.output
    assert "class User(Base)" in user.read_text()
    assert "# my base edit" in base.read_text()  # shared files are never overwritten
    assert "base.py (kept existing)" in result.output


def test_existing_init_gets_an_export_line(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "__init__.py").write_text('"""My models."""')

    result = runner.invoke(app, ["add", "model", "User", "--no-install"])

    assert result.exit_code == 0, result.output
    assert "added `from .user import User as User`" in result.output
    assert (tmp_path / "models" / "__init__.py").read_text() == (
        '"""My models."""\n\nfrom .user import User as User\n'
    )


def test_works_with_generated_auth(tmp_path, database_url):
    runner.invoke(app, ["add", "model", "User", "--no-install"])
    runner.invoke(app, ["add", "auth"])
    script = """
    import os

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from auth import AuthError, AuthService, InMemoryRevokedTokenStore, hash_password
    from models import Base, User
    from models.user import normalize_login

    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(User(
        firstname="Max", lastname="Power", login="Max", hashed_password=hash_password("pw")
    ))
    session.commit()


    class Users:
        def get_by_username(self, username):
            query = select(User).where(User.login == normalize_login(username))
            return session.scalars(query).one_or_none()


    auth = AuthService(Users(), InMemoryRevokedTokenStore())
    pair = auth.login("MAX", "pw")
    assert auth.authenticate(pair.access_token) == "1"
    try:
        auth.login("max", "wrong")
    except AuthError:
        print("ok")
    """
    run_generated(tmp_path, script, database_url)


def test_installs_sqlalchemy_when_missing(tmp_path, uv_calls):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')

    result = runner.invoke(app, ["add", "model", "User"])

    assert result.exit_code == 0, result.output
    assert uv_calls == [(["/usr/bin/uv", "add", "sqlalchemy"], tmp_path)]
    assert "Added sqlalchemy" in result.output


def test_finds_pyproject_in_parent_directory(tmp_path, uv_calls, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path / "src")

    runner.invoke(app, ["add", "model", "User"])

    assert uv_calls == [(["/usr/bin/uv", "add", "sqlalchemy"], tmp_path)]


@pytest.mark.parametrize("requirement", ["sqlalchemy", "SQLAlchemy[asyncio]>=2.0", "sqlalchemy ==2.1"])
def test_skips_install_when_already_declared(tmp_path, uv_calls, requirement):
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "app"\ndependencies = ["{requirement}"]\n'
    )

    result = runner.invoke(app, ["add", "model", "User"])

    assert result.exit_code == 0, result.output
    assert uv_calls == []
    assert "already a project dependency" in result.output


def test_no_pyproject_prints_instructions(uv_calls):
    result = runner.invoke(app, ["add", "model", "User"])

    assert result.exit_code == 0, result.output
    assert uv_calls == []
    assert "uv add sqlalchemy" in result.output


def test_failed_install_exits_with_error_but_keeps_files(tmp_path, uv_calls):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')
    uv_calls.returncode = 1

    result = runner.invoke(app, ["add", "model", "User"])

    assert result.exit_code == 1
    assert "`uv add sqlalchemy` failed" in result.output
    assert (tmp_path / "models" / "user.py").exists()


def test_no_install_skips_dependency_check(tmp_path, uv_calls):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\ndependencies = []\n')

    runner.invoke(app, ["add", "model", "User", "--no-install"])

    assert uv_calls == []


BASE_FIELDS_CHECK = """
import os
from datetime import UTC, datetime

from sqlalchemy import BigInteger, String, create_engine, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column

from models import Base, BaseFields


class Post(BaseFields):
    __tablename__ = "posts"
    title: Mapped[str] = mapped_column(String(255))


assert set(Base.metadata.tables) == {"posts"}  # BaseFields is abstract: no table

engine = create_engine(os.environ["DATABASE_URL"])
Base.metadata.create_all(engine)
columns = {c["name"]: c for c in inspect(engine).get_columns("posts")}
assert isinstance(columns["id"]["type"], BigInteger)
assert columns["id"]["autoincrement"] is True
assert "nextval" in columns["id"]["default"]  # BIGSERIAL
for name in ["created_at", "updated_at"]:
    assert columns[name]["type"].timezone is True, name  # timestamptz
    assert columns[name]["default"] == "now()", name
    assert columns[name]["nullable"] is False, name

with Session(engine) as session:
    first, second = Post(title="a"), Post(title="b")
    session.add_all([first, second])
    session.flush()
    assert (first.id, second.id) == (1, 2)
    # eager_defaults: timestamps come back with the INSERT, not on next access
    assert {"created_at", "updated_at"} <= first.__dict__.keys()
    created = first.created_at
    assert created.tzinfo is not None

    for attempt in [
        lambda: setattr(first, "created_at", datetime(2000, 1, 1, tzinfo=UTC)),
        lambda: Post(title="c", created_at=datetime(2000, 1, 1, tzinfo=UTC)),
    ]:
        try:
            attempt()
        except AttributeError:
            continue
        raise SystemExit("created_at was editable")
    session.commit()

    old = datetime(2000, 1, 1, tzinfo=UTC)
    first.updated_at = old  # editable: an explicit value wins over onupdate
    session.commit()
    assert first.updated_at == old

    # Postgres' now() is the transaction's start time, so this needs a new transaction.
    first.title = "changed"
    session.commit()
    assert first.updated_at > created, (first.updated_at, created)
    assert first.created_at == created
print("ok")
"""


def test_generates_base_fields(tmp_path, database_url):
    result = runner.invoke(app, ["add", "model", "BaseFields", "--no-install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "models" / "base_fields.py").exists()
    run_generated(tmp_path, BASE_FIELDS_CHECK, database_url)


def test_second_model_is_appended_to_init(tmp_path):
    runner.invoke(app, ["add", "model", "User", "--no-install"])
    result = runner.invoke(app, ["add", "model", "basefields", "--no-install"])

    assert result.exit_code == 0, result.output
    init = (tmp_path / "models" / "__init__.py").read_text()
    assert init.endswith(  # inserted in sorted order, as isort/ruff would
        "from .base import Base as Base\n"
        "from .base_fields import BaseFields as BaseFields\n"
        "from .user import User as User\n"
    )
    run_generated(tmp_path, "from models import Base, BaseFields, User\nprint('ok')")

    # Running it again doesn't add a duplicate line.
    runner.invoke(app, ["add", "model", "BaseFields", "--no-install", "--force"])
    assert (tmp_path / "models" / "__init__.py").read_text() == init

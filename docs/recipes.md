# Recipes

## Add a compose service

1. `src/pavilion/compose/services/<name>.py`: a `_build(version) -> dict` (service body
   without `image`) and a `ServiceSpec` (versions newest first, named volumes).
2. Register it in `compose/services/__init__.py` (`SERVICES`).
3. Test in `tests/compose/test_add_service.py`; `add service list` and `--help` pick it
   up automatically. If you can, validate output with `docker compose config -q`.

## Add a model

1. `src/pavilion/models/templates/<module>.py.jinja` importing `from .base import Base`.
2. A `ModelSpec(name, module, description)` in `models/scaffold.py`, added to `MODELS`
   (the CLI argument and menu pick it up).
3. Test it like `USER_MODEL_CHECK`: take the `database_url` fixture (fresh Postgres
   database), `run_generated(tmp_path, SCRIPT, database_url)`, and in the script
   `create_engine(os.environ["DATABASE_URL"])` + `create_all`. Extra packages go
   through `deps.ensure_dependency`.

## Add a new `pavilion add <feature>`

1. `src/pavilion/<feature>/` with `__init__.py` (one-line docstring), `cli.py` (the
   command function), and the logic in its own module(s).
2. Attach it in `src/pavilion/cli.py` (`add_app.command("<feature>")(fn)` or `add_typer`).
3. Use `ui.select` / `ui.text` for prompts (they handle no-TTY and Ctrl+C) and
   `raise ui.fail(...)` for errors. Check for conflicts before prompting.
4. Tests in `tests/<feature>/`; the autouse fixture already chdirs into `tmp_path`.
5. README usage section + docs/architecture.md.

## Add an `add auth` option

1. Enum (or field) on `AuthConfig` in `auth/config.py`; update `describe()`.
2. Flag + prompt in `auth/cli.py`, in the prompt order documented in architecture.md;
   reject flag combinations that don't apply with `typer.BadParameter`.
3. Expose it to templates via the context in `auth/scaffold.py`; add any new output file
   to the templates dicts (it then joins `ALL_OUTPUT_FILES` automatically).
4. Templates: keep each rendered variant readable on its own; `trim_blocks`/
   `lstrip_blocks` let `{% if %}` lines sit indented without leaving blank lines.
5. Tests: render it and *run* the generated code with `run_generated(tmp_path, SCRIPT,
   *argv)` — scripts are plain Python strings built on the `USERS` prelude.
6. Lint every variant:
   `uvx ruff check --select E,F,W,I,B,UP --line-length 100 <generated dirs>`.

## Check interactive prompts for real

CliRunner has no TTY, so prompts are skipped in tests. To see them, run from a scratch
directory:

```sh
cd "$(mktemp -d)"
# transport, strategy, algorithm (EdDSA -> RS256), separate refresh keys, RSA 4096,
# access TTL, refresh TTL, hashing
python ~/projects/pavilion/scripts/drive_tty.py "add auth" \
    ENTER ENTER UP UP ENTER DOWN ENTER BS*4 4096 ENTER ENTER ENTER ENTER
```

Steps are one per keystroke group: `ENTER`, `UP`, `DOWN`, `ESC`, `BS*N`, or literal text.
Text prompts are prefilled with their default, so clear it with `BS*N` first. The script
kills the app after `--timeout` (30s), so a misaligned step list can't hang. Redrawn
lines are merged, so the output looks a little garbled but every answer is visible.

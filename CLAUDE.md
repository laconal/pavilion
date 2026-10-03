# pavilion

A project scaffolder CLI (Typer + uv). Every command is `pavilion add <thing>`:

- `add docker list | redis | postgres` — add a service to docker-compose.yml
- `add keys [RS256|ES256|EdDSA]` — PEM signing key pair in `secrets/`
- `add auth` — generate a framework-agnostic JWT auth package (`auth/`) + keys/secrets
- `add model list | User | BaseFields` — SQLAlchemy models in `models/` (Postgres); runs
  `uv add sqlalchemy` if missing

Interactive by default (arrow-key menus, text prompts); every prompt has a flag.

More context, read when relevant:
- [docs/architecture.md](docs/architecture.md) — modules, command flows, the generated auth package
- [docs/decisions.md](docs/decisions.md) — why things are the way they are, incl. the user's explicit choices
- [docs/recipes.md](docs/recipes.md) — adding a service/feature/auth option, testing prompts by hand

## Commands

```sh
unset VIRTUAL_ENV            # the user's shell points it at another project; uv warns otherwise
uv run pytest -q             # ~66 tests, ~16s (generated code runs in subprocesses;
                             # model tests start a throwaway postgres:18 Docker container)
uv run --isolated --python 3.12 pytest -q   # oldest supported Python; .venv is left alone
uv run pavilion --help
uv build --wheel             # check templates ship: unzip -l dist/*.whl | grep templates
```

Run pavilion itself from a scratch directory, never the repo root: it writes
`auth/`, `models/`, `secrets/` and `docker-compose.yml` into the current directory, and
`add model` runs `uv add` on the nearest pyproject.toml — which would be pavilion's own.

## Layout

Feature folders, each with its command (`cli.py`) next to its logic:

```
src/pavilion/
  cli.py      root Typer app; only wires feature commands under `add`
  ui.py       select() / text() prompts and fail(); no-TTY -> return the default
  deps.py     ensure_dependency(): `uv add <pkg>` in the user's project unless declared
  compose/    cli.py, file.py (ruamel round-trip edit), services/ (one module per service)
  keys/       cli.py (+ prompts reused by auth), generate.py (KeyPair, generate/check/ensure)
  auth/       cli.py, config.py (enums + AuthConfig), ttl.py, scaffold.py, templates/*.jinja
  models/     cli.py, scaffold.py (ModelSpec registry MODELS), templates/*.jinja
tests/        mirrors features; conftest.py chdirs every test into tmp_path
scripts/drive_tty.py   drive the real prompts in a pseudo-terminal
```

Dependency direction: `auth` -> `keys`; features never import the root `cli.py`.

## Conventions

- **Validate before writing, check before prompting.** Fail on existing files / key
  mismatches before generating anything, and before asking questions that can't be used.
- **Existing files are never overwritten without `--force`**; `add auth --force` also
  deletes pavilion-owned files the new config doesn't use (`ALL_OUTPUT_FILES`).
- Errors: `raise ui.fail("message")` (stderr, exit 1). Bad flag combos:
  `typer.BadParameter(..., param_hint="--flag")` (exit 2).
- Each prompt falls back to its default without a TTY, so CliRunner tests get defaults.
- Generated code must be lint-clean, readable as normal Python, and runnable: auth tests
  execute it (login/refresh/logout) for every option combination.
- Keep docs in step: README.md (user-facing) and these files when behavior changes.
- No formatter is configured; match surrounding style. The user hand-edited
  `auth/config.py` to single blank lines between enum classes — leave that as is.

## Gotchas

- **Supports Python >= 3.12** (`requires-python`); the floor is PEP 695 generics in
  `ui.py`. Don't use 3.13/3.14-only syntax or stdlib (e.g. unparenthesized `except A, B`,
  `copy.replace`) in pavilion or in generated templates. Dev uses 3.14 (`.python-version`).
- **Typer 0.27 vendors click** (`typer._click`); `import click` fails. Restrict choices
  with an `Enum` (built dynamically if needed, see compose/cli.py), custom types with
  `typer.Option(parser=...)`.
- **Rich error boxes wrap at 80 columns** in CliRunner output: assert on short phrases.
- **Generated packages (`auth`, `models`) clash in `sys.modules`**, so tests run them via
  `subprocess` + `sys.executable` (`run_generated` in the test files). `pyjwt`,
  `argon2-cffi`, `bcrypt`, `sqlalchemy` are dev deps only for that.
- **Postgres is the only target database** (user's decision): no SQLite variants or
  workarounds in templates. Model tests use the `database_url` fixture
  (tests/models/conftest.py): a fresh database per test on a throwaway `postgres:18`
  container (random port, `pavilion-test-*`, removed after the session) or on
  `PAVILION_TEST_POSTGRES_URL`. The user runs other Postgres containers on this machine
  (`postgres`, `postgres-salon`) — never touch those.
- Postgres `now()` is the transaction start time: a timestamp set by INSERT and by an
  UPDATE in the same transaction are equal. Commit between steps in tests.
- Tests must never run a real `uv add`: use the `uv_calls` fixture
  (tests/models/test_add_model.py), which fakes `deps.subprocess.run` / `shutil.which`.
- Jinja env uses `trim_blocks`, `lstrip_blocks`, `StrictUndefined`; a missing context
  variable is an error, not an empty string.
- questionary menus wrap around (UP from the first item selects the last).
- `pkill -f "pavilion ..."` matches your own bash command line and kills it.
- No commits yet; the git default branch for PRs is `main` (working branch: `master`).

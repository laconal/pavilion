# Architecture

## Entry point

`pyproject.toml` `[project.scripts] pavilion = "pavilion:main"` -> `pavilion/__init__.py`
`main()` -> `cli.app()`. `uv run` installs the package editable (a `.pth` pointing at
`src/`), so code changes apply without reinstalling.

`cli.py` builds `app` -> `add` and attaches: `compose.cli.service_app` as `add service`,
`keys.cli.add_keys` as `add keys`, `auth.cli.add_auth` as `add auth`.

## ui.py

- `select(message, {value: label}, default=None)` — questionary arrow-key menu; default is
  the first option unless given. Ctrl+C/Esc -> `typer.Abort`.
- `text(message, default, validate)` — free text; `validate` returns True or an error string.
- `interactive()` is `sys.stdin.isatty()`; both prompts return the default without a TTY.
- `fail(message, color)` prints to stderr and returns `typer.Exit(1)` to `raise`.

## compose (`add service`)

- `services/base.py` `ServiceSpec(name, description, image_template, versions, build, volumes)`.
  `versions` is newest-first (first = default). `build(version)` returns the service body
  without `image`, so config can vary by version (Postgres data dir does).
- `services/__init__.py` `SERVICES` registry. `cli.py` registers `list` plus one
  subcommand per spec, each with a `--version` option restricted by a generated `StrEnum`.
- `file.py`: `find_compose_file` uses docker's lookup order (`compose.yaml`, `compose.yml`,
  `docker-compose.yaml`, `docker-compose.yml`), else creates `docker-compose.yml`.
  ruamel.yaml round-trip keeps comments/order. `_to_yaml_node` quotes port mappings and
  renders `["CMD", ...]` healthchecks in flow style. Named volumes are added if missing.
- Flow: existing service? -> fail (unless `--force`) -> choose version -> write.

## keys (`add keys`)

- `generate.py`:
  - `Algorithm` (RS256/ES256/EdDSA, JWA names), `DESCRIPTIONS`, RSA size limits.
  - `KeyPair(private, public)`; `KeyPair.in_dir(dir, refresh=False)` ->
    `private.pem`/`public.pem` or `private_refresh.pem`/`public_refresh.pem`.
  - `secret_path(dir, refresh=False)` -> `jwt_secret` / `jwt_secret_refresh`.
  - `generate_keys(keys, alg, rsa_key_size, force)` — PKCS#8 private (0600, created with
    that mode), SubjectPublicKeyInfo public (0644). `_prepare_directory` makes the dir 0700
    with a `.gitignore` of `*` / `!.gitignore`.
  - `check_keys` — True if a matching pair exists, False if none, raises `KeyMismatchError`
    (carries `.keys`) on incomplete pair / wrong algorithm / wrong RSA size.
  - `ensure_keys` / `ensure_secret` — generate unless present; return True if generated.
- `cli.py`: `add_keys` (+ `--refresh`, `--rsa-bits`, `-d`, `--force`), and the shared
  `choose_algorithm`, `choose_rsa_bits`, `check_rsa_bits`, `RsaBitsOption` used by auth.

## auth (`add auth`)

Prompt order (each skipped if its flag is given):
transport -> strategy -> algorithm (asymmetric only, EdDSA preselected) -> refresh keys ->
RSA size (RS256 and some key pair still missing) -> access TTL -> refresh TTL -> hashing.

- `config.py`: `Transport` (header/cookie), `Strategy` (asymmetric/symmetric, symmetric =
  HS256), `Hashing` (argon2/bcrypt), `RefreshKeys` (shared/separate), `AuthConfig` with
  `templates`, `dependencies`, `describe()`. `ALL_OUTPUT_FILES` = every file auth may write.
- `ttl.py`: `TTL(amount, unit)`; `TTL.parse("30m"|"3h"|"7d"|"90s"|"3")` (bare = hours);
  `.python()` -> `timedelta(hours=3)` keeping the typed unit; `validate_ttls` requires
  refresh > access. Defaults 3h / 24h.
- `scaffold.py` `scaffold_auth(config, directory, secrets_dir, rsa_key_size, force)`:
  1. existing pavilion files in `directory` -> `AuthFilesExistError` unless force
  2. `_prepare_secrets`: check every key pair first, then ensure each (notes for output)
  3. render templates; with force, delete stale files not in this config
- Template context: `cookie`, `hashing`, `asymmetric`, `algorithm` (JWA name, HS256 for
  symmetric), `separate_refresh_keys`, `access_ttl`/`refresh_ttl` (Python source),
  `access_keys`/`refresh_keys` (KeyPair), `access_secret`/`refresh_secret` (posix str),
  `package` (directory name, for import examples).

## models (`add model`)

- `scaffold.py`: `ModelSpec(name, module, description)` (template = `<module>.py.jinja`),
  registry `MODELS`. `scaffold_model` fails if `<module>.py` exists (unless force), creates
  `base.py` / `__init__.py` only when missing (never overwritten, even with force), and
  reports `needs_export` when an existing `__init__.py` doesn't mention the model.
- `cli.py`: `model_app` group (like `add service`): `list` plus one subcommand per
  `MODELS` entry, each with `-d`, `--install/--no-install`, `--force`. Names are
  case-insensitive via `context_settings={"token_normalize_func": ...}` mapping any case
  to the registered name. No subcommand -> menu in a TTY, help otherwise. After writing,
  `--install` (default) calls `deps.ensure_dependency("sqlalchemy", cwd)`.
- `deps.py`: finds the nearest `pyproject.toml` upward, reads `[project] dependencies`
  (PEP 503-normalized names, extras/specifiers ignored), runs `uv add <pkg>` in that
  directory if missing. Statuses: ADDED, ALREADY_PRESENT, NO_PROJECT, NO_UV, FAILED
  (FAILED exits 1; the generated files stay).
- An existing `__init__.py` that doesn't mention the model gets a re-export line
  (`from .x import X as X`) inserted among the `from .` imports in sorted order.
- Generated `BaseFields`: `__abstract__`, `eager_defaults`, `BigInteger` id (BIGSERIAL),
  `created_at`/`updated_at` `DateTime(timezone=True)` with `server_default=func.now()`
  (+ `onupdate` for updated_at); a `@validates("created_at")` that always raises makes
  it read-only (DB-filled values don't go through validators).
- Generated `User`: SQLAlchemy 2.0 typed `Mapped[...]` columns, `@validates("login")`
  lowercasing via `normalize_login()`, `active` with `default=True` + `server_default=true()`.

## The generated auth package

Framework-agnostic, synchronous, relative imports (works under any package name):

| File | Contents |
|---|---|
| `tokens.py` | `ALGORITHM`, TTLs, key file paths (env-overridable), `_signing_key(type)` / `_verification_key(type)`, `create_access_token`, `create_refresh_token`, `decode_token(token, expected_type)` |
| `service.py` | `User` (`id`, `hashed_password`) / `UserRepository` protocols, `RevokedTokenStore` + `InMemoryRevokedTokenStore`, `TokenPair`, `AuthService.login/refresh/logout/authenticate` |
| `passwords.py` | `hash_password` / `verify_password` (argon2-cffi or bcrypt) |
| `cookies.py` (cookie only) | `Cookie` (kwargs for `set_cookie`), `token_cookies(pair)`, `cleared_cookies()` |
| `__init__.py` | re-exports + usage example in the docstring |

Token claims: `sub`, `type` (access/refresh), `jti`, `iat`, `exp`. Refresh rotates (old
jti revoked); logout revokes the refresh jti; unknown-user login still hashes (timing).
Cookies: access `SameSite=Lax`, path `/`; refresh `SameSite=Strict`, path `/auth`;
both HttpOnly + Secure, `max_age` from the TTLs.

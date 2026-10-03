# Decisions

Why things are the way they are. "User:" marks an explicit choice or correction from
the project owner — don't undo those without asking.

## Packaging

- Distributed as a CLI tool: users run `uvx pavilion ...` or `uv tool install pavilion`,
  not `uv add`. Published on PyPI (0.1.0, 0.1.1); a version can never be re-uploaded,
  so bump with `uv version --bump patch` before every `uv publish`.
- MIT license (`LICENSE`, `license = "MIT"` in pyproject); first shipped after 0.1.1.
- User: `requires-python` lowered from 3.14 to 3.12 (tests pass on 3.12, 3.13, 3.14).

## CLI shape

- User: compose services are added with `pavilion add docker <name>` (renamed from
  `add service`, which was in 0.1.x releases — a breaking change). The code keeps the
  `compose/` folder and `add_service()` names, since they edit the compose file.
- User: `pavilion add service ...` is reserved for application-level service code to
  come — e.g. a Redis service (get/set/delete helpers), a RabbitMQ service, a service
  layer. So "docker" means infrastructure in docker-compose, "service" means code.
  Don't add a backward-compatible `add service` alias for the docker command.
- `add docker` / `add model` are command groups with one subcommand per entry, not a
  `name` argument — so `list` can coexist with the names.
- Interactive first, flags for everything. Without a TTY every prompt takes its default,
  which keeps CI/scripts working and makes CliRunner tests deterministic.
- Arrow-key menus come from questionary; Typer's own prompt can only take typed input.
- User: feature-first folder layout (compose/, keys/, auth/), each with its own `cli.py`.

## Compose

- ruamel.yaml (round-trip) so editing an existing compose file keeps comments and order.
- Only port mappings get quoted ("6379:6379" is a base-60 int to YAML 1.1 parsers).
- Images: `redis:{8,7}-alpine`, `postgres:{18,17,16,15}-alpine`, newest is the default.
- Postgres 18+ mounts `/var/lib/postgresql`, older `/var/lib/postgresql/data` — mounting
  an old image at the new path would silently put data in an anonymous volume.
- Postgres credentials are `${POSTGRES_USER:-postgres}`-style so a `.env` can override
  them; the healthcheck uses `$$` so the container's env is read, not compose's.

- PgBouncer uses `edoburu/pgbouncer` (no official image; the user already runs it).
  Configured by env vars, verified against the image's /entrypoint.sh and in a real
  compose stack: `DATABASE_URL` without a database name (pools every database, `*`),
  `AUTH_TYPE=scram-sha-256` (image default md5 doesn't match Postgres 14+),
  `POOL_MODE=transaction`, `MAX_PREPARED_STATEMENTS=100` (asyncpg/psycopg prepared
  statements work, PgBouncer 1.21+), host port 6432 -> container 5432, `depends_on`
  postgres healthy, `pg_isready` healthcheck. Credentials reuse the postgres service's
  `${POSTGRES_USER:-postgres}`-style variables, so a password must be URL-safe.

## Keys

- JWA algorithm names (RS256, not "rsa256"); input is case-insensitive.
- RSA size: user asked for an input with default 2048; range 2048–16384. Only prompted
  when new RSA keys will actually be generated.
- User: separate refresh keys live next to the access keys as `private_refresh.pem` /
  `public_refresh.pem` (and `jwt_secret_refresh`), not in a `secrets/refresh/` folder.
- `secrets/.gitignore` (`*`, `!.gitignore`) so keys can't be committed even without a
  root .gitignore. Private keys are created 0600 from the start.
- `add keys` default (no TTY) is RS256 for compatibility; `add auth` preselects EdDSA
  (user's mockup).

## Models

- User: `pavilion add model User` generates a SQLAlchemy model with the fields they
  specified (users table; firstname/lastname/login 255, middlename nullable,
  hashed_password, active default true, login saved lowercase).
- Added beyond the spec: `id` primary key, `unique=True` on `login`, middlename length 255.
- `hashed_password` is `String(255)`, not Text: argon2 ~100 / bcrypt 60 chars, bounded,
  and VARCHAR is friendlier on MySQL; on Postgres they're equivalent.
- Lowercase login uses `@validates` instead of a Python `@property` (user said
  "property"): it covers the constructor and assignments and keeps `User.login` a plain
  column for queries. A property would need a `_login` column plus a hybrid property.
  Bulk UPDATE statements bypass it; `normalize_login()` is exported for lookups.
- User: the command installs SQLAlchemy (`uv add`) when it's missing. This differs from
  `add auth`, which only prints `Next: uv add ...` — aligning auth is an open option.
- The auth `User` protocol attribute was renamed `password_hash` -> `hashed_password`
  to match the model, so the two generated packages work together unchanged.

- User: **PostgreSQL is pavilion's database.** Templates are written for Postgres only
  (no SQLite variants), and model tests run against real Postgres 18 in Docker.
- User: `add model BaseFields` — abstract parent with `id` BigInteger autoincrement PK,
  `created_at` (auto on insert, not editable), `updated_at` (auto on update, editable).
  Choices: timestamps are timezone-aware; `updated_at` is also set on insert (NOT NULL,
  equals created_at at first); "not editable" = assigning raises AttributeError, also in
  the constructor; `onupdate` only covers UPDATEs issued through SQLAlchemy (raw SQL
  would need a trigger); `eager_defaults` so async sessions get the timestamps.
- `autoincrement=True` on Postgres renders BIGSERIAL (as the user specified); an
  `Identity()` column (GENERATED ... AS IDENTITY) would be the modern alternative.
- `User` still has its own Integer `id` and doesn't inherit `BaseFields` (not requested).

## Services

- User: `pavilion add service redis` generates `RedisService` with create/update/get/
  delete, and puts `REDIS_URL` (default `redis://localhost:6379`) in `.env` — creating
  it, or appending when the key is missing.
- Semantics chosen: create = set only if new (`NX`), update = only if it exists (`XX`),
  keeping the TTL unless one is given (`KEEPTTL`); every method returns whether it did
  anything; values are str (`decode_responses=True`); `ttl` is seconds or a timedelta.
- Async client by default (FastAPI-style apps; models already use eager_defaults for
  async), `--client sync` available. Earlier generated code (auth) is sync.
- An existing `REDIS_URL` in `.env` is never changed (it may point at a real server).
  `.env` goes next to the nearest pyproject.toml. Warn when git doesn't ignore it.
- The generated code reads `os.environ` and doesn't load `.env` itself (no
  python-dotenv / pydantic-settings dependency); docs say to use `uv run --env-file`.
- File is `services/redis_service.py` — `services/redis.py` could shadow the `redis`
  package when run from inside the folder.
- `redis` is installed like SQLAlchemy is for models (`--no-install` to skip).

## Auth

- User: transport means *how JWTs travel* — Authorization header or HttpOnly cookies.
  "Cookies" does NOT mean server-side `session_id` sessions; that mode existed briefly and
  was removed. Both transports share tokens.py/service.py; cookie adds cookies.py.
- Generated code is framework-agnostic and sync; the user implements `UserRepository`.
  A FastAPI router, async variant, Redis-backed stores or CSRF tokens are possible
  follow-ups that were offered, not requested.
- Dependencies are printed (`Next: uv add ...`), not installed into the user's project.
- User: TTLs are prompted, defaults 3h access / 24h refresh. The unit typed is kept in the
  generated `timedelta`. Known trade-off (told to the user): logout only revokes refresh
  tokens, so a stolen access token stays valid up to the access TTL.
- Separate refresh keys: tokens are signed/verified with per-type keys, so a refresh
  token presented as an access token fails the signature, not just the `type` claim.
- Cookie mode: refresh cookie path `/auth` + SameSite=Strict; CSRF protection relies on
  SameSite only (sibling-subdomain attacks are not covered — offered as a follow-up).
- Generated `except (A, B):` keeps parentheses (works on Python < 3.14 too), even though
  ruff's 3.14 formatter would drop them.
- `--force` deletes pavilion-owned files the new configuration doesn't use, after a stale
  `tokens.py` survived a JWT -> sessions switch.

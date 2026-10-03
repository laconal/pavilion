# pavilion

A project scaffolder built with Typer.

## Install

```sh
uv tool install .        # or: uv run pavilion ...
```

## Usage

```sh
pavilion add docker list              # show available services
pavilion add docker redis             # add redis to the compose file in the current dir
pavilion add docker postgres          # pick a version with the arrow keys
pavilion add docker postgres --version 17    # non-interactive
pavilion add docker redis -f infra/compose.yaml
pavilion add docker redis --force     # overwrite an existing redis service
```

`pavilion add docker pgbouncer` puts PgBouncer (`edoburu/pgbouncer`) in front of the
`postgres` service, so add that first. It pools every database in transaction mode with
the postgres credentials (SCRAM), supports prepared statements, and listens on
`localhost:6432`: point the app's database URL there, and run migrations against
postgres directly (5432).

`pavilion add docker celery` adds `celery-worker` and `celery-beat`, built from the
project's `./Dockerfile` (it warns if there isn't one) and using the compose `redis`
service as broker (db 0) and result backend (db 1), so add Redis first. It asks for the
`celery -A` app (default `app.worker`, or `-A app.worker:celery_app`). Celery reads
`CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` from the environment, so a plain
`Celery("app")` needs no broker settings in code. `.env` is loaded if present, with
`REDIS_URL` pointed at the `redis` container. Run a single beat.

Pavilion edits the first of `compose.yaml`, `compose.yml`, `docker-compose.yaml` or
`docker-compose.yml` it finds, or creates `docker-compose.yml`. Existing comments and
ordering are preserved.

Available services: `redis` (8, 7) and `postgres` (18, 17, 16, 15). Without `--version`,
pavilion asks interactively; when there's no terminal (CI, pipes) it uses the newest.

Postgres defaults (`postgres` / `postgres`, database `app`) can be overridden with
`POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` in a `.env` file.

### Keys

```sh
pavilion add keys                     # pick an algorithm with the arrow keys
pavilion add keys ES256               # RS256 | ES256 | EdDSA (case-insensitive)
pavilion add keys EdDSA -d config/jwt # custom directory (default: secrets)
pavilion add keys RS256 --rsa-bits 4096  # RSA key size (default 2048, prompted if omitted)
pavilion add keys RS256 --force       # replace an existing key pair
pavilion add keys EdDSA --refresh     # refresh-token pair: private_refresh.pem, public_refresh.pem
```

Writes `private.pem` (PKCS#8, mode 0600) and `public.pem` (SubjectPublicKeyInfo).
The directory gets its own `.gitignore` so keys are never committed by accident.

### Auth

```sh
pavilion add auth                     # answer the prompts with the arrow keys
pavilion add auth --transport cookie --algorithm ES256 --hashing argon2
pavilion add auth --transport header --strategy symmetric
pavilion add auth --algorithm RS256 --rsa-bits 3072 --refresh-keys separate
pavilion add auth --access-ttl 30m --refresh-ttl 7d
```

Generates a framework-agnostic `auth/` package (`-d` to change) built on JWT access and
refresh tokens. Their lifetimes default to 3h and 24h; enter them as `30m`, `3h`, `7d`
or `90s` (a bare number means hours), and the refresh TTL must be the longer one.

| File | Contents |
|---|---|
| `tokens.py` | create/verify access and refresh tokens |
| `service.py` | `AuthService.login / refresh / logout / authenticate` |
| `passwords.py` | `hash_password` / `verify_password` (Argon2 or bcrypt) |
| `cookies.py` (`--transport cookie`) | HttpOnly cookie settings for `response.set_cookie(**cookie.kwargs)` |

With `--transport header` clients send `Authorization: Bearer <access token>`; with
`--transport cookie` the tokens are set as HttpOnly cookies (the refresh cookie is
`SameSite=Strict` and only sent to `/auth`).

Implement `UserRepository.get_by_username()` for your user model; see the generated
`__init__.py` for an example. Asymmetric signing reuses (or creates) the key pair in
`secrets/`; symmetric creates `secrets/jwt_secret`. With `--refresh-keys separate`,
refresh tokens are signed with their own keys/secret (`secrets/private_refresh.pem` and
`public_refresh.pem`, or `secrets/jwt_secret_refresh`), so a leaked
access key can't forge refresh tokens. The in-memory revoked-token store is for
development; back it with Redis or a database in production.

### Models

```sh
pavilion add model list               # show available models
pavilion add model User               # SQLAlchemy model in models/ (-d to change)
pavilion add model BaseFields         # abstract parent: BigInteger id, created_at, updated_at
pavilion add model User --no-install  # don't touch pyproject.toml
```

Generates `models/base.py` (a `DeclarativeBase` with a constraint naming convention;
created once and never overwritten), `models/user.py` and `models/__init__.py`. If the
project's `pyproject.toml` doesn't list SQLAlchemy yet, pavilion runs `uv add sqlalchemy`.

The `User` model (`users` table): `id`, `firstname`, `lastname`, `middlename` (nullable),
`login` (unique, always stored lowercase), `hashed_password`, `active` (default true).
Look users up with `User.login == normalize_login(raw)`. It fits the generated auth
package's `User` protocol as is.

`BaseFields` is an abstract model to inherit from (`class Post(BaseFields): ...`): a
`BigInteger` auto-increment `id`, `created_at` (set by the database on insert, read-only)
and `updated_at` (set on insert and on every update, editable). Both timestamps are
timezone-aware. Each new model is added to `models/__init__.py` in sorted order.

The models target PostgreSQL.

### Services

```sh
pavilion add service list             # show available services
pavilion add service redis            # RedisService in services/ (-d to change)
pavilion add service redis --client sync --no-install
```

`RedisService` wraps redis-py (async by default, `--client sync` for a blocking client):
`create` (only if the key is new), `get`, `update` (only existing keys; keeps the expiry
unless a new `ttl` is given) and `delete`, each returning whether it did anything.
Use it as `async with RedisService() as redis: ...`.

It reads `REDIS_URL`, so pavilion adds `REDIS_URL=redis://localhost:6379` to the project's
`.env` (created if missing; an existing value is never changed) and warns if `.env` isn't
git-ignored. `.env` isn't loaded automatically: use `uv run --env-file .env ...` or
Compose's `env_file`. The `redis` package is added with `uv add` if it's missing, and if
the compose file has no Redis yet, pavilion suggests `pavilion add docker redis`.

### Utils

```sh
pavilion add util list                # show available utilities
pavilion add util generate_token      # adds it to utils/tokens.py (-d to change)
pavilion add util timed --force       # replace an existing definition
```

| Util | Module | What |
|---|---|---|
| `generate_password(length=12)` | `passwords.py` | random password: letters, digits, `!@#$%^&*-_=+?` |
| `generate_token(nbytes=32)` | `tokens.py` | URL-safe random token (reset links, API keys) |
| `generate_code(digits=6)` | `tokens.py` | numeric code as a string, e.g. `"042917"` |
| `hash_token(token)` | `tokens.py` | SHA-256 hex, to store tokens hashed |
| `mask_email(email)` | `masking.py` | `m***r@gmail.com` |
| `mask_secret(secret, visible=4)` | `masking.py` | `****f3a9` |
| `@retry(attempts=3, exceptions=..., delay=0.5, backoff=2, max_delay=30, jitter=True)` | `retry.py` | retries sync/async functions with exponential backoff |
| `timer(label)` | `timing.py` | `with timer("x") as t:` logs the duration, `t.seconds` |
| `@timed` | `timing.py` | logs each call's duration (sync/async); adds `timer` too |
| `slugify(text, separator="-", allow_unicode=False)` | `text.py` | `Hello, World!` -> `hello-world` |
| `utcnow()` | `dates.py` | timezone-aware UTC now |

Utilities live in topic modules: adding one to an existing module appends the function
and merges its imports, leaving everything else in the file alone. `--force` replaces
just that function. Everything is re-exported from `utils/__init__.py`
(`from utils import retry`). Standard library only.

## Development

Each `pavilion add ...` feature lives in its own folder under `src/pavilion/`, with its
command (`cli.py`) next to the logic behind it:

```
cli.py              root app; wires the feature commands together
ui.py               shared menus, prompts and error exits
services/           add service   (scaffold.py: AppServiceSpec registry; templates/)
utils/              add util      (scaffold.py: UtilSpec registry; templates/)
compose/            add docker    (file.py edits the compose file; services/ has one module per service)
keys/               add keys      (generate.py)
auth/               add auth      (config.py, scaffold.py, templates/)
```

To add a compose service, create `compose/services/<name>.py` with a `ServiceSpec` and
register it in `compose/services/__init__.py`. Tests mirror this layout under `tests/`.


```sh
uv run pytest
```

The model and service tests run against real PostgreSQL and Redis: throwaway
`postgres:18` / `redis:7-alpine` Docker containers, or the servers in
`PAVILION_TEST_POSTGRES_URL` (an admin URL such as
`postgresql://postgres:secret@localhost:5432/postgres`) and `PAVILION_TEST_REDIS_URL`
(its database is flushed). Without either they're skipped.

## License

MIT, see [LICENSE](LICENSE).

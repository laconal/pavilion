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

- `pavilion add service <name>` is a command group with one subcommand per service, not
  a `name` argument — so `add service list` can coexist with service names.
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

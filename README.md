# pavilion

A project scaffolder built with Typer.

## Install

```sh
uv tool install .        # or: uv run pavilion ...
```

## Usage

```sh
pavilion add service list             # show available services
pavilion add service redis            # add redis to the compose file in the current dir
pavilion add service postgres        # pick a version with the arrow keys
pavilion add service postgres --version 17   # non-interactive
pavilion add service redis -f infra/compose.yaml
pavilion add service redis --force    # overwrite an existing redis service
```

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

## Development

Each `pavilion add ...` feature lives in its own folder under `src/pavilion/`, with its
command (`cli.py`) next to the logic behind it:

```
cli.py              root app; wires the feature commands together
ui.py               shared menus, prompts and error exits
compose/            add service   (file.py edits the compose file; services/ has one module per service)
keys/               add keys      (generate.py)
auth/               add auth      (config.py, scaffold.py, templates/)
```

To add a compose service, create `compose/services/<name>.py` with a `ServiceSpec` and
register it in `compose/services/__init__.py`. Tests mirror this layout under `tests/`.


```sh
uv run pytest
```

## License

MIT, see [LICENSE](LICENSE).

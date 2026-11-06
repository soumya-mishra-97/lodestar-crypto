# Security model

Lodestar holds information about your money (holdings, cost basis, notes), so it is built as if exposed to the internet, even when it runs on your laptop. It is **read-only by design**: it never asks for, stores or uses private keys, never signs anything and never places trades. The Trader Skills are **paper trading only**: simulated positions on stored daily bars, with no order-placement code path and no setting for exchange keys with trading rights.

## Threats considered

| Threat | Controls |
|---|---|
| Unauthenticated access (local mode) | `LS_AUTH_MODE=local` (the default) has no login and is only for a stack bound to localhost (compose publishes every port on `127.0.0.1`). Production refuses to boot unless `LS_AUTH_MODE=password` |
| Account takeover | Argon2id hashing; 12-char minimum; login rate limit 5/min/IP (fails **closed** if Redis is down); constant-time dummy verify (no user enumeration); generic "Invalid credentials" |
| Token theft (XSS) | Access JWT is 15 min and **memory-only** (never localStorage). Refresh token is an `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/v1/auth` |
| Token replay | Refresh tokens are single-use (rotated on every refresh, stored as SHA-256 hashes in Redis); logout revokes immediately |
| JWT attacks | Algorithm pinned to HS256 (`alg=none` / confusion blocked); `exp`, `iat`, `iss`, `sub` required |
| CSRF | SameSite=Strict cookie only reaches auth endpoints; all other endpoints require the `Authorization` header (the SSE stream is read with `fetch`, so it carries the header too) |
| Privilege escalation | First account is `owner`; registration then closes (`LS_ALLOW_REGISTRATION=false`). Mutations that cost money or change holdings require `owner` |
| IDOR | Every watchlist/portfolio query is filtered by the authenticated user id; ids are random UUIDs |
| Injection (SQL) | SQLAlchemy parameterised queries only; no string-built SQL |
| Input abuse | Pydantic schemas with `extra="forbid"`, length/range limits, regex-validated coin ids and search queries, 256 KB body cap, CSV import capped at 200 KB / 500 rows with line-numbered errors |
| Key / seed-phrase leakage | Wallet import accepts **public addresses only**; anything shaped like a hex or WIF private key, an extended private key or a 12-24 word seed phrase is rejected (also inside CSV rows) before it is stored, logged or sent, with a warning to treat it as compromised. Balance reads are `eth_getBalance` / `eth_call balanceOf` / mempool.space GETs only |
| Prompt injection | See [ARCHITECTURE.md §6](ARCHITECTURE.md#6-llm-integration): sanitise and screen untrusted text, fence it as data, **read-only** tools with validated arguments, schema output, claim pre-screening and a fail-closed verifier, human approval |
| Accidental real trading | There is no exchange client with order methods in the codebase: Kraken is used through public market-data endpoints only (OHLC, ticker, order book, futures funding). Paper positions open only from a trade plan a human approved; fills are simulated by `domain/trading/paper.py` |
| Unverified output | Nothing reaches the reader without passing the verifier and a human decision; after two failed repairs the run fails closed |
| XXE / XML bombs | RSS parsed with `defusedxml`; responses capped at 2 MB |
| SSRF | Outbound calls go only to fixed provider base URLs (and the configured RPC endpoints); user input is never used as a URL, only as a validated path/param value |
| Cost abuse (LLM) | 30 runs/hour/user, one active run per asset, analyst step limit, at most two repair loops, bounded worker concurrency |
| Data at rest | Holding notes encrypted with MultiFernet (AES-128-CBC + HMAC-SHA256; zero-downtime key rotation). Use encrypted disks / managed DB encryption for the rest |
| Data in transit | HTTPS at the proxy; HSTS when `LS_ENV=production`; DB and Redis bound to loopback in compose |
| Secrets leakage | `SecretStr` settings; log redaction of secret-like keys; `.env` git-ignored; gitleaks in pre-commit + CI; production refuses to boot with default/weak secrets |
| Cache poisoning → RCE | Cache stores JSON only, never pickle |
| Clickjacking / sniffing | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff`, strict CSP on API and SPA |
| Supply chain | Lockfiles (`uv.lock`, `package-lock.json`); `pip-audit`, `npm audit`, Trivy, Dependabot; non-root, read-only containers with `no-new-privileges` |
| Error leakage | RFC 9457 problem responses; 5xx bodies never include internals; request id for correlation |

## API keys

| Key | Where it lives | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Server env / secret manager | Never sent to the browser. Use a dedicated key with a monthly spend limit set in the Anthropic Console |
| `LS_COINGECKO_API_KEY` | Server env | Free demo key is enough for personal use |
| `LS_JWT_SECRET` | Server env | ≥32 random chars; rotating it signs everyone out |
| `LS_FIELD_ENCRYPTION_KEYS` | Server env | Comma-separated; prepend a new key to rotate, re-encrypt, then drop the old key |

For deployment, prefer your platform's secret store (GitHub Actions secrets, Fly/Render secrets, AWS SSM/Secrets Manager, Doppler, 1Password Connect) over `.env` files.

## If you later connect exchange accounts

Lodestar deliberately does not, and trading stays paper-only by design. If you add it, use **read-only** API keys only (no trade/withdraw scopes), IP-allowlisted to your server, stored with `FieldCipher`, and decrypted only inside the worker that uses them.

## Reporting

This is a personal project. If you find an issue, open a private security advisory on the GitHub repository.

"""Generate sha256 hashes of API keys for hashed-at-rest auth.

When APP_AUTH_HASH_KEYS=true, the values in APP_API_KEYS / APP_ADMIN_API_KEYS
must be hex sha256 digests, not the plaintext keys. Run this to produce them:

    uv run python scripts/hash_api_keys.py secret-user-key secret-admin-key

Output is a .env snippet — paste the hashes into your secret store / env.

Keys are one-way hashed (sha256) and compared with hmac.compare_digest at
runtime; the plaintext never leaves this terminal.
"""

from __future__ import annotations

import sys

from app.core.config import sha256_hex


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: uv run python scripts/hash_api_keys.py <key> [<key> ...]")
        return 2
    print("# APP_AUTH_HASH_KEYS=true")
    for key in args:
        print(f"sha256({key!r}) = {sha256_hex(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

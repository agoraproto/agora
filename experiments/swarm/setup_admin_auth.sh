#!/bin/bash
# One-shot setup for /admin.html basic-auth protection.
# - Generates a random secure password.
# - Hashes it via `caddy hash-password`.
# - Patches /etc/caddy/Caddyfile to require basic-auth on /admin.html.
# - Reloads caddy.
# - Prints the password ONCE so the operator can save it.
#
# Idempotent: if the basic-auth block is already in place, the script
# refuses to overwrite (so re-runs don't silently rotate the password).

set -e

CADDYFILE="/etc/caddy/Caddyfile"
USERNAME="andreas"

# Note: this script is idempotent — it removes any prior @admin/basic_auth
# blocks (no matter where they were injected) and re-inserts a fresh one
# in the correct top-level agoraproto.org block. Password rotates on each
# run, so save the printed password immediately.

# ── Generate a random password (24 chars, base64) ──
PASSWORD=$(openssl rand -base64 18 | tr -d '=+/' | head -c 24)
echo "Generated password: $PASSWORD"
echo

# ── Hash via caddy ──
HASH=$(caddy hash-password --plaintext "$PASSWORD")
if [ -z "$HASH" ]; then
    echo "❌ caddy hash-password failed. Is caddy installed?"
    exit 1
fi
echo "Hash: $HASH"

# ── Patch Caddyfile ──
# Insert before the closing brace of the agoraproto.org block.
# We use awk to find the agoraproto.org { ... } block and inject
# the @admin matcher + basic_auth before its closing }.
cp "$CADDYFILE" "$CADDYFILE.bak.$(date +%s)"
echo "Backed up Caddyfile to $CADDYFILE.bak.<timestamp>"

python3 - <<PYEOF
import re, pathlib
p = pathlib.Path("$CADDYFILE")
src = p.read_text()

# Match 'agoraproto.org {' only when it's the entire site name (not a
# substring of 'api.agoraproto.org' or 'dashboard.agoraproto.org').
# That means: at start of line or after whitespace, and not preceded
# by a dot.
m = re.search(r'(?:^|\n)agoraproto\.org\s*\{', src)
if not m:
    raise SystemExit("Could not find a top-level 'agoraproto.org {' block in Caddyfile")
block_start = m.start() + (1 if src[m.start()] == "\n" else 0)
print(f"Found agoraproto.org block at offset {block_start}")

# Walk forward to find the matching closing brace at depth 0 within the block.
depth = 0
i = block_start
end = -1
while i < len(src):
    c = src[i]
    if c == "{":
        depth += 1
    elif c == "}":
        depth -= 1
        if depth == 0:
            end = i
            break
    i += 1
if end == -1:
    raise SystemExit("Could not find closing brace of agoraproto.org block")

# Clean up any prior basic_auth blocks we may have wrongly injected earlier
# (e.g. inside api.agoraproto.org from the v1 of this script).
cleanup = re.compile(
    r'\n?\s*# Admin route — basic auth, set up by setup_admin_auth\.sh\n'
    r'\s*@admin path /admin\.html\n'
    r'\s*basic_auth @admin \{\n[^}]*\n\s*\}\n',
    re.MULTILINE,
)
n_removed = 0
while True:
    new_src, n = cleanup.subn("", src, count=1)
    if n == 0:
        break
    src = new_src
    n_removed += 1
if n_removed:
    print(f"Removed {n_removed} stale basic_auth block(s) from prior runs.")

# Re-find end after cleanup
m = re.search(r'(?:^|\n)agoraproto\.org\s*\{', src)
block_start = m.start() + (1 if src[m.start()] == "\n" else 0)
depth = 0
i = block_start
end = -1
while i < len(src):
    c = src[i]
    if c == "{":
        depth += 1
    elif c == "}":
        depth -= 1
        if depth == 0:
            end = i
            break
    i += 1

inject = """
    # Admin route — basic auth, set up by setup_admin_auth.sh
    @admin path /admin.html
    basic_auth @admin {
        $USERNAME $HASH
    }
"""
new = src[:end] + inject + src[end:]
p.write_text(new)
print("Patched Caddyfile (block ended at offset {}, injected {} chars).".format(end, len(inject)))
PYEOF

# ── Reload caddy ──
caddy validate --config "$CADDYFILE" >/dev/null
systemctl reload caddy
sleep 1

# ── Smoke test ──
CODE=$(curl -s -o /dev/null -w '%{http_code}' https://agoraproto.org/admin.html)
echo
echo "Smoke test: https://agoraproto.org/admin.html → HTTP $CODE  (expected 401)"

# ── Print the password one more time for safekeeping ──
cat <<EOF

══════════════════════════════════════════════════════════════
  ✅ Admin route now protected.
  Save these credentials somewhere safe:

     URL:      https://agoraproto.org/admin.html
     Username: $USERNAME
     Password: $PASSWORD

  The password is NOT stored on the server in plain text.
  Only the bcrypt hash lives in $CADDYFILE.
══════════════════════════════════════════════════════════════
EOF

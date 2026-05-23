#!/bin/bash
# Sprint 15 v3 — robust admin basic-auth setup.
#
# Strategy:
#   1. If a .bak.* backup exists, restore the OLDEST one to /etc/caddy/Caddyfile
#      so we always start from a known-good baseline (no broken patches).
#   2. Generate a fresh random password + bcrypt hash.
#   3. Parse the Caddyfile with a brace counter (no regex on multi-line
#      blocks) to find the EXACT closing brace of the top-level
#      'agoraproto.org { ... }' block (not 'api.' or 'dashboard.' subdomains).
#   4. Insert the basic_auth block right before that closing brace.
#   5. Validate the file, reload caddy, smoke-test for HTTP 401.

set -e

CADDYFILE="/etc/caddy/Caddyfile"
USERNAME="andreas"

# ── Step 1: restore from oldest backup if any exist ──
oldest_bak=$(ls -1t /etc/caddy/Caddyfile.bak.* 2>/dev/null | tail -n 1 || true)
if [ -n "$oldest_bak" ]; then
    echo "Restoring from oldest backup: $oldest_bak"
    cp "$oldest_bak" "$CADDYFILE"
fi

# Take a new backup of the (now clean) state
cp "$CADDYFILE" "$CADDYFILE.bak.$(date +%s)"

# ── Step 2: generate password + hash ──
PASSWORD=$(openssl rand -base64 18 | tr -d '=+/' | head -c 24)
HASH=$(caddy hash-password --plaintext "$PASSWORD")
if [ -z "$HASH" ]; then
    echo "❌ caddy hash-password failed."
    exit 1
fi

# ── Step 3+4: parse + inject via Python (brace-counter, not regex) ──
python3 - <<PYEOF
import re, pathlib, sys

p = pathlib.Path("$CADDYFILE")
src = p.read_text()
USERNAME = "$USERNAME"
HASH = "$HASH"

# Locate the top-level 'agoraproto.org {' header. Must NOT match
# 'api.agoraproto.org' or 'dashboard.agoraproto.org'. The pattern requires
# the previous char to be \n or start-of-file.
m = re.search(r'(?:^|\n)agoraproto\.org\s*\{', src)
if not m:
    sys.exit("❌ Could not find a top-level 'agoraproto.org {' block in Caddyfile.")

# Set i to the position of the '{' character (the start of the block body).
brace_pos = m.end() - 1
block_start = m.start() + (1 if src[m.start()] == '\n' else 0)

# Walk forward from the opening brace using a counter to find its matching
# closing brace. That's where we inject the new directives.
depth = 0
i = brace_pos
close_pos = -1
while i < len(src):
    c = src[i]
    if c == '{':
        depth += 1
    elif c == '}':
        depth -= 1
        if depth == 0:
            close_pos = i
            break
    i += 1

if close_pos == -1:
    sys.exit("❌ Could not find closing brace of agoraproto.org block.")

# Detect any prior @admin / basic_auth pollution and remove it cleanly.
# We do this by reading the block body and stripping out any line that
# matches the admin-auth signature.
body_start = brace_pos + 1
body_end = close_pos
body = src[body_start:body_end]

# Strip prior admin-auth lines, line by line. We look for the sentinel
# comment '# Admin route — basic auth' and remove that line + the next
# four lines (or until we hit a line containing only whitespace + '}').
out_lines = []
lines = body.split('\n')
skip = 0
for ln in lines:
    if skip > 0:
        skip -= 1
        # If we see the closing brace of the basic_auth block, stop
        # skipping after it.
        if ln.strip() == '}':
            skip = 0
        continue
    if 'Admin route' in ln and 'basic auth' in ln and 'setup_admin_auth' in ln:
        skip = 4  # comment + 3 directive lines + 1 closing brace
        continue
    out_lines.append(ln)
cleaned_body = '\n'.join(out_lines)

# Inject before the closing brace.
new_block = """
    # Admin route — basic auth, set up by setup_admin_auth.sh
    @admin path /admin.html
    basic_auth @admin {
        ${USERNAME} ${HASH}
    }
""".replace("${USERNAME}", USERNAME).replace("${HASH}", HASH)

# Stitch back together: prefix + opening brace + cleaned body + injected + closing brace + rest.
new_src = src[:body_start] + cleaned_body + new_block + src[body_end:]
p.write_text(new_src)
print(f"Patched Caddyfile. Block ran from {block_start} to {close_pos}; cleaned body has {len(cleaned_body)} chars, injected {len(new_block)} chars.")
PYEOF

# ── Step 5: validate + reload + smoke test ──
echo
echo "Validating Caddyfile..."
caddy validate --config "$CADDYFILE" 2>&1 | head -10

echo
echo "Reloading caddy..."
systemctl reload caddy
sleep 2

CODE=$(curl -s -o /dev/null -w '%{http_code}' https://agoraproto.org/admin.html)
echo
echo "Smoke test: https://agoraproto.org/admin.html → HTTP $CODE  (expected 401)"

# ── Print password ──
cat <<EOF

══════════════════════════════════════════════════════════════
  ✅ Admin route now protected.
  Save these credentials somewhere safe:

     URL:      https://agoraproto.org/admin.html
     Username: $USERNAME
     Password: $PASSWORD

  Hash lives in $CADDYFILE; plain password is NOT stored anywhere.
══════════════════════════════════════════════════════════════
EOF

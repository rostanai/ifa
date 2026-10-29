#!/bin/sh
# Builds demo/repo-js: commit 2 drops a null-guard, so node throws a TypeError. ci-js.log is the real failing run.
set -e
cd "$(dirname "$0")"
rm -rf repo-js && mkdir repo-js && cd repo-js
git init -q && git config user.email dev@example.com && git config user.name "Dev"
cat > user.js <<'EOF'
function displayName(u) {
  return (u.profile && u.profile.name) || "Anonymous";
}
module.exports = { displayName };
EOF
cat > test.js <<'EOF'
const assert = require("assert");
const { displayName } = require("./user");
assert.strictEqual(displayName({ profile: { name: "Ada" } }), "Ada");
assert.strictEqual(displayName({}), "Anonymous");
console.log("ok");
EOF
git add . && git commit -qm "add displayName()"
cat > user.js <<'EOF'
function displayName(u) {
  return u.profile.name || "Anonymous";
}
module.exports = { displayName };
EOF
git commit -qam "refactor: simplify displayName()"
node test.js > ../ci-js.log 2>&1 || true
echo "demo ready: python3 agent.py demo/repo-js demo/ci-js.log --test 'node test.js'"

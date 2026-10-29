#!/bin/sh
# Builds demo/repo: commit 1 works, commit 2 introduces a regression, ci.log is the real failing run.
set -e
cd "$(dirname "$0")"
rm -rf repo && mkdir repo && cd repo
git init -q && git config user.email dev@example.com && git config user.name "Dev"
cat > calc.py <<'EOF'
def average(xs):
    return sum(xs) / len(xs) if xs else 0.0
EOF
cat > test_calc.py <<'EOF'
from calc import average
assert average([2, 4]) == 3
assert average([]) == 0.0
print("ok")
EOF
git add . && git commit -qm "add average()"
cat > calc.py <<'EOF'
def average(xs):
    return sum(xs) / len(xs)
EOF
git commit -qam "perf: simplify average()"
python3 test_calc.py > ../ci.log 2>&1 || true
echo "demo ready: python3 agent.py demo/repo demo/ci.log --test 'python3 test_calc.py'"

#!/usr/bin/env python3
"""Incident-to-fix agent: CI log -> suspect commit -> Nemotron fix -> verified branch/PR.

usage: agent.py REPO LOGFILE [--test "cmd"] [--pr]      agent.py --selftest
env:   NEBIUS_API_KEY (required), NEBIUS_MODEL, TAVILY_API_KEY (optional doc lookup)
"""
import json, os, re, shlex, subprocess, sys, urllib.error, urllib.request

BASE = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
MODEL = os.getenv("NEBIUS_MODEL", "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1")  # NVIDIA open model


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def parse_log(log):
    """Return (file, line, error message) of the innermost project frame."""
    skip = lambda fs: [f for f in fs if "site-packages" not in f[0] and "node_modules" not in f[0]]
    py = skip(re.findall(r'File "([^"]+)", line (\d+)', log))  # innermost frame is LAST
    other = skip(re.findall(r"\(?([\w./-]+\.(?:js|ts|go|rb|java)):(\d+)", log))  # innermost is FIRST
    errs = re.findall(r"(?:^|\s)(\w*(?:Error|Exception)\b.*)$", log, re.M)  # \s: gh log lines carry a prefix
    if not (py or other):
        return None, None, errs[-1] if errs else log.strip().splitlines()[-1]
    f, n = py[-1] if py else other[0]
    return f, int(n), errs[-1] if errs else "unknown error"


def post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code} from {url}: {e.read().decode()[:300]}")


def docs_lookup(error):
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return ""
    r = post("https://api.tavily.com/search", {"query": error, "max_results": 3},
             {"Authorization": f"Bearer {key}"})
    return "\n".join(f"- {x['title']}: {x['content'][:300]}" for x in r.get("results", []))


def ask_model(error, path, source, culprit, docs):
    prompt = f"""A CI run failed.
Error: {error}
Suspect commit: {culprit}
Relevant docs:\n{docs or '(none)'}
File {path}:\n{source}

Fix the root cause with the smallest change. Reply with JSON only:
{{"explanation": "<2 sentences>", "new_content": "<complete new file content>"}}"""
    r = post(f"{BASE}/chat/completions",
             {"model": MODEL, "temperature": 0, "messages": [{"role": "user", "content": prompt}]},
             {"Authorization": f"Bearer {os.environ['NEBIUS_API_KEY']}"})
    text = r["choices"][0]["message"]["content"] or ""
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


def safe_path(repo, path):
    """The log is attacker-influenced: only ever touch tracked files inside the repo (never .git/.github)."""
    root = os.path.realpath(repo)
    real = os.path.realpath(path if os.path.isabs(path) else os.path.join(repo, path))
    rel = os.path.relpath(real, root)
    if os.path.commonpath([real, root]) != root or rel.split(os.sep)[0] in (".git", ".github"):
        sys.exit(f"refusing path outside the repo or under .git/.github: {path}")
    if sh("git", "ls-files", "--error-unmatch", rel, cwd=repo).returncode:
        sys.exit(f"refusing file not tracked by git: {rel}")
    return rel


def run(repo, logfile, test=None, pr=False):
    log = open(logfile).read()
    path, line, error = parse_log(log)
    if not path:
        sys.exit(f"no project stack frame in log; error: {error}")
    path = safe_path(repo, path)
    blame = sh("git", "blame", "-L", f"{line},{line}", "--porcelain", path, cwd=repo).stdout.split()
    sha = blame[0][:8] if blame else "unknown"
    culprit = sh("git", "show", "-s", "--format=%h %an: %s", sha, cwd=repo).stdout.strip()
    print(f"[1] failure   {error}\n[2] location  {path}:{line}\n[3] suspect   {culprit}")

    source = open(os.path.join(repo, path)).read()
    fix = ask_model(error, path, source, culprit, docs_lookup(error))
    print(f"[4] nemotron  {fix['explanation']}")

    branch = f"fix/{sha}"
    sh("git", "checkout", "-b", branch, cwd=repo)
    open(os.path.join(repo, path), "w").write(fix["new_content"].rstrip("\n") + "\n")
    if test:  # verify before we claim a fix; model-written code runs here, so keep our secrets out of its env
        env = {k: v for k, v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET|PASSWORD", k, re.I)}
        ok = subprocess.run(shlex.split(test), cwd=repo, env=env, capture_output=True).returncode == 0
        print(f"[5] verify    {'tests pass' if ok else 'tests STILL FAIL - reverting'}")
        if not ok:
            sh("git", "checkout", "-", cwd=repo)
            sh("git", "branch", "-D", branch, cwd=repo)
            sys.exit(1)
    sh("git", "commit", "-am", f"fix: {error[:60]}\n\nRegression from {culprit}.\n{fix['explanation']}", cwd=repo)
    print(sh("git", "show", "--stat", "--patch", "HEAD", cwd=repo).stdout)
    if pr:  # ponytail: assumes gh is authed and a remote exists
        sh("git", "push", "-u", "origin", branch, cwd=repo)
        print(sh("gh", "pr", "create", "--fill", cwd=repo).stdout)


def selftest():
    py = 'Traceback (most recent call last):\n  File "/r/app.py", line 7, in <module>\n    main()\n  File "/r/calc.py", line 3, in avg\n    return t / n\nZeroDivisionError: division by zero\n'
    assert parse_log(py) == ("/r/calc.py", 3, "ZeroDivisionError: division by zero"), parse_log(py)
    js = "TypeError: x is undefined\n    at run (/srv/app/src/job.js:42:9)\n    at node_modules/foo/index.js:1:1"
    assert parse_log(js)[:2] == ("/srv/app/src/job.js", 42)
    node = "/r/user.js:2\n  return u.profile.name;\n\nTypeError: Cannot read properties of undefined (reading 'name')\n    at displayName (/r/user.js:2:19)\n    at Object.<anonymous> (/r/test.js:3:13)\n"
    assert parse_log(node)[:2] == ("/r/user.js", 2), parse_log(node)
    gh = 'test\tRun\t2026-10-29T06:00:00Z Traceback (most recent call last):\ntest\tRun\t2026-10-29T06:00:00Z   File "/home/runner/work/ifa/ifa/calc.py", line 2, in average\ntest\tRun\t2026-10-29T06:00:00Z ZeroDivisionError: division by zero\n'
    assert parse_log(gh) == ("/home/runner/work/ifa/ifa/calc.py", 2, "ZeroDivisionError: division by zero"), parse_log(gh)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sh("git", "init", "-q", cwd=d)
        open(f"{d}/a.py", "w").close(); open(f"{d}/untracked.py", "w").close()
        os.makedirs(f"{d}/.github"); open(f"{d}/.github/w.yml", "w").close()
        sh("git", "add", "a.py", ".github/w.yml", cwd=d)
        assert safe_path(d, f"{d}/a.py") == "a.py"
        for bad in ("../../etc/passwd", "/etc/passwd", "untracked.py", ".github/w.yml", ".git/config"):
            try:
                safe_path(d, bad); raise AssertionError(f"accepted {bad}")
            except SystemExit:
                pass
    print("selftest ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--selftest"]:
        selftest()
    else:
        run(a[0], a[1], a[a.index("--test") + 1] if "--test" in a else None, "--pr" in a)

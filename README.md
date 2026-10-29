# Incident-to-Fix Agent

> A failing build goes in. A verified fix, with the commit that caused it, comes out.

Built for the **Nebius x NVIDIA Global AI Hackathon**, track: Coding & Agentic Engineering.

When CI breaks, an engineer reads the log, finds the file, works out which commit caused it, searches for the error, writes a fix and re-runs the tests. Most of that is mechanical. This agent does it.

## How it works

```
CI log ──► 1 parse ──► 2 git blame ──► 3 Tavily docs ──► 4 Nemotron ──► 5 run tests ──► 6 commit / PR
           file+line    culprit commit   (optional)       proposes fix    pass? keep      fix/<sha> branch
                                                                          fail? revert
```

1. **Parse** the log for the innermost project stack frame and the error (Python, JS/TS, Go, Ruby, Java). Python's innermost frame is last, JavaScript's is first; both are handled.
2. **Blame** the failing line with `git blame` to find the commit that introduced it.
3. **Research** (optional): if `TAVILY_API_KEY` is set, search Tavily for the exact error.
4. **Reason**: send the error, culprit commit, file and docs to an NVIDIA Nemotron model on **Nebius Token Factory**. The model returns an explanation and the corrected file.
5. **Verify**: apply the change on a `fix/<sha>` branch and run your test command. If the tests still fail, the agent reverts and exits non-zero. It never claims a fix it hasn't verified.
6. **Deliver**: commit with a message that names the regression commit. With `--pr`, push and open a pull request.

## Nebius and NVIDIA usage

- Inference runs through **Nebius Token Factory**'s OpenAI-compatible chat completions API.
- The model is an **NVIDIA open-source Nemotron model**, chosen with `NEBIUS_MODEL`.
- **Tavily** supplies live documentation lookup.

## Quick start

Requires Python 3.9+ and git. No packages to install; the agent uses only the standard library. The JS demo also needs Node.

```bash
export NEBIUS_API_KEY=...        # Nebius Token Factory key
export NEBIUS_MODEL=...          # exact NVIDIA Nemotron model ID from the Nebius model list
export TAVILY_API_KEY=...        # optional

python3 agent.py --selftest      # offline check of log parsing
```

### Demo 1: Python

A commit titled "perf: simplify average()" removed the empty-list guard, so the tests fail with `ZeroDivisionError`.

```bash
sh demo/make_demo.sh
python3 agent.py demo/repo demo/ci.log --test 'python3 test_calc.py'
```

### Demo 2: JavaScript

A commit titled "refactor: simplify displayName()" removed a null guard, so Node throws `TypeError: Cannot read properties of undefined`.

```bash
sh demo/make_demo_js.sh
python3 agent.py demo/repo-js demo/ci-js.log --test 'node test.js'
```

Example output:

```
[1] failure   TypeError: Cannot read properties of undefined (reading 'name')
[2] location  user.js:2
[3] suspect   c244c96 Dev: refactor: simplify displayName()
[4] nemotron  ...Optional chaining safely returns undefined for missing properties...
[5] verify    tests pass
```

### Use it on your own repo

```bash
python3 agent.py /path/to/repo ci-failure.log --test 'npm test' [--pr]
```

`--pr` pushes the branch and opens a pull request with the `gh` CLI, which must be installed and authenticated.

## GitHub Action: fix failed builds automatically

`.github/workflows/incident-to-fix.yml` runs when your workflow named `CI` fails. It downloads the failed log, runs the agent on the failing commit, and opens a PR if the tests pass.

Setup in your repo (Settings):

1. **Secrets and variables > Actions > Secrets:** add `NEBIUS_API_KEY` (and optionally `TAVILY_API_KEY`).
2. **Variables:** add `TEST_CMD` (for example `npm test`) and `NEBIUS_MODEL`. The job fails if `TEST_CMD` is empty, so it can never commit an unverified fix.
3. **Actions > General > Workflow permissions:** enable "Allow GitHub Actions to create and approve pull requests".
4. Copy `agent.py` and the workflow file into the repo, and rename `"CI"` in the workflow to match your pipeline.

Safety: it only reacts to failures from branches in the same repository (never forks, which must not see your secrets), and ignores `fix/*` branches so it can't loop.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `NEBIUS_API_KEY` | API key (required) | none |
| `NEBIUS_BASE_URL` | OpenAI-compatible endpoint | `https://api.tokenfactory.nebius.com/v1` |
| `NEBIUS_MODEL` | Model ID | an NVIDIA Nemotron ID; set this to a name from your model list |
| `TAVILY_API_KEY` | Enables documentation lookup | off |

## Limitations

- The model rewrites the whole file instead of producing a diff. This is reliable for small and medium files; large files would need diff-based patching.
- One failure per run. The test command is run without a shell, so use a single command rather than `a && b`.
- The test command decides what counts as fixed. A weak test suite can accept a weak fix, so review the commit before merging.
- Log parsing is regex based and covers common stack-trace formats only.

## Roadmap

- GitHub Action that runs on failed workflow runs and comments the proposed fix on the PR.
- Diff-based patching and multi-file fixes.
- Confidence score and flaky-test detection before attempting a fix.

## Project layout

```
agent.py              the whole agent (~100 lines, standard library only)
demo/make_demo.sh     Python regression demo
demo/make_demo_js.sh  JavaScript regression demo
make_doc.py           generates the Word submission write-up
```

## Security

Never commit API keys. Keep them in environment variables or in a git-ignored file (`resource/` is ignored here).

# api-semantinc-linting

A GitHub Action that runs the [`openapi-semantic-review`](https://github.com/apiglue/claude-marketplace-api-governance) Claude skill against every OpenAPI specification changed in a pull request, and **blocks the merge while semantic errors remain**.

- Only runs when the PR actually changes an OpenAPI document — other PRs pass instantly.
- Errors (`SEM-001`…`SEM-006`) block. Warnings (`SEM-007`…`SEM-014`) are advisory and reported but do not block, unless you opt in.
- Posts a single sticky comment with the findings table, updated on every push.
- Uploads the skill's corrected `-semantically-linted` copy of each spec as a run artifact.

## Usage

```yaml
name: OpenAPI semantic lint gate

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    paths: ["**.yaml", "**.yml", "**.json"]

concurrency:
  group: openapi-semantic-lint-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  semantic-lint:
    name: Semantic lint
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: apiglue/api-semantinc-linting@v1
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Making it a merge gate

1. Add an `ANTHROPIC_API_KEY` secret to the repository (or the organization).
2. Merge the workflow above into your default branch so at least one run exists.
3. **Settings → Branches → Branch protection rule** for your default branch → *Require status checks to pass before merging* → select **`Semantic lint`** (the job's `name`).

With that check required, a pull request cannot be merged until the semantic review reports zero errors.

## Inputs

| Input | Default | Description |
|---|---|---|
| `anthropic-api-key` | — | **Required.** API key used to run the skill. |
| `github-token` | `${{ github.token }}` | Reads the PR diff and posts the findings comment. |
| `spec-extensions` | `yaml,yml,json` | Extensions considered candidate specifications. |
| `spec-paths` | `""` | Newline-separated explicit paths. Set this to bypass change detection (e.g. to review a fixed set of specs on a schedule). |
| `spec-directory` | `""` | Only review changed specs under this directory (e.g. `apis`). Empty reviews the whole repository. |
| `fail-on` | `errors` | `errors`, or `errors+warnings` for a stricter gate. |
| `comment` | `true` | Post/update the sticky PR comment. |
| `upload-artifact` | `true` | Upload the report and corrected spec copies. |
| `model` | `claude-sonnet-5` | Model used for the review. |
| `plugin-marketplace` | `https://github.com/apiglue/claude-marketplace-api-governance.git` | Marketplace git URL installed into the run. |
| `plugin` | `api-ai-toolkit@apiglue-api-governance` | Plugin installed from that marketplace. |
| `skill` | `api-ai-toolkit:openapi-semantic-review` | Skill invoked once per specification. |

The marketplace is installed from its default branch — the action has no ref-pinning input. If you need the gate's rules frozen against upstream edits, point `plugin-marketplace` at a fork or a release branch you control.

## Outputs

| Output | Description |
|---|---|
| `specs` | Newline-separated list of reviewed specification files. |
| `error-count` | Total SEM errors across all reviewed specifications. |
| `warning-count` | Total SEM warnings. |
| `passed` | `true` when the gate passed, including when no specification changed. |

## How a spec is detected

A changed file is reviewed when both hold:

1. Its extension is in `spec-extensions`.
2. Its content declares an `openapi` / `swagger` key — as an unindented YAML key, or as a JSON member anywhere on the line (so minified JSON specs are caught too). A nested `swagger:` property inside some unrelated YAML does not match.

Deleted files are ignored. When nothing matches, the job succeeds without calling the model — so the check can be required on every pull request without slowing unrelated work down.

## What runs inside

1. `claude-code-action` installs the `apiglue-api-governance` marketplace and the `api-ai-toolkit` plugin into the run, so the plugin's skills and its bundled Spectral ruleset resolve natively.
2. `api-ai-toolkit:openapi-semantic-review` runs per spec. Its first step is `openapi-spectral-fix`, which produces a `-fixed-ruleset` copy; the gate answers **No** to that skill's "fix warnings too?" prompt.
3. The semantic catalog (`SEM-001`…`SEM-014`) is evaluated against the fixed copy, and a `-semantically-linted` copy is written with the error-level fixes applied.
4. Findings are emitted as `.semantic-review/result.json`, which the workflow parses to decide the verdict.

Nothing is committed or pushed — your specification files are never modified in place. The corrected copies live only in the run artifact.

The gate also fails if the review cannot complete (invalid spec, Spectral unavailable, no result file). A gate that cannot judge a spec never reports green.

## Local example

This repository's own workflow lints the specifications under `apis/` with both jobs. `apis/openapi-semantic-traps.json` passes every structural lint rule while violating many semantic rules, so editing it in a pull request exercises both gates end to end with a red run.

## Jev variant

`jev/` is a second action that scores the same `SEM-001`…`SEM-014` catalog with TypeSafe's Jev model instead of Claude. It sends one request per changed spec, with the spec as `state` and the 14 two-level Score questions from `jev/questions.json`. `jev/semantic_score.py` then combines the answers into a weighted compliance score and fails the job when an error rule fires.

```yaml
      - uses: apiglue/api-semantinc-linting/jev@v1
        with:
          typesafe-api-key: ${{ secrets.TYPESAFE_API_KEY }}
          spec-directory: apis   # optional
```

## Comparison

Both gates on [`apis/openapi-semantic-traps.json`](apis/openapi-semantic-traps.json) in [PR #2](https://github.com/apiglue/api-semantic-linting/pull/2):

| | Semantic lint (Claude) | Semantic lint (Jev) |
|---|---|---|
| Result | ❌ Blocked | ❌ Blocked |
| Time shown in comment | 4m 34s | 0m 02s |
| Whole job, per GitHub | 4m 42s | 11s |
| Rules fired | 13 | the same 13 |
| Table rows | 20, one per location | 13, one per rule |

- **Same verdict on every rule.** Both flagged `SEM-001`…`SEM-011`, `SEM-013` and `SEM-014`, and both passed `SEM-012`. Jev's probabilities were all between 0.90 and 1.00; the lowest were `SEM-013` (0.90), `SEM-011` (0.91) and `SEM-005` (0.93).
- **Jev is about 140× faster.** It makes one API call per spec, and TypeSafe charges for input tokens only.
- **Claude gives exact locations** (`GET /getContactList`, `totalAmount`), recommendations written for each finding, and a corrected copy of the spec. Jev only says which rules fired.
- **`SEM-007` severity is inconsistent.** The skill marks it as an error, which is how Jev counts it. The Claude gate's prompt treats only `SEM-001`…`SEM-006` as errors, so its comment header showed "9 error(s), 11 warning(s)" while its footer showed "11 · 9".

# Timeblock ChatGPT -> Codex Planner/Executor Standard v1.3.2

Status: **OWNER-APPROVED SINGLE CANONICAL WORKFLOW**
Decision date: **2026-09-05**
Workflow version: **1.3.2**

This file is the single highest-precedence workflow for normal Timeblock and AI-COMMUNICATION-Timeblock engineering tasks.

## 0. Precedence and legacy block

Execution precedence is:

1. `AGENTS.md`
2. this file: `docs/engineering/CHATGPT_CODEX_PLANNER_EXECUTOR_STANDARD.md`
3. repository-specific ownership/security/release contracts explicitly referenced by the task spec
4. `docs/qa/<TASK_ID>.md`
5. relevant current source/tests

No v1.1, v1.2, v1.3, v1.3.1, historical direct-main, long-lived-thread, Timeblock Dev AI, Qwen/OpenCode, or old model-routing workflow may be used to plan or execute a normal task when it conflicts with v1.3.2. See `docs/engineering/LEGACY_WORKFLOW_BLOCKLIST.md`.

If any old file, Git-history revision, prompt, memory, PR comment, or archived skill conflicts with v1.3.2, ignore the old workflow instruction. Product/security/ownership facts remain valid only when the current repository explicitly declares them current.

## 1. Canonical architecture

```text
OWNER TASK / QA EVIDENCE
-> ChatGPT GPT-5.6 Sol Deep / Extra High Planner
-> resolve exact current lineage first
-> inspect only authoritative current evidence/source
-> write docs/qa/<TASK_ID>.md
-> docs-only PLAN_SHA on the approved task lineage
-> fresh Codex GPT-5.6 Sol High executor by default
-> implement approved scope end-to-end
-> write/update test source
-> static completeness review
-> freeze exact candidate commit
-> ONE final local QA gate against that exact candidate
-> FINAL_LOCAL_QA=PASS
-> RELEASE HANDOFF FAST PATH
-> push exact tested candidate / update PR
-> CANDIDATE_SHA == TESTED_COMMIT_SHA == REMOTE_PR_HEAD_SHA == DEPLOY_TEST_SHA
-> STOP
-> owner manually deploys DEPLOY_TEST_SHA
-> owner manual QA
   -> PASS: verify SHA/head/main drift, merge normally, report main SHA
   -> FAIL: collect evidence, create R(n+1), new PLAN_SHA, fresh executor
```

Release handoff is a mechanical Git publishing step, not a second engineering/research phase.

## 2. Fixed roles and models

Default Planner / Architect:

```text
ChatGPT GPT-5.6 Sol Deep / Extra High
```

Default Executor:

```text
Fresh Codex GPT-5.6 Sol High
```

Bounded escalation specialist only:

```text
Fresh GPT-6 Astra High
```

Astra is not the default long-running executor. Luna/Terra or another cheaper model may be used only when the Planner explicitly records that downgrade in the current task spec for a mechanical, low-risk task. Old score tables never auto-route a task.

One task tree has one active write executor. One file has one active write owner.

If Codex quota changes before final QA, preserve the same branch/SHA/task lineage with a compact handoff; do not rediscover the project from scratch. ChatGPT Sol Deep may act as fallback executor if the owner chooses.

If executor quota ends after `FINAL_LOCAL_QA=PASS`, do **not** start another full engineering executor. Use `TASK_MODE=RELEASE_HANDOFF` and pass only the compact release handoff capsule defined below.

## 3. Lineage-first planning gate

Before creating or updating a task spec, the Planner must establish:

```text
REPOSITORY=
CURRENT_MAIN_SHA=
OWNER_DEPLOYED_SHA=
ACTIVE_PR=
ACTIVE_PR_HEAD_SHA=
APPROVED_STARTING_SHA=
LINEAGE_RELATION=
```

Rules:

- Do not assume `main` is the correct starting point.
- If owner-deployed/live or active-PR lineage is newer than, ahead of, or diverged from `main`, inspect ancestry and use the exact owner-approved continuation lineage.
- Never create a docs-only `PLAN_SHA` from stale `main` when doing so would drop migrations, runtime fixes, or tested code already present in the active lineage.
- For cross-repository work, record both exact starting SHAs.

## 4. Git is the task source of truth

Important task specs belong under:

```text
docs/qa/TB-<SUBSYSTEM>-<YYYYMMDD>-<NNN>.md
```

Corrective revisions use `-R1`, `-R2`, etc.

A task spec should contain as applicable:

- exact repository/branch/PR/start SHA;
- owner evidence and confirmed PASS/FAIL items;
- product decisions and architecture invariants;
- exact task-specific ownership/boundary document paths;
- exact task-specific release/runtime document paths when needed;
- files to inspect/change;
- protected files/contracts;
- implementation scope and out-of-scope;
- acceptance criteria;
- focused final-QA matrix;
- required plugins/tools and permission scope;
- final report schema.

Do not put secrets, huge raw logs, full conversations, or unrelated history in task specs.

## 5. PLAN_SHA contract

The Planner commits only planning/task documentation to the exact approved task lineage and reports:

```text
PLAN_SHA=<40-char SHA>
```

`PLAN_SHA` identifies the exact task-spec revision. It is not the later deploy candidate.

If the branch moves after `PLAN_SHA`, the executor must verify ancestry and confirm the new head does not invalidate the task spec before continuing.

The in-flight workflow-upgrade exception in section 9E is the only normal case where an already-running pre-upgrade task may complete without fabricating a retroactive `PLAN_SHA`.

## 6. Short executor prompts

### 6.1 Engineering executor

Prefer a short prompt that names:

```text
Repository:
PR:
Branch:
EXACT STARTING SHA: <PLAN_SHA or approved continuation SHA>
TASK SPEC: docs/qa/<TASK_ID>.md
```

Then instruct the executor:

1. read `AGENTS.md`;
2. read this v1.3.2 standard;
3. read only the exact ownership/security/release docs declared by the task spec;
4. read the task spec;
5. inspect only relevant current source/tests;
6. do not redo Planner research or historical PR archaeology;
7. implement the full approved scope;
8. do not execute QA between implementation phases;
9. freeze candidate before final QA;
10. run one final gate against the exact frozen candidate;
11. on PASS, enter Release Handoff Fast Path;
12. push the same tested commit;
13. report exact `DEPLOY_TEST_SHA` and STOP;
14. do not deploy or merge before owner QA PASS unless the owner explicitly authorizes that specific deployment action.

### 6.2 Release handoff capsule

When `FINAL_LOCAL_QA=PASS`, a fresh executor/thread must not reload the engineering context. Use only:

```text
TASK_MODE=RELEASE_HANDOFF
REPOSITORY=
BRANCH=
PR=
CANDIDATE_SHA=
TESTED_COMMIT_SHA=
EXPECTED_REMOTE_HEAD=
FINAL_LOCAL_QA=PASS
ACTION=PUSH_EXACT_CANDIDATE_AND_REPORT_SHA
```

The release-handoff executor must not re-read broad source/tests, redo research, rerun QA solely due to untracked artifacts, or perform unrelated cleanup.

## 7. Plugin/tool discipline

Use least privilege. The Planner records:

```text
REQUIRED_PLUGINS=
OPTIONAL_PLUGINS=
PLUGIN_NOT_REQUIRED=
PLUGIN_PERMISSION_SCOPE=
```

Typical routing:

- GitHub: repository, branch, PR, diff, SHA, merge lineage.
- Render: only when live deploy/log/env/runtime evidence is material; no automatic deploy unless owner explicitly commands it.
- OpenAI Developers: only for OpenAI API/realtime/Agents/Apps integration work.
- Supabase/database tooling: only when that actual database is in scope.
- Drive/Slack: only when they contain authoritative task evidence.
- Local Playwright/Chromium: deterministic UI verification in the final QA phase.
- Cloudflare: approved CLI/API/browser/manual evidence; do not invent a plugin.

A newly required external permission triggers re-planning rather than silent permission expansion.

## 8. Phase discipline

```text
PHASE 0 — resolve exact lineage if needed; NO QA
PHASE 1 — inspect relevant source/contracts/tests; NO QA
PHASE 2 — implement all production changes; NO QA
PHASE 3 — write/update regression test source; DO NOT EXECUTE
PHASE 4 — static completeness/protected-boundary review; NO QA
PHASE 5 — create/freeze local candidate commit
PHASE 6 — ONE final local QA gate against exact candidate
PHASE 7 — RELEASE HANDOFF FAST PATH: verify exact tracked tree, fetch, verify remote lineage, push exact candidate, verify PR head
PHASE 8 — report compact exact SHA handoff and STOP
```

Full repository QA is not automatic. Use the smallest complete final gate justified by risk. Hosted GitHub Actions are not an iterative edit/fail/edit substitute for deterministic local final QA.

If final QA fails, fix the defect, create a new candidate commit, and rerun only the affected final gate. Do not reuse a failed candidate's evidence.

If final QA passes and the tracked candidate tree remains unchanged, do not rerun QA during release handoff.

## 9. Candidate SHA contract

Before owner deployment QA:

```text
CANDIDATE_SHA
== TESTED_COMMIT_SHA
== REMOTE_PR_HEAD_SHA
== DEPLOY_TEST_SHA
```

If these differ:

```text
READY_FOR_OWNER_MANUAL_QA=NO
```

After reporting `DEPLOY_TEST_SHA`, no cleanup commit, amend, extra push, deploy, or merge is allowed without creating a new candidate and invalidating prior QA evidence, except for non-Git local artifact cleanup that does not change the tracked candidate tree.

## 9A. Tracked worktree cleanliness

Release handoff requires the **tracked Git tree and index** to be clean. It does not require all local untracked files to be deleted.

Required checks:

```bash
git status --porcelain --untracked-files=no
git diff --exit-code
git diff --cached --exit-code
```

Required invariant:

```text
HEAD == CANDIDATE_SHA == TESTED_COMMIT_SHA
TRACKED_WORKTREE_CLEAN=YES
STAGED_CHANGES=NONE
```

Untracked local files do not block release handoff unless one of these is true:

- they are intended repository source, test, config, migration, task-spec, or required fixture files;
- the current task spec explicitly requires them to be committed;
- there is concrete evidence the candidate is incomplete without them.

Do not use a blanket `git status --short must be EMPTY` rule as a release gate.

## 9B. Release Handoff Fast Path

After an exact frozen candidate has passed final local QA, release handoff is a mechanical Git operation.

When the invariant in 9A holds, Codex performs only:

1. verify branch and exact `HEAD`;
2. verify tracked worktree/index are unchanged;
3. fetch remote;
4. verify expected branch/PR lineage and remote drift;
5. verify normal fast-forward ancestry where applicable;
6. push the exact candidate normally, never force-push;
7. verify the remote PR head;
8. require `CANDIDATE_SHA == TESTED_COMMIT_SHA == REMOTE_PR_HEAD_SHA == DEPLOY_TEST_SHA`;
9. report the compact release handoff;
10. STOP.

During this fast path, do **not**:

- reload broad source/tests or historical PR context;
- redo product research;
- inspect, delete, or reorganize QA artifacts merely to make `git status` visually empty;
- modify `.gitignore` solely for handoff;
- rerun QA when the tracked tested tree is unchanged;
- modify source/tests/docs;
- create cleanup commits;
- amend the candidate;
- force-push or rewrite history;
- deploy Render unless the owner explicitly requests that deployment;
- merge `main` before owner manual QA PASS.

## 9C. QA artifact policy

QA artifacts are evidence, not product source.

Preferred locations:

```text
OS TEMP, for example:
%TEMP%/timeblock-qa/<TASK_ID>/<CANDIDATE_SHA>/

or an already-ignored repository path:
qa-artifacts/<TASK_ID>/<CANDIDATE_SHA>/
```

Tool-generated local directories such as these may remain untracked without blocking release handoff:

```text
.playwright-cli/
output/
qa-artifacts/
temporary screenshots
browser traces
```

They do not invalidate exact-candidate QA when `HEAD`, tracked diff, and staged diff are unchanged.

Do not commit QA output unless the task explicitly defines it as a required versioned fixture/artifact.

## 9D. Compact release report

The normal release-handoff report should be short:

```text
STATUS=READY_FOR_OWNER_MANUAL_QA
PR_NUMBER=
BRANCH=
CANDIDATE_SHA=
TESTED_COMMIT_SHA=
REMOTE_PR_HEAD_SHA=
DEPLOY_TEST_SHA=
TRACKED_WORKTREE_CLEAN=YES
FINAL_LOCAL_QA=PASS
RENDER_DEPLOYED=NO
MAIN_MERGED=NO
NEXT_ACTION=OWNER_DEPLOY_DEPLOY_TEST_SHA
```

Detailed test counts and earlier QA evidence belong in the task/QA record. Do not repeat long reports unless the owner asks or a failure requires detail.

## 9E. In-flight workflow upgrade rule

A task that already reached implementation, candidate freeze, or final QA before a newer workflow revision became canonical must not fabricate a retroactive `PLAN_SHA`.

Preserve the exact current lineage and record:

```text
TRANSITION_TASK=YES
PLAN_SHA=N/A_PRE_WORKFLOW_UPGRADE
```

Complete only the remaining candidate/release-handoff steps without rewriting the already-tested lineage.

Any new corrective task created after owner QA FAIL must use the current canonical workflow normally, including a new revision task spec and `PLAN_SHA`.

A workflow upgrade itself should not be injected into an already-frozen product candidate if doing so would change the tested SHA. Publish workflow changes through a separate docs-only lineage/PR unless the candidate is intentionally re-frozen and revalidated.

## 10. Owner QA

Owner deploys exactly `DEPLOY_TEST_SHA` and reports PASS or FAIL with evidence.

Before accepting QA, ChatGPT verifies:

```text
DEPLOYED_SHA == DEPLOY_TEST_SHA
```

PASS path:

- verify PR head still equals QA SHA;
- refetch current main;
- verify merge will preserve the tested tree/contract;
- if safe, merge normally and report final main SHA;
- if integration changes the tested tree, create a new integration candidate and require owner QA again.

FAIL path:

- verify deployed SHA;
- analyze evidence;
- create `TASK_ID-R(n+1)`;
- create a new docs-only `PLAN_SHA` on the correct continuation lineage;
- start a fresh executor thread.

## 11. Default release boundary

Default responsibility split:

```text
CODEX:
push exact tested candidate
verify remote PR head
report DEPLOY_TEST_SHA
STOP

OWNER:
deploy DEPLOY_TEST_SHA to Render
perform manual/device/runtime QA
```

Codex must not inspect or deploy Render during normal release handoff unless the owner explicitly authorizes it for the exact candidate in that turn.

## 12. Cross-repository tasks

When both repositories change, record:

```text
TIMEBLOCK_PLAN_SHA=
GUILUA_PLAN_SHA=
TIMEBLOCK_DEPLOY_TEST_SHA=
GUILUA_DEPLOY_TEST_SHA=
PAIR_TESTED_TOGETHER=YES|NO
```

Keep one active write owner per repository/file boundary. Do not claim a cross-system PASS unless the exact required SHA pair was tested together where the contract requires it.

## 13. Completion definition

A production task is closed only when:

```text
PLAN_COMMITTED=YES|N/A_PRE_WORKFLOW_UPGRADE
CODE_COMPLETE=YES
CANDIDATE_FROZEN=YES
FINAL_LOCAL_QA=PASS
EXACT_SHA_HANDED_OFF=YES
OWNER_DEPLOYED_EXACT_SHA=YES
OWNER_MANUAL_QA=PASS
MERGED_TO_MAIN=YES
TESTED_TREE_PRESERVED=YES
```

## 14. Canonical shorthand

When the owner says:

> Planner -> Spec-in-Git -> Codex Executor -> Owner QA

it means this **v1.3.2** workflow only. Do not load, execute, or revive older workflow versions.

When the owner says:

> Release handoff

it means section 9B only: verify the exact tested candidate, push it, verify remote PR head, report `DEPLOY_TEST_SHA`, and STOP.
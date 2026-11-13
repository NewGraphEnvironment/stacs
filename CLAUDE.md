# stacs

Register a STAC catalogue into pgstac and verify it arrived. Python, uv-managed,
`src/stacs/` layout; consumers install it from git, never PyPI (the PyPI name belongs to an
unrelated archived project).

## Repository Context

**Repository:** NewGraphEnvironment/stacs (public)
**Primary Language:** Python (uv; `uv sync`, `uv run pytest`)

## The boundary

**`stacs` works on a catalogue after its items exist.** Reading a source and building
items belongs to the repository that owns the source. Before adding anything, ask whether
it would be identical for every catalogue; if it knows about one source, it does not
belong here.

**No deployment defaults.** This is a public tool, so the STAC host, database, API URL,
bucket and collection are always parameters from the caller. Never default one to a real
host or bucket, including in tests: fixtures use obviously fake values.

## Hazards carried over from the code's origin

These were each learned in production and are the reason the code is being packaged
rather than copied:

- **Never delete-then-load.** `pgstac.items.collection` is `ON DELETE CASCADE`; dropping
  the collection row destroys every item. Registration is upsert-only.
- **Collection before items**, for the same foreign key.
- **Never verify by count.** Compare id sets in both directions, then compare bodies by
  digest. A `/search` on a list of ids silently omits ids that do not exist, and a
  `/search` with no `limit` returns 10 features.
- **An unread body is an error, never "unchanged".**
- **Secrets through the environment, never argv**, so they do not appear in `ps`.
- **A queryables load can take rows other collections serve.** pypgstac replaces every
  row of the name served on this collection, a global or shared row included. So
  `register` loads queryables last, only for names that differ, and re-reads every other
  collection on every way out after the attempt, failures included: a load can commit
  and still report failure. `research/pgstac_queryables.md` has the source.

## The remote script

`register.remote_script` runs on a host whose shell and env file are the caller's. Two
traps found while porting it, both of which passed a load that never ran:

- On bash 3.2, an expansion error or a failed `.` under an armed `EXIT` trap exits **0**.
  Success is a flag set on the last line and a `STACS_LOADED <n> <kind> <db>` line Python
  requires on stdout -- never the exit status alone.
- `( ... ) || exit 1` suspends `set -e` for everything inside the subshell. The subshell
  that sources the env file runs untested; the parent's `-e` carries its failure.

Change the script only with `tests/test_register.py` running it for real (its ssh stub
executes the script locally against a fake pypgstac).

## Tests

The suite runs offline: the root `conftest.py` refuses every DNS lookup and connection
outside loopback for the whole session. Proxy variables are not enough -- urllib3's
`PoolManager`, which pystac uses for schema fetches, ignores them. A guard added here gets a
mutation check (remove it, watch a test fail); a covered line is not a tested one.

Docstring examples are collected with the tests (`--doctest-modules`, `testpaths` includes
`src`). The guard sits at the root, not in `tests/`, so `pytest src/...` alone is guarded
too; `tests/test_harness.py` pins both.

## The documentation site

`mkdocs.yml` builds the site from `docs/`; the pages pull their prose from `README.md` by
section marker (`<!-- --8<-- [start:home] -->`) and include `NEWS.md` whole, so the README
stays the one source. Keep the markers when editing it (`tests/test_docs.py` checks each
start has its end: snippets runs an unclosed section to the end of the file, and strict
does not notice), and keep a README link absolute or outside the markers: a relative one
resolves against `docs/`, and the strict build fails on it. Raw HTML (`<img>`, `<a>`) is
never checked, so it stays outside the markers, as the logo does. A snippet can include
any file in the repo (`base_path: ["."]`), so `CLAUDE.md`, `planning/` and `research/`
reach the site only if a page or a docstring names them: don't. Never pass `-q` to a
strict build: it hides the warnings strict counts, so a dead link passes.

## Versioning

`pyproject.toml` `version` and `NEWS.md` move together, and a git tag `vX.Y.Z` marks each
release. Consumers pin by tag in `[tool.uv.sources]`. After the bump run `uv lock`: the
lockfile records this package's version and CI runs `uv sync --locked`. `/gh-pr-merge`
cuts the release itself: its gate reads this repo as a Python package and does the bump,
the `## Unreleased` rename, the `uv lock`, the release commit, the tag and the GitHub
release. Don't do it by hand.

<!-- BEGIN SOUL CONVENTIONS — DO NOT EDIT BELOW THIS LINE -->


# Agent Operating Rules

How an agent session works here: clocks and waiting, subagents, evidence, and when to come
back to the user. Worked commands and background, under the same headings, are in
soul's `conventions/reference/agent-operations.md`, which no `CLAUDE.md` loads.

Citations sit in `<!-- evidence -->` blocks, which a repo's `CLAUDE.md` omits; the full text
is in `conventions/agent-operations.md`. A new citation goes in its rule's block, and the
remedy stays in the rule (`code-check.md`'s header; `/compact-prep` step 5).

## 1. You Have No Clock Between Tool Calls

**Every duration claim comes from `date`, never from how much waiting felt like
it happened.**

Background `sleep` returns immediately from the agent's side, and the number of
times you have polled is not evidence of elapsed time. Two consecutive tool
calls can be 15 seconds apart by the clock while feeling like ten minutes of
waiting.

**How to apply:** before saying *any* duration — "still running after N
minutes", "this has been X a while", "longer than usual" — run `date -u` and
subtract a real start time. `gh run list --json createdAt` gives it for CI. If a
claim about slowness would change what the user does next, it needs a measured
number or it does not get made.

The same rule covers process state: `ps` and task-status listings have both been observed
wrong. Check the artifact (an output file's size, its mtime, the service's own API), not the
wrapper, and the file, not a link to it (`ls -lL`; §2, "Don't trust status").

**Measure in UTC; report clock times to the user in Vancouver time, and write those words.**
An ETA or a "finished at" for the user reads `9:22 AM Vancouver time`, not `16:22Z`, and never
the tz abbreviation, which prints `MST` since BC dropped the clock change; add UTC only when the
exact instant matters. Convert with a tool, never by hand, on a host whose tz database knows BC's
change (`TZ=America/Vancouver date +%z` reads `-0700` in winter; `-0800` means a stale one):
`TZ=America/Vancouver date '+%-I:%M %p Vancouver time'`, or the converter in the reference file for a given instant; keep
an input's trailing `Z`, because a time with no offset is read as machine-local. Durations need
no zone. Stored artifacts stay in UTC: commits, logs, filenames, `research/`, PR and issue bodies.

*16 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### The same blind spot picks the wrong waiting tool

Not having a clock also makes a **chain of background sleeps** feel like
waiting when it is not. Pick the instrument by how many answers you need:

| you need | use |
|---|---|
| one notification when a condition becomes true | `Bash(run_in_background)` with an `until` loop that exits, its probe local or the whole loop on the remote host |
| one per state change, ending on its own | `Monitor` with a command that emits and then exits |
| a value you must have before the next step | a **foreground** call, so the blocking is explicit |
| a long job that notifies when it exits | `Bash(run_in_background)` with the command as plain foreground text: no `&`, no `nohup` |

A repeated `sleep N; grep` is right in none of them. **Tell: if you are about to
spawn a second waiter for the same thing, the first one was the wrong shape.**

**An `until` waiter over `ssh` to a Mac exits 0 whatever the remote command did:** gate on
what it prints (`code-check-shell.md`, "Over Tailscale SSH to a Mac, `ssh` exits 0").

**And a waiter's notification is a wrapper's exit too.** Re-read the condition and the job's
own state in a foreground call before reporting it done, against a marker only this run's end
can produce: clear it at launch, or check it is newer than a stamp touched at launch
(`code-check.md`, "A wrapper's exit is not the work"), never a string grepped out of a log.

A `Monitor` filter must also match the failure states, not just the success
one — silence looks identical to "still running", so a watcher that greps only
for the happy path stays quiet through a crash.

**Never end a backgrounded call's command with a trailing `&`.** A trailing `&` (or
`nohup … &`) with nothing in the same command waiting on it, sent with `run_in_background`,
lets the wrapper exit at once, so the notification reports **exit 0** whatever the job
then does. Pick one mechanism from the table, never two.

*20 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Don't edit files a long-running suite is still reading

`devtools::test()` and its equivalents load each test file **when they reach it**,
not at launch, so edits made mid-run are half-applied and the result describes a tree
that never existed. **The tell is a moving denominator:** 3490 passes, then 3496, then
3500, on "the same" tree. `Rscript file.R` parses incrementally too, and there the tell is
a **syntax error quoting a line that does not exist**.

Before a long run, commit. While it runs, do work that touches nothing it reads —
issue bodies, PR text, reading, planning. If an edit cannot wait, kill the run
rather than let it produce a result that has to be re-litigated. And when a long run
fails, get the `file:line` before forming any theory: a mid-flight edit and a real
regression look identical in a summary line.

*9 lines of evidence for this rule are in `conventions/agent-operations.md`.*

## 2. Subagents Are Evidence, Not Dependencies

**Spawn on your own judgment. Don't block on one. Don't trust its status. Verify its claims in both directions.**

### Spawning is your call, not the user's

Deciding to spawn a subagent is an engineering judgment, the same kind as choosing
to write a test or run a grep. **Do not ask permission for it.** The user is usually not
positioned to answer, and under **Always Away** the work stalls until they wake up, for an
answer that was yours to make.

This does not soften `karpathy.md` §1's asks — *"if uncertain, ask"*. Those are about
**what the user wants**: intent, scope, an ambiguous requirement, a tradeoff only they can
weigh. This is about **how you carry it out**. Ask about intent; decide about mechanism.

#### Standing authorization: the harness bars the Agent tool by default on Opus 5

Opus 5 sessions carry a hardcoded CLI instruction, *"Do not call the AgentTool unless the
user requested it"*, which no local setting reaches. **The clause is conditional, so this
convention is the request:** invoking a skill that mandates subagents (`/code-check`'s
rounds, the Plan review in `planning.md`) **is** the user requesting them. Spawn them. This
is a standing user instruction (the owner, 2026-08-29), for the mandated spawns only: the
bounds below hold, and a workflow or deep-research fan-out still needs an explicit ask.

**Spawn without asking** when a skill or convention mandates it, when you want fresh eyes on
your own work, when a sweep will **locate** what matters faster than reading serially (then
read directly whatever you will act on), or when independent items can run concurrently.
**Do it yourself** when one grep answers it, or when the work depends on conversation context
a subagent will not have. If you would sit idle waiting, spawn and keep working, or do it
inline.

**Bounds you enforce yourself, rather than converting into questions:**

- **Two or three concurrent is the working default, and about five per task.** Bound both.
  Past that total, **say so in your next message.**
- **Do not let a subagent fan out again.** `Explore` and `Plan` cannot spawn;
  `general-purpose` can, so put "do not spawn subagents" in its prompt.
- Unnamed, delivering by file — `planning.md` carries the mechanics.
- **Report after, not before.** Say what you spawned, and relay what it found — a subagent's
  report never reaches the user on its own.

*10 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Don't block

Spawn a background subagent, then keep working on the lowest-risk part of the
task — scaffolding, data files, tests. When findings arrive, treat them as a
review of landed work rather than a precondition for starting it. If a result genuinely
must precede the next step, run it synchronously (`run_in_background: false`) so the
blocking is explicit and visible.

*8 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### When your own queue is empty, offer backlog work for the wait

With nothing of the task left while a review or a long run is in flight, offer 2 or 3 queued
pieces (`planning/backlog.md`, `umbrella.sh next`) sized to the wait, in one phone-answerable
question, safest first: read-only, issue work in our repos, a park in its own worktree. None
edits the checkout the run reads. Each class is asked until the answer ledger promotes it (§4).

*3 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Don't trust status

**Never report an agent as stalled, or as still working, on status alone.** A subagent's
`tasks/<id>.output` is a symlink that `ls -l` reports as frozen; `ls -lL` follows it.
Never read the transcript itself, it overflows the context. Even a growing transcript shows
activity, not that a report will arrive. So decide nothing on it; wait for the event,
against a clock:

- **Note the spawn time with `date -u`** (§1) and wait for the completion notification, not a
  file waiter. Until it arrives, the report is "spawned at T, no notification yet", never
  "stalled". Keep working, outside the diff.
- **Deadline:** 60 minutes from the spawn for a `/code-check` round; none for a background
  Plan review, checked against `date -u` at each wake.
- A replacement gets its own findings path, and is a spawn, so it counts toward the bound. The
  original may still deliver: read whichever arrives, both if both do.

**Never record a review as "Clean" on an idle notification.** The reviewer **writes its
findings to a file and reports only the path**; a missing or empty file after the
notification or the deadline means the round is re-run. Spawn reviewers unnamed: a named
spawn idles instead of completing.

*20 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Verify claims, in both directions

Subagent output is evidence, not verdict: acting on a wrong finding and dismissing a late
review wholesale both happen. **Cheap probe first, then act.** Reproduce the claim before
you fix it, and before you dismiss it. A finding you cannot reproduce is a finding you do
not yet understand.

*5 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Fan out inside one process

A workflow that shells out **once per item** costs one permission prompt per item; the same
work **inside one process** costs one prompt total. An unattended run that stops for
approval on item 3 of 200 has gone idle, and the wrapper reports nothing.

- **Prefer one process doing N items over N processes doing one.** Loop inside the
  language runtime; shell out once, for the batch.
- Where a per-item subprocess is genuinely required, allowlist its command **before**
  the run.
- If a run keeps stopping for approval, look at whether the loop sits inside or outside
  the process boundary before adding allowlist entries.

*5 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### A subagent that must not know the answer must be a Plan or Explore type

A `general-purpose` subagent carries the project's `CLAUDE.md`, and `Plan` and `Explore` do not, so a
blind reader, a blind reviewer or any control that must not see prior results is spawned as `Plan` or
`Explore`. Check it rather than trusting the brief: a canary of each type, given no tools and asked only
whether its context mentions the term in question, settles it in seconds. Neither type can write, so take
its output from the transcript by script, not by retyping, and audit the transcript's tool calls for reads
outside what it was given.

*4 lines of evidence for this rule are in `conventions/agent-operations.md`.*

---

## 3. Evidence, Not Impressions

**Measure before you characterise. Presence is not provenance. "Unknowable" is a
claim.**

### Measure before you characterise

When a decision turns on **what something contains**, open it and count. Do not
describe it from its structure, from an issue's claim about it, or from a tag list.
A heading tells you a thing is *present*, never that it is *populated*.

**A measurement carries the time it was taken.** One made earlier in the same session is not
a current one, least of all for anything another session can change underneath it. For
anything git-backed, `git fetch` first: reading a local clone and reporting it as the state of the world is the same error
with a longer fuse. **And before hand-rolling a parser for a probe, check whether the code
already has one**: a bespoke parser silently narrows the population it can see.

**It also carries the artifact it was taken from, so two measurements that contradict are
usually two artifacts rather than one wrong number.** A schema and a migrated database, a
changelog and the code, a freshly built table and the persisted one it writes into: each
answers differently, and a rule written from one is wrong about the other. Name the artifact
each was taken from, and which one the claim is about, before calling either wrong.

**A host that times out from one machine is not blocked until the local link is ruled out**:
ping the gateway and try a second machine.

*23 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### A share is not robust to an unresolved definition until you measure the spread

When a result is expressed as a share, a ratio or a ranking and called "unaffected by
whichever definition proves correct", **compute the statistic under each candidate
definition and report the spread beside it.** If the spread is material against the claim
being made, the definition is a blocker, so schedule it first. A share is invariant to a
filter only when the filter is uncorrelated with the thing being measured.

*20 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Presence is not provenance

When something's **presence** is offered as evidence for **how it got there**, find
the fact that actually discriminates. **Consistency is not support.** Before offering
"X shows Y", ask what else would produce X. If anything would, X is not evidence. When the
user pushes back on an inference, re-derive rather than defend.

*12 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Documents that share an ancestor corroborate nothing

Finding the same claim in three places is not triangulation if one was written from
another. **The tell is agreement with no independent derivation.** Ask of each
restatement: what did its author read? Prose repeats; code does not, so the discriminating
check is almost always to read the thing the prose describes.

- **A search engine's summary is not a source:** fetch the document it names and find the
  sentence, or attribute the claim to the snippet.
- **Derive every number in a release note from the artifact it describes**, not the issue.
- **For "you can tell X by looking at Y", check that Y separates X from not-X.**
- **A carve-out is a number too:** run the check over the population before writing it.
- **Read the code behind a stated quantity or scope before repeating it;** when one instance
  is stale, grep for the sentence, not the file.
- **Treat `every`, `each`, `all N`, `nothing else`, `roughly doubles` and `between X and Y`
  as words to check:** walk the per-member evidence before writing the quantifier. When review
  keeps finding them, list every quantified or inherited claim with a measured verdict
  (`code-check.md`, "A guard's scope, escape hatches, and remedies").

*93 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### "It can only be answered by testing" is a claim with an author

An issue or a colleague saying a question needs a field season, a device or a deploy
is stating a claim, not a property of the problem. Spend the cheap probe first. Then
**bound what the probe closed**: reading a desktop plugin says nothing about the mobile app.
An over-claimed probe is worse than none.

*10 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### A real bug is not necessarily the reported bug

A defect found while investigating a symptom is **evidence, not the answer**. Before
offering it as the cause, check that it produces *exactly* the symptom described,
including the details that sound incidental. Write the reported symptom out and ask whether
the proposed cause produces **all** of it, and say which parts are still unexplained: "this
is a real bug and it may not be your bug" is honest and cheap.

*5 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### An enumeration is not a checklist

A probe listing what exists — subkeys present, columns found, files listed — answers
"what is here", never "what do we want". Before a probe's output becomes work, grep for
each item and ask whether anything consumes it. When it duplicates something already done
another way, name the comparison.

*3 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### A relative descriptor is meaningless without its anchor

"Upstream", "downstream", "above", "below", "before", "after", "parent" — each is
relative to something named **elsewhere in the document**. Resolve the anchor before
drawing any inference from the term; getting it wrong produces a confident and specific
wrong answer. **Where a source describes a sequence — crossings on a stream, releases in a
changelog, stages in a pipeline, commits on a branch — write the order out before
interpreting a single relative term in it.**

*7 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### A safeguard whose mechanism is a human reading a diff is not a control

When a design says "the writes are uncommitted, so the diff is the review", check
whether anyone reads diffs. Here nobody does, so gate on **blast radius** instead: a write
that reaches one repo just happens; a write that reaches every repo (a soul convention) may
be appended to within its budget but edited or removed only through an issue. Where a real check is
needed, make it mechanical — a grep for a contradicting rule, an assertion that nothing
above the `CLAUDE.md` marker moved, a guard that resolves every heading against a base SHA.
The user still wants a short, honest account of what was written: a report, not a review.

*3 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Not finding it is not evidence it does not exist

Before building a fetcher, harvester, backup or sourcing routine, **search the sibling
packages for the verb** — enumerate the org's installed packages and grep their exports
(the command is in the reference file), and list the directory it names where
operational drivers live outside any package. **Then read the README ownership table and the
above-marker `CLAUDE.md` of any package plausibly adjacent — exports understate remit.**

**Tell:** you are about to write something whose name is a verb the ecosystem already does
somewhere. Fetch, sync, harvest, backup, source, register, publish. **A function existing
in two places is worse than it existing in neither**, and **check what the *architecture*
says, not just what exists**: an issue that already assigned the boundary settles it.

*26 lines of evidence for this rule are in `conventions/agent-operations.md`.*

#### The storage version: one store is not the world

A negative result is only ever as wide as the store you looked in. **`aws s3` and `s3cmd`
address different clouds and are invisible to each other**, so enumerate the stores before
searching them, and prefer the job that stages data to whatever a bucket happens to hold.
The same holds for **checkouts**: a local `grep` across the local checkouts answers a question
about this disk. Use `gh api -X GET search/code -f q="org:NewGraphEnvironment <term>"`,
which indexes **default branches only**: a file on a feature branch needs
`gh api repos/<owner>/<repo>/contents/<path>?ref=<branch>`. Its index is not complete even
there, so confirm a negative that matters by cloning and grepping the repos it covers. Each
S3 tool lists only its own provider's buckets; the backup script names the rest.

*17 lines of evidence for this rule are in `conventions/agent-operations.md`.*

#### The temporal version: what you build against may be about to change

**Before a design depends on a peer repo's artifact** (a guard comparing against its files,
an extractor reading its output, automation keyed to its layout), **search the peer repo's
open issues and PRs for work that changes it**, and read the body of each adjacent hit, not
only its title. Unquoted words match anywhere; a quoted phrase must match exactly and misses
rewordings. A full 100 rows of either type means the list was cut: narrow the words.

```bash
for t in issue pr; do gh api -X GET search/issues -f q="repo:NewGraphEnvironment/<peer> is:$t is:open <artifact words>" -f per_page=100 --jq '.items[] | "\(.number) \(.title)"'; done
```

*15 lines of evidence for this rule are in `conventions/agent-operations.md`.*

## 4. Decisions Up Front, Then Run

**Ask at the plan gate. After approval, run to the PR. Before a plan exists, a question wants an answer.**

The first three subsections are one rule on one axis — *when* to come back to the
user — and they are only correct as a set. The rest decide what the user is handed when
you do come back.

### After plan approval, run every phase to the PR

Plan approval is the authorization for every mechanical step after it. Run every
phase, commit atomically per phase, archive the PWF, push, open the PR, and report
**once**, at the end. Do not stop between phases to report progress. **The merge is a
separate instruction** — *to the PR* ends at the open PR, and `/gh-pr-merge` runs when the
user invokes it or the instruction says so.

- **Inside it:** correcting the plan when a review disproves it (reported in the summary),
  unless the correction is itself a fork of the kind below; filing issues, opening PRs and
  editing bodies in NGE repos; pushing the feature branch. Blockers that cannot be resolved
  are filed as issues and named in the final report rather than held open.
- **Not inside it:** posting outside our repos (below), and anything a convention names as
  its own gate — the merge, a change to the machine (`newgraph.md`), a push into an artifact
  a human is testing on (`code-check.md`).

*8 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Before a plan exists, a question wants an answer

The same terseness that means "go" after approval means "answer me" before it. A
turn that ends in a question mark, with no approved plan, gets an answer and a
one-line offer of the work — not the first commit toward it. When the ask is to understand
something, keep it short and concrete; a worked example beats a taxonomy. **The mandate
starts at plan approval.**

**When an answer settles a plan or moves an issue's scope, end with one offer** to write it into
#N's body as `## Plan` / `## Decisions` (a fold names both issues), and edit the body once
agreed: the next session reads the body, not this conversation.

*6 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### What still interrupts, and where it goes

A decision that permanently shapes stored data — a key, an identifier, a schema
choice, a deprecation shim versus a hard rename — is the user's, and it goes to the
**plan gate**, batched, as two or three concrete options with the recommended one
first and the consequence stated, including a word or field an upstream contract lacks. Found mid-run, it is still not the agent's to decide:
ask it the same way — options, recommendation first, phone-answerable — commit, and
continue on the phases that do not depend on it while the answer is outstanding
(`planning.md`, "When Something Keeps Failing" — escalating is not stopping).

In plan mode, collect the "this changes what I build" forks and ask them together before
`ExitPlanMode`. Mechanism is never a question (§2), nor is anything with a conventional
default: pick it, say so, move on.

*4 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Record the owner's answers; promote a class only on the record

A hook (`settings/hooks/answers_log.py`) records each `AskUserQuestion`; record a question
asked in prose with its `--manual` form. `/backlog-sweep` in soul proposes a class with a run
of approvals and no refusal as a standing authorization. The classes this section reserves
(stored data, posting outside our repos, machine changes, merges) are never proposed, and work
under a promoted class is still reported.

*2 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Never post outside our own repos without approval

Never post to a venue outside NGE's own repositories without the user's explicit
approval for that specific post — upstream GitHub issues and PR comments, mailing
lists, forums, third-party trackers. **Drafting is welcome and expected**: write the
comment, show it, wait. The sending needs the word: an upstream comment is published under
our name, indexed at once, and cannot be unpublished.

- Our own repos are unaffected; filing and editing issues there needs no asking.
- **Reading upstream is unrestricted and worth doing.**
- Offer the draft in the reply, and say plainly that nothing has been posted.

*4 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Upstream, we are guests: fork first, offer an issue, disclose AI

We build on other people's work: gratitude and humility in every step that touches it.
Maintainers may read anything we write about their code, so describe what we saw rather than
diagnose their design, offer rather than propose, and leave them every road to lead.

- **Fix on our fork the same day,** one concern per branch from upstream's default branch,
  no planning files and no `#N` in its commits, the draft in a fork issue labelled
  `upstream-draft`. Pin our packages to the fork's integration branch until upstream holds
  every fix on it, their way.
- **Upstream gets a short issue that offers:** thanks, a reprex, the options as we see them,
  and a pull request if it helps. Send one when asked, or first only where outside pull
  requests are routinely merged. One open item per maintainer, timed around their load.
- **About 200 words, no SRED line.** A design change goes in as a question.
- **Say plainly that Claude Code helped,** in a sentence from the `upstream-draft` on, and offer
  an `Assisted-by` reword in the pull request unless the maintainer has already merged a Claude
  co-authored commit (check their log). Where AI-assisted contributions are unwelcome, send no code.
- **Never ping by accident:** in our repos' issues and pull requests an upstream item is
  backticked, never a URL, link or bare `#N` (a fork's reached upstream's once), unless the user
  wants the ping; commit messages name none, even backticked. An edit cannot take a ping
  back. In a fork checkout `gh` targets upstream, so pass `--repo` for our fork.
- **Homework before, notes after:** who contributes, stated policy, AI use, current load,
  response pace, kept in soul's `research/upstream-projects.md`, revised after every reply,
  merge or silence.
- Raise upstream only what would help their other users. If a maintainer would rather not
  hear from us, keep the fork or move on.

*32 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Credit Claude; a session link only on a cloud PR in a private repo

In our repos, commits end with `Co-Authored-By`, PR bodies with "Generated with Claude Code",
and issues carry no Claude line bar an `upstream-draft`'s sentence. A session link has one
home: the PR body a **cloud** session opens in a **private** repo keeps the harness's footer;
commits, local sessions and public repos carry none. The harness's attribution reminder asks
for a `Claude-Session:` trailer and a URL, and defers to a repo's rule: this one.
`attribution.sessionUrl: false` silences it after `/claude-settings-init`; a SessionStart hook
says when it has not run. A cloud session reads no user settings: in a public repo only this
line guards it until a repo-level setting lands. `/gh-pr-merge` step 3b strips a public PR
body's link; trailers in commits stay.

*13 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Auto mode refuses a production write whatever the chat says

Auto mode's classifier can refuse a command as a production write: a live store rewritten,
a deploy, a publish. When it does, approval given in chat does not reach it. On the **first** such refusal, say so once and offer two routes:
the user leaves auto mode for that step (Shift+Tab) and approves the prompt, or runs the
bare command themselves (below). Do not retry, and do not suggest a restart.

It names a **category** ("Production Deploy"), not *earlier conversation content*, so it is
not the secret-read clamp (`newgraph.md`), which needs a restart.

**It classifies the command text, so it also fires on a write the file tools can make
safely.** Where what was refused is an edit to a tracked file rather than the publish
itself, take that route first — Read and Edit, which the denial text offers as a safer
method — and say the classification was wrong. Keep the two routes above for the command
that really does publish.

*23 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Hand the user bare commands

When the user must run a command themselves — an interactive login, a
sudo-needs-TTY operation, anything the Bash tool is blocked from running — give the
**bare command**, in a fenced block, ready to paste. Never prefix it with `!`: here it does
not run, or runs from `$HOME`.

- **Anchor every path**: absolute, or after `cd <repo-root> &&` on the same line.
- Keep it paste-safe, **short enough not to wrap**, and say what the first output line must read (`PUBLISH run`), so a
  dropped flag shows before anything is written.
- **Several commands go on one line.** A multi-line paste can run only its first line, with no
  error: join them with `&&` or a `for` loop over the list, still short enough not to wrap;
  past that, hand one per turn.

**A file under `~/Downloads` may be unreadable by the agent process.** Probe with
`ls ~/Downloads >/dev/null 2>&1 && echo readable || echo blocked`; Desktop and Documents are
granted separately, so probe each. If blocked, ask for one copy into the repo, with absolute
paths. Full Disk Access for the terminal app removes the block.

*13 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Read a name for what it sounds like: the user dictates

Messages often arrive by voice, so names come spelled by sound ("maxxam creek" was Maxan
Creek). Resolve a place name against BC Geographic Names or the Freshwater Atlas before it
lands in an issue, code or a query, and read an odd phrase for the word it sounds like
before asking about it.

### Link every issue and PR you name to the user

When a message to the user names an issue or a PR, make the number a link the user can
click: `[repo#12](https://github.com/<owner>/<repo>/issues/12)`,
`[repo PR #13](https://github.com/<owner>/<repo>/pull/13)`.

- **Say what each one is** in a few words, unless its sentence already does: a list of bare
  links fails this. A `Stop` hook, `settings/hooks/reply_links-check.py`, holds a reply that
  breaks either half; its no-context check is a heuristic, so a reply it misjudges may stand.
- **Cross-repo references carry the repo** (`other#12`): a bare `#N` is a working link to the
  wrong repo, and naming the collision in prose afterwards does not fix it; re-qualify the link.
- Before sending a report with many numbers, spot-check two or three through `gh`: the ones
  typed from memory or whose type you inferred.
- Scope is messages to the user, and PR and issue bodies read from outside the repo; commit
  messages autolink already. An upstream item in our repos' GitHub text is backticked (§4, pings).

*11 lines of evidence for this rule are in `conventions/agent-operations.md`.*

### Surface upstream defects and gaps; do not work around them

When a dependency or an external API misbehaves, or its contract lacks a concept you need,
surface it and ask rather than
coding around it: a workaround hides the defect from whoever could fix it, and most of the
dependencies in question are **first-party**, so a local patch leaves the bug in place for
every other consumer. Same instinct as `newgraph.md`'s "install missing packages, don't
workaround", applied to a *broken* dependency.

**How to apply:** first check an installed package is current (`check_pkg_stale.sh`, then our
package's tag and `main`, a CRAN package's CRAN) and state the versions beside the diagnosis.
Then reproduce it minimally, file an issue in the owning repo with the
repro and the exact lines (a third party's: a fork issue first, above), report it, and carry on if it is not blocking. The rule is
*do not hide it*, not *do not continue*.

**A gap is a change request:** file it with the contract's owner before coining a name, and
bring the choice to the plan gate. Tell: you are explaining why your names are not the contract's.

*16 lines of evidence for this rule are in `conventions/agent-operations.md`.*


# CI Monitoring

When this repo has GitHub Actions workflows, scan recent runs on session start, so a failed deploy, vignette build or citation update does not linger until someone notices.

## On Session Start

A failure counts only while it is the newest run of its workflow on its branch: a later run
on the same branch that passed fixed it, and a branch whose PR has merged or closed is not the
default branch's problem.

```bash
DEF=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name) || DEF=main
gh run list --limit 20 --json databaseId,headBranch,event,workflowName,conclusion,createdAt \
  --jq 'sort_by(.createdAt) | reverse | .[] | [.databaseId, .headBranch, .event, .workflowName, .conclusion, .createdAt] | @tsv' \
| awk -F'\t' -v OFS='\t' '
    { k = $4 "|" $2 }
    !(k in top) { top[k] = $1; topc[k] = $5 }
    $5 == "failure" || $5 == "cancelled" || $5 == "startup_failure" || $5 == "timed_out" || $5 == "action_required" {
      line = $1 " " $4 " on " $2 " (" $3 ") " $5 " " $6
      if (top[k] == $1) print $2, line (($2 == DEF) ? "" : " · BRANCH")
      else if (topc[k] == "success") print $2, line " · fixed by run " top[k]
      else print $2, line " · newest run " top[k] " " (topc[k] == "" ? "in_progress" : topc[k]) (($2 == DEF) ? "" : " · BRANCH")
    }' DEF="$DEF" \
| while IFS=$'\t' read -r b line; do
    case "$line" in
      *" · BRANCH")
        st=$(gh pr list --head "$b" --state all --limit 1 --json state -q '.[0].state // "none"' 2>/dev/null) || st=unknown
        case "$st" in MERGED|CLOSED) echo "${line% · BRANCH} · branch merged" ;; *) echo "${line% · BRANCH} · branch $b, PR $st" ;; esac ;;
      *) echo "$line" ;;
    esac
  done
```

A row with no suffix is a live failure on the default branch; `· fixed by run <id>` and
`· branch merged` are history, listed so the reader can see why nothing is raised. Only a
`success` fixes a failure: a newer run that is still running, was skipped, or died at startup
leaves the failure live, and the row says `· newest run <id> <conclusion>`. A `startup_failure`
(a workflow file pushed broken), a `timed_out` and an `action_required` are failures in their own
right and print as rows. Keep a
`cancelled` row only if its annotations report a timeout ("A timed-out run reads `cancelled`");
say timed out, not failed.

*6 lines of evidence for this rule are in `conventions/ci-monitoring.md`.*

If any live failures since the last visit, surface to the user before starting other work:

> Workflow `<name>` failed `<time>` ago (run `<id>`). Investigate with `gh run view <id> --log-failed`. Fix or proceed with current task?

User decides; do not auto-fix. `/gh-pr-merge` watches a fresh merge's runs; this scan is the backstop for failures nobody watched (web-UI merges, schedules, dispatches).

## A green run does not mean the site is current

CI conclusion and published content are two different facts. Check the second one
directly when it matters — the deploy commit, not the run status:

```bash
git fetch -q origin gh-pages && git log -1 --format='%s' FETCH_HEAD
# "Deploying to gh-pages from @ owner/repo@<sha> 🚀"  <- the last commit that started a run?
```

Compare it with the last commit that started a run, not with the tip: a bot commit and a
housekeeping push tagged `[skip ci]` start none, so a site built from the commit below them
is current when they touch nothing the site publishes.

GitHub can create a workflow run minutes after the push that triggered it, and
out of order with a later push, so a parent commit's run can deploy over its child's with
both runs green and the published site one commit stale.

Things that do **not** fix this, so don't reach for them:

- `cancel-in-progress: true` — cancels an *overlapping* run. In the measured case the
  runs never overlapped (`created == started` on both, second created after first
  finished), so there was nothing to cancel.
- A `concurrency:` group — the r-lib pkgdown template already sets one at the job
  level (`group: pkgdown-${{ github.event_name != 'pull_request' || github.run_id }}`).
  Grepping for a top-level `concurrency:` key misses it and invites a redundant
  "fix". Serializing runs doesn't order events that arrive late.

There is no workflow-side fix, because the reordering happens before the workflow
exists. The remedy is detection: check the deploy provenance, and re-dispatch
(`gh workflow run <file> --ref main`) if it's behind. Harmless when the stale
commit changed nothing the site publishes — confirm via `.Rbuildignore` / `_pkgdown.yml`
rather than assuming.

*5 lines of evidence for this rule are in `conventions/ci-monitoring.md`.*

## Don't push to the default branch between a merge and its CI settling

The r-lib templates set `concurrency` with `cancel-in-progress: true`, so a second push
to `main` cancels the first push's still-running workflows. That is correct behaviour and
it is not the problem; the problem is that a **cancelled** run and a **failed** run look
the same in the status column, so a routine follow-up push turns a green merge into
something the next person has to go read a log about — and the log does not exist.

The routine follow-up is the one that bites, because it is the one nobody counts as a
push: a typo fix, a `.gitignore` line, an untagged `CLAUDE.md` drift sync. `/compact-prep`
step 6 runs `claude_md_drift.sh apply`, which **pushes**. Run by hand after `/gh-pr-merge`,
that lands seconds after the merge; `/gh-pr-merge` step 12, which runs it for you, waits for
step 10's watch to read green first. A housekeeping push carries `[skip ci]`, starts no run and
cancels nothing only where soul's `ci_skip.sh` admits it: every commit touches only
`CLAUDE.md`, `comms/`, `planning/`, `research/` or `.claude/`, in an R package whose shape
it admits. Anywhere else the sync pushes untagged, and this rule holds.

Order them: watch the merge's runs to completion, *then* push anything else.

Where a push has already gone out and cancelled something, `/gh-pr-merge` step 10 has the
reading: `cancelled`/`skipped` is `⊘ superseded` unless its annotation reports a timeout, and the thing to confirm
is that the newest SHA that started a run passed. Do not re-dispatch the cancelled one.

*3 lines of evidence for this rule are in `conventions/ci-monitoring.md`.*

## Don't use `gh run watch` to wait

It polls hard enough to trip GitHub's *secondary* rate limit, which `gh api
/rate_limit` does not report — every primary bucket reads full while calls return
403. Retrying extends it. Poll sparsely with `gh run view <id> --json status,conclusion`,
and prefer `git fetch` over the REST API for anything git can answer.

## A setup failure and a build failure look identical in the status column

`gh pr checks` and the Actions UI report one word per job. A run that died fetching its
own toolchain and a run that died because the code is broken both read `fail`, and only
the second says anything about what you just shipped.

```
Error in download.file(...) : status was 'SSL connect error'
download of package 'pak' failed
Error in loadNamespace(x) : there is no package called 'pak'
```

That is `setup-r-dependencies` failing before the package was ever built. On a release
commit the natural but wrong reading is "the release is broken".

**Read which step failed before drawing a conclusion**, especially on a release commit
where the instinct is to distrust the tag:

```bash
gh run view <id> --log-failed | grep -iE 'error|fatal' | head
```

If it died in dependency setup, rerun once. If it dies the same way again it is the
upstream CDN, and the honest move is to say so and stop — not to keep spending runs on
something no change in the repo can fix.

A job that failed with **no steps** never started, and `--log-failed` answers `log not found`.
Read why from its check run's annotations, `gh api repos/<owner>/<repo>/check-runs/<job id>/annotations
--jq '.[].message'`: a refusal for failed payments or a spending limit is the account owner's to fix, and a
re-run before they fix it is refused the same way.

*6 lines of evidence for this rule are in `conventions/ci-monitoring.md`.*

## A timed-out run reads `cancelled`
Read a `cancelled` run's annotations before calling it superseded: its job ids from `gh run view <id> --json jobs --jq '.jobs[].databaseId'`, then `gh api repos/<o>/<r>/check-runs/<job id>/annotations`. A timeout says "The job has exceeded the maximum execution time", and its `--log-failed` is empty.

*5 lines of evidence for this rule are in `conventions/ci-monitoring.md`.*

## R workflows live in NewGraphEnvironment/flows
Change a runner, timeout or step there and fast-forward `v1`; a workflow marked at its top as its own is changed in its repo. Re-run all jobs: re-run failed reuses the old copy.

## A hung setup step holds the concurrency group for six hours
A run `in_progress` long past its usual duration, with a newer run of it `pending` behind, is a hang: confirm no step moved (`gh run view <id> --json jobs`), then `gh run cancel <id>`; the lasting fix is `timeout-minutes:`. A slow `setup-r-dependencies` may be compiling (`ℹ Building <pkg>`, in the web UI while it runs); sources on `cran.rstudio.com` mean `code-check-r.md`, "pak Behavior".

*9 lines of evidence for this rule are in `conventions/ci-monitoring.md`.*

## A job-level `concurrency` group must vary with the matrix, or the jobs cancel each other

`concurrency` at the **job** level is evaluated **per matrix job**, so a group string that
does not vary with the matrix puts every runner in one group — and with
`cancel-in-progress: true` they cancel each other. At most one platform runs per push,
which is the entire justification for having a matrix.

```yaml
# WRONG: identical for all three entries
concurrency:
  group: check-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

# right
  group: check-${{ github.workflow }}-${{ github.ref }}-${{ matrix.config.os }}
```

`fail-fast: false` does not help — that governs failures, not cancellation.

**It fails in the quiet direction.** A cancelled run reports `cancelled`, not `failure`,
which `/gh-pr-merge` step 10 correctly reads as `⊘ superseded` — so two platforms that
never ran look like two platforms that were superseded by a newer push. Nothing is red and
nothing says the coverage was lost.

The entries above concern cancellation **between pushes**, which is the behaviour you
want. This is cancellation **within one push**, which is never what you want.

*10 lines of evidence for this rule are in `conventions/ci-monitoring.md`.*


## A push `paths:` filter skips an empty commit, and dispatch and schedule run only from the default branch
Before planning to re-run a workflow on a feature branch, check how it is triggered. An empty commit (`git commit --allow-empty`) changes no files, so a `push` trigger with a `paths:` filter skips it, and the skip is silent: no run is created, so nothing reports anything. `workflow_dispatch` only works for a workflow file already on the default branch, and `schedule` only fires from there. So a branch-only workflow is re-run in one of three ways: push trigger with no `paths:` (the branch filter scopes it), `gh run rerun <id>`, or a commit that touches a filtered path.

*1 line of evidence for this rule is in `conventions/ci-monitoring.md`.*

## A commit pushed by the Actions token starts no workflow, so wait on the SHA you pushed
Key a CI waiter on the SHA you pushed, never on the default branch's tip: a bot commit made with `GITHUB_TOKEN` (an `update-citation-cff` auto-commit, a docs regen) lands on top of yours and, by GitHub's design, triggers no workflow run, so a loop waiting for runs on the tip waits forever.

The tip moves seconds after a release push, which is exactly when a waiter is started. The bot commit also needs no check of its own when it only touches a file the site does not publish; confirm the deploy provenance instead (the `gh-pages` subject names the SHA that was built).

*1 line of evidence for this rule is in `conventions/ci-monitoring.md`.*

## A pending run cancelled by a `concurrency` group runs no steps, so its failure alarm never fires
With `cancel-in-progress: false`, GitHub keeps one running and one pending run per group, and a newer run cancels the pending one before its job starts. An `if: failure() || cancelled()` alarm step is part of that job, so it never runs and the displaced run disappears silently. Count on the next scheduled run to pick the work up, or dispatch it by hand. Do not write that the alarm covers it.

*1 line of evidence for this rule is in `conventions/ci-monitoring.md`.*

## A deploy commit on `gh-pages` is not yet a served page
Before telling anyone a Pages URL is live, fetch it and compare the bytes with the source: the deploy commit lands on `gh-pages` before the `pages-build-deployment` run publishes it, and until that run finishes the URL still answers 404.

*1 line of evidence for this rule is in `conventions/ci-monitoring.md`.*

## A Quarto website renders every Markdown file unless `project: render:` lists its pages
Set `render:` in `_quarto.yml` (`["*.qmd", "!comms/"]`, or the site's own pages): with none, a Quarto website renders every `.md` in the repo, `CLAUDE.md` and `comms/` included, so one file Quarto cannot read fails every publish and one it can is published.

*1 line of evidence for this rule is in `conventions/ci-monitoring.md`.*

## `gh run list --commit` needs the full SHA, and `--workflow` cannot name the Pages run
Key a CI waiter on `gh run list --commit "$(git rev-parse <ref>)"` and pick a run by name in `--jq`: a short SHA returns an empty list with exit 0, and `--workflow 'pages build and deployment'` fails, because GitHub's built-in Pages run has no workflow file.

Both fail quietly in a waiter: an empty list reads as "no runs yet", so the loop runs to its cap, and a failed `--workflow` lookup leaves the run id empty.

*1 line of evidence for this rule is in `conventions/ci-monitoring.md`.*

# Code Check — Python
Traps in Python: the interpreter, pytest, the HTTP stack under pystac, and MkDocs.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/code-check-python.md`; read it before writing or reviewing code in its area. `/code-check` loads it in full.*

### A script named after a stdlib module shadows that module when run by path
Name a script so it cannot collide with the standard library (`enum_sites.py`, not `enum.py`): run by path, its directory is first on `sys.path`, so every `import enum` in the process, `re`'s included, gets the script.

### Proxy variables do not take a pystac test offline: block at the socket
To make Python tests network-proof, patch the socket layer to refuse every non-loopback lookup and connection, in `pytest_configure`, and clear the proxy variables with `NO_PROXY=*`.

### A conftest guard covers only the invocations that load it
Put a session-wide guard in the repository's root `conftest.py`, and pin it by behaviour in a child process: pytest loads a conftest only for the paths it is given and their parents, so a guard in `tests/conftest.py` is absent from `pytest src/...`.

### `mkdocs build --strict -q` passes a dead link
Run `mkdocs build --strict` without `-q`, and set all seven `validation:` keys to `warn` in `mkdocs.yml`: `-q` raises the log level past WARNING, strict counts only the warnings it sees, and so it counts nothing.

### `tempfile.mkstemp` then `os.replace` leaves the target at mode 0600
Set the temp file's mode before the rename: the target's own (`os.stat(path).st_mode & 0o7777`) when it exists, `0o666 & ~umask` when it does not.

### A line break inside an f-string's braces parses only on Python 3.12+
Parse or test a script under its declared `requires-python` floor (`uv run --python 3.11 --script …`): PEP 701 (3.12) allows a newline inside an f-string's braces, so code that passes on 3.12 can be a SyntaxError on 3.11.

### Drive LibreOffice over UNO as an `soffice` macro, not with its bundled Python
Put the script in the private profile's `user/Scripts/python/` and start it as a macro, since on macOS LibreOffice's bundled interpreter run directly is killed at once.

### `re.match` with `$` accepts a trailing newline
Validate a whole string with `re.fullmatch()`, and write `[0-9]` for an ASCII digit.

# Code Check — R
Traps in R: the language and base/utils behaviour, package internals (`R CMD build`, `.Rbuildignore`, roxygen, lintr, `data-raw/`, testthat, pak), and the DBI/duckdb/arrow data layer.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/code-check-r.md`; read it before writing or reviewing code in its area. `/code-check` loads it in full.*

### Read-back shape must match write-back shape
A script that reads a file, transforms it, and writes it **back to the same path** is idempotent only if the reader accepts the shape the writer produces.

### Moving prose into a code chunk hides it from tools that scan the document
- Tools that scan an R Markdown document for prose — citation detection, cross-references, spell-check, word counts — skip code chunks.

### `fs::dir_ls(glob = )` matches the FULL path, so a bare filename pattern matches nothing
Give `fs::dir_ls()` an anchored `regexp =`, never a `glob =`: a glob is matched against the whole path, and its `[...]` classes are escaped.

### `glue()` trims common leading whitespace
- `glue::glue()` strips the common indentation of its input, so a template whose output must preserve exact indentation (XML, YAML, Makefiles, Python) comes out subtly wrong — valid-looking, wrongly indented.

### A `glue()` named argument shadows caller variables in the arguments after it
Compute each value before the call and pass the result.

### `f(g(x)) <- v` needs a `g<-`, not an evaluated `g(x)`
- R parses **any** call on the left of `<-` as a replacement function, all the way down.

### A replacement function on an `xml_missing` node is a silent no-op
`xml2::xml_find_first()` returns an `xml_missing` object when nothing matches — not `NULL`, not an error.

### `download.file(quiet = TRUE)` never tells you the HTTP status — read it from `curl`
Read an HTTP status from `curl::curl_fetch_disk()`'s `status_code`, never from `download.file()` messages.

### A URL handed to a reader goes through R's 60 s connection timeout
Download a large remote file to a `tempfile()` with httr2 or curl and read the copy, never `jsonlite::fromJSON(url)`, `readRDS(url(u))` or `read.csv(u)`.

### `on.exit()` at a script's top level never fires
- `on.exit()` registers a handler on the *current frame*.

### A `data-raw/` script must load the source tree, not the installed package
- `requireNamespace("pkg")` succeeds whenever **any** version is installed, so a guard shaped like `if (!requireNamespace("pkg")) pkgload::load_all()` silently runs against the installed one.

### `lintr` also resolves against the installed package, not the source tree
For a `no visible binding` lint on a constant added on this branch, check `exists(name, asNamespace(pkg))` and reinstall before changing code.

### Regenerated binaries churn git even when nothing changed
- Formats that embed a creation timestamp or other run-varying metadata produce a different file on every rebuild.

### Tests that silently do not run
`expect_snapshot()` **skips on CRAN**, and `testthat` treats a non-interactive run as CRAN by default.

### testthat counts an uncaught error under `error`, not `failed`
Count `r$failed > 0 | r$error` over `r <- as.data.frame(testthat::test_file(f))`, never `failed` alone, and count skips from a `ProgressReporter`'s `n_skip`, never from the frame.

### A `skip_if_not()` skips only its own `test_that()` block
Before blaming a failure, or its absence, on a skip, find the `test_that()` block the skip sits in.

### `expect_gt()` and friends take no `info` argument
Passing `info =` to `expect_gt`, `expect_lt`, `expect_gte` or `expect_lte` is an **error**, not a warning.

### pak Behavior
- pak stops on first unresolvable package — all subsequent packages are skipped

### Reproducibility
- Branch pins (`pkg@branch`) are not reproducible — document why used; the fuller pin policy (no suffix by default, never a bare SHA) is under "Two repos pinning the same remote" below

### A duplicate knitr chunk label fails the build, and reading the diff will not find it
Chunk labels must be unique **within a document**.

### `R CMD build` ships every top-level directory not in `.Rbuildignore`
- Internal coordination directories — `comms/`, `research/`, `planning/`, `dev/` — land in the tarball and therefore in the library of anyone installing from GitHub.

### `R CMD build` ships the `.git` FILE when you build from a worktree
A package built from a `git worktree` ships `.git` (a file holding the developer's absolute path), because R excludes only a `.git` directory; list `^\.git$` in `.Rbuildignore`.

### `.Rbuildignore` has no comment syntax — every line is a live regex
`tools:::inRbuildignore` loops over every non-empty line and ORs `grepl()` of it against the file list.

### Base name shadowing in formal args
- Avoid `names`, `length`, `data`, `c`, `t`, `T`, `F`, etc. as formal argument names.

### Cross-function consistency for label/string normalization
- When two functions in the same package both decide whether a string is a "system value" (or any normalized form), they MUST use the same comparison.

### `$` on a list partial-matches, so a longer sibling key answers for a missing one
- `x$foo` on a list returns `x$foo_bar` when `foo` is absent and `foo_bar` is the only key with that prefix.

### A database driver's value is not a base R type — and it fails twice
A column fetched through DBI does not arrive as the base type its SQL type suggests.

### A value compared as `::text` in SQL has PostgreSQL's spelling, not R's
Write native types from R and cast once in SQL.

### arrow dplyr backend: no grouped slice — bridge to duckdb
- arrow's dplyr backend errors on grouped `slice_max`/`slice_min` (`arrow_not_supported("Slicing grouped data")`).

### as.POSIXct on a Date pins UTC midnight; on a character it uses the machine zone
Construct instants explicitly: a `Date` always becomes UTC midnight whatever `tz =` says, and a character with no zone is read in the machine's zone, so pass `tz =` at parse time.

### as.POSIXct on character infers ONE format for the whole vector
- `as.POSIXct(x)` on a character vector picks a single format by finding the first candidate that parses **every** element — and `strptime` **ignores trailing characters**.

### Inserting a helper between a roxygen block and its function rebinds `@export`
- roxygen2 attaches a block to **whatever object follows it**.

### open_dataset(unify_schemas = TRUE) requires aligned types
- Cross-prefix/file schema unification only merges what types allow: `timestamp[us, tz=UTC]` will not merge with naked `timestamp[us]`, `Grade: string` not with `Grade: double`.

### duckdb larger-than-memory dedup: shard the work — settings won't save you
- duckdb's **window operator** (QUALIFY row_number ...) does not spill enough to survive big partitions (OOM'd an 8 GB limit on a ~124M-row input).

### `nzchar(NA)` is TRUE — non-empty checks silently pass NA
- `nzchar(NA)` returns `TRUE`, so the natural "is this cell filled in" test — `all(nzchar(trimws(x)))` — waves through a column full of `NA`.

### A `for` loop that builds `aes()` captures the loop variable lazily
`aes()` quotes its arguments, so `aes(fill = lab[i])` is not evaluated until the plot is drawn — by which time `i` holds its **last** value.

### ggplot2 legends and labels: a key for an unused factor level, and ggrepel labels that must avoid each other
Keep `drop = FALSE` on the scale and give the layer a named `show.legend` that also sets `FALSE` for each other legend.

### `paste()` with a zero-length argument returns length ONE, not zero
`paste0("x", character(0))` is `"x"`, so a key built per element gains one phantom member when the vector is empty; guard the empty case before building keys.

### `strsplit()` drops a trailing empty field, so a trailing separator vanishes
Leading empties survive and trailing ones do not, which is what makes it hard to reason about from memory.

### `identical()` on two reader results tests the reader, not the file
Compare the file itself (`tools::md5sum()`) to show it was not modified, never two reader results.

### Under `R CMD check`, tests run from a temp dir against the INSTALLED package
Two shapes, both green under `devtools::test()` and broken under `R CMD check`, `devtools::check()`, a tarball check, or an installed-tests run — the direction that costs the most time.

### `dbConnect(SQLite(), path)` CREATES the file, so a read has a write side effect
SQLite creates a database on connect.

### CSV whitespace: `trim_ws` and `strip.white` do not do what the name suggests
- `readr::read_csv()` defaults to **`trim_ws = TRUE`** and silently strips leading and trailing whitespace.

### `R CMD check` rejects a filename containing a space
- "checking for portable file names" fails on any file in the built package whose name has a space.

### `sort()` and `order()` collate by `LC_COLLATE`, so a canonical form is locale-dependent
Sort with `method = "radix"` wherever the order builds a canonical string.

### A library call that dispatches on a global option is not a pure function
A function whose *units* or *algorithm* are chosen by a session-wide setting behaves differently depending on what the caller did before reaching your code.

### `identical(-0, 0)` is TRUE in R, and the two still digest differently
A hash over R's serialized bytes — which is what `digest::digest()` takes by default — separates positive and negative zero, even though every value comparison says they are the same.

### Two repos pinning the same remote at different tags is an unsolvable install
`Remotes:` pins are per-repo, but resolution is global.

### `file(open = "wb", encoding = )` does not re-encode on write
The `encoding` argument to `file()` governs how bytes coming *in* are interpreted.

### A scalar helper called from `glue()` or `mutate()` recycles instead of erroring
`glue()` vectorises over its inputs.

### Never name a durable artifact by a hash the library reserves the right to change
`rlang::hash()` carries **no cross-version stability guarantee**, and rlang says so in its own NEWS for 1.3.0:

### `vapply(..., USE.NAMES = FALSE)` strips ALL dimnames, row names included
A named `FUN.VALUE` looks like it guarantees row names on the returned matrix.

### `source()`ing a config into the render environment leaks it into the next render
`source(params$config)` inside an Rmd puts every config value into the environment `render()` evaluates in.

### One very long table cell hangs paged.js, and it presents as a Chrome timeout
A ~600-character free-text field in a `kable` cell wedged `pagedown::chrome_print` indefinitely.

### `stats::aggregate()` has three separate silent behaviours, and each fails in a different direction
All three measured on R 4.5, all three met inside one 800-line script (drift#67).

### `stats::mad()` is already scaled to an SD
Use `stats::mad(x)` itself as the robust standard deviation: its default `constant = 1.4826` already scales it, so multiplying by 1.4826 again inflates the SD by half.

### `deparse(body(f))` excludes formal defaults, so a body scan cannot see a default
A guard that scans function bodies for a forbidden literal is blind to that literal in a **signature**.

### `deparse()` re-encodes non-ASCII, so it answers about itself rather than the file
Scan R source for non-ASCII with `tools:::.check_package_ASCII_code()`, as `R CMD check` does, never through `parse()` and `deparse()`.

### `package_version()` errors on a pre-release version string
`package_version("3.9.0beta1")` raises rather than returning `NA`, so strip a pre-release suffix before asserting a version floor.

### `tryCatch(warning = )` DISCARDS the value the expression produced
A `warning =` handler is not a filter — it replaces the whole expression, so a call that **succeeded** and merely warned returns the handler's value and the result is thrown away.

### Do not abort inside a handler for a warning raised from C++; note it and abort after the call returns
Record a flag in the `withCallingHandlers()` handler, `invokeRestart("muffleWarning")`, and raise once the call has returned.

### `match()` treats NA as a matchable VALUE, so two unknowns join to each other
`match(NA, c("1", NA))` is **2**.

### `expect_message(expr, regexp)` checks only the FIRST condition, so a progress line hides the message under test
testthat 3e captures the first message the expression emits and matches the regexp against **that one**.

### `pak` refuses to install a package that needs no compiler
Install a pure-R package with `R CMD INSTALL <checkout>` when `pak::pak()` reports missing build tools.

### `as.integer("NaN")` is `0`, and `as.integer(NaN)` is `NA`
The string round trip is the bug.

### `expect_false(identical(x, y))` cannot fail when the two are different types
`identical()` is type-strict, so it is already `FALSE` for any pair that differs in storage mode — and an assertion that the defect would make *true* then cannot fire.

### `unlist()` prefixes a `split()` group's name, so reassembling by name silently yields all-NA
Putting per-group results back in input order by naming them looks right and returns nothing:

### `tolerance` in testthat is RELATIVE, so it pins a published figure far more loosely than it looks
`expect_equal(x, 12.529, tolerance = 2e-2)` accepts anything within **two percent** — so a figure published to three decimals survives drifting to `12.629`.

### `cli` reads `{.name}` as a STYLE, not a variable, and a fold can swallow an interpolation
Two ways a `cli` message loses a value.

### `[[` on a named ATOMIC vector with an absent key is an error, not `NULL`
A list returns `NULL` for a missing `[[` key.

### `data.frame()` recycles a scalar against a zero-length column
It does not yield a 0-row frame — it raises, because a length-1 column and a length-0 column cannot be recycled together:

### A dot-prefixed column name can be swallowed by the verb's own formal
`mutate(x, .d = expr)` does not create a column called `.d`.

### `summarise()` and `mutate()` evaluate in order, so a later argument sees the summarised column
Once `frames = sum(frames)` has run, `frames` inside the next argument is that one-row sum, not the group's vector.

### `\<` and `\>` are word boundaries in R's default regex, not escaped `<` and `>`
Leave `<` and `>` unescaped when you build a pattern from data.

### `tempfile()` lives in the session tempdir, so a path printed in an error names a file R is about to delete
R removes its session `tempdir()` on exit, including after `stop()`.

### R's `yaml` returns a mixed int/float sequence as a list, not a numeric vector
Normalise a numeric YAML sequence at load.

### testthat's failure snapshots land in `tests/` and ride in on `git add -A`
testthat 3e writes `tests/testthat/_problems/*.R` and `tests/testthat/testthat-problems.rds` when tests fail.

### Postgres row order is never fixed unless the query fixes it, so a pick, a float sum and a presence check can each depend on it
End every `ORDER BY` on a unique key, order any fetch whose rows are summed, and ask whether a value is loaded with an index walk, not `DISTINCT` or `EXISTS`.

### `sprintf("%g", x)` writes `Inf` and `NA` into SQL as bare words, which Postgres reads as column names
A numeric formatter such as `sprintf("%.10g", x)` has no SQL form for non-finite values.

### Verify a float-formatting fix in its consumer, not through `as.numeric()`
Compare where the literal is parsed, or compare IEEE 754 bytes, never through `as.numeric()`.

### An `information_schema` lookup by the literal table name misses what Postgres resolves
`WHERE table_schema = 's' AND table_name = 'T'` compares the text you passed.

### Rscript reads a script as it runs, so never edit a script while a run of it is in flight
Run a copy of the script for anything long-running, or leave the file alone until the run exits.

### A range total taken as the difference of two large running totals loses the small ranges
Sum a range directly (segment tree, per-range `sum()`, or grouped sums) rather than as `cumsum[hi] - cumsum[lo]` when ranges are small relative to the running total.

### A `pkg::` call in a test passes `devtools::test()` and fails `R CMD check` if `pkg` is undeclared
List every package a test reaches with `::` in `DESCRIPTION`, and run `tools:::.check_packages_used_in_tests` on the source tree before pushing.

### Inside a dplyr verb, a column named like a local variable wins
Inject a local value into a data-masked verb with `!!x` or `.env$x`, never a bare `x`.

### `earthdatalogin`'s search and download calls overwrite the netrc when they find no Earthdata entry
Search NASA's CMR and download with `curl` given the netrc directly, or check `earthdatalogin:::has_edl_netrc()` yourself first.

### A fetcher's test helper must make the network fail, not just mock the reader
When a test mocks a downloader's reader and supplies fixture files, also mock the search and download functions to `stop()` by default, and re-mock them only in the tests that exercise that path.

### testthat 3e `expect_message()` returns the condition, not the expression's value
Assign inside the call, `expect_message(h <- f(x), "msg")`, never `h <- expect_message(f(x), "msg")`.

### `c()` dispatches on its first argument, so `c(NULL, <Date>)` is a plain number
Put a Date first when `c()` combines an optional piece with Dates: `c(NULL, <Date>)` takes the default method and returns a bare day count.

### `bind_rows()` of all-`NULL` is a 0 x 0 tibble, and a typed template must take its types from the rows' source
Bind per-group results under a zero-row template so an all-dropped result keeps its columns.

### `sample.int(prob =)` without replacement is not a probability-proportional draw, so weighting its result again double-counts
Draw a subsample to be design-weighted **uniformly** (`sample.int(n, k)`), or keep every unit.

### `system2(stdout = TRUE)` warns on a non-zero exit instead of raising, so a `tryCatch(error =)` around it never fires
Read the exit status off the result: `st <- attr(out, "status")`, which is `NULL` on success.

### Forked `parallel::mclapply()` workers segfault in `glm.fit` under macOS Accelerate BLAS
Fit models in parallel on socket workers (`parallel::makeCluster()` with `parLapply()`), not forks.

### `clusterApply()` returns `NULL` for no tasks, not an empty list
Guard an empty input before naming or indexing a `clusterApply()` or `clusterApplyLB()` result: given zero tasks both return `NULL`, where `parLapply()` and `lapply()` return `list()`.

### `c(name = x)` keeps `x`'s own name, so a value from a named vector becomes `name.X`
Strip the name before you label it: `c(axis = unname(v[1]))` or `c(axis = v[[1]])`.

### `trace(exit =)` also fires when the function raises, and `returnValue()` then has no value
Give `returnValue()` a default and check its length: `trace(f, exit = quote(rec(returnValue(NULL))))`, then treat anything not length 1 as "no value".

### `Rscript -e` supplies `--args` itself, so adding your own shifts every argument by one
Write `Rscript -e 'expr' a b`, not `Rscript -e 'expr' --args a b`.

### `read.delim()` quotes by default, so a `"` in a field silently swallows rows
Read a TSV you wrote unquoted with `quote = "", na.strings = character(), comment.char = ""`.

### duckdb in R: the query that autoloads `icu` binds unreliably, so `LOAD icu` before it
Run `LOAD icu` on the connection before any query that needs it (`epoch()`, `year()`, a cast to `DATE` on a `TIMESTAMPTZ`), or use a function that needs no extension (`epoch_ms()`).

### duckdb refuses a parent delete in the transaction that deleted its children
Delete rows a foreign key still points at as separate autocommit statements, children first, never inside one `DBI::dbWithTransaction()`.

### `fs::path()` collapses the `//` after a URL scheme, so it cannot build URLs
Join a URL with `paste(base, key, sep = "/")` or `file.path()`, never `fs::path()`.

### R's default curl user-agent fails on canada.ca, and the error names HTTP/2, not the agent
Set a user-agent on every R fetch of a `canada.ca` page, because R's default fails there with an HTTP/2 error that never mentions the agent.

### `climr::downscale()` returns its reference-period row even with `return_refperiod = FALSE`
Keep only the observed series (`DATASET == "<obs_ts_dataset>"`, four-digit `PERIOD`) before averaging climr output over years.

### A `function(...)` mock hides arguments the real callee no longer accepts
Assert a `function(...)` mock's argument names against the real callee's `formals()`.

### `expect_message(regexp = "...$")` never matches, because `message()` appends `"\n"`
The condition message carries the trailing newline, so an end anchor fails and the test reports "did not throw a message" even though the message printed.

### `load_all()` refuses an installed dependency below the `Imports:` floor, so measure old-against-new from a frozen worktree
Run the old-dependency side of a before/after comparison from a `git worktree` of the pre-bump commit, and install the new version only after those runs finish.

### `tryCatch()` nests its handlers, so a `stop()` in one is caught by a later one
Record the condition in the handler (`hit <<- TRUE`) and raise after `tryCatch()` returns.

### `fs::file_move()` onto an existing directory nests the source inside it
Move a directory into place with `base::file.rename()` and check its return value, which is FALSE where the target is a non-empty directory, a symlink or a file.

### `normalizePath()` renames through a symlink and returns a missing path as it was
Make a path absolute with `file.path(normalizePath(dirname(x), mustWork = TRUE), basename(x))`, which keeps its name.

### Base `file.info()` has no inode column, so `file.info(x)$ino` is NULL and any comparison of it passes
Read an inode with `fs::file_info(x)$inode`.

### `cffr::cff_create()` writes a CRAN DOI for any package that shares a name with a CRAN package
Drop the generated DOI (`x$doi <- NULL`) unless it is your own, and supply your own through `keys = list(doi = ...)`.

### A `{python}` chunk needs reticulate even with `eval = FALSE`
Set `python.reticulate = FALSE` on a Python chunk that only displays code, or declare reticulate.

### `readBin(size = 4)` returns NA for exactly 2^31, so it cannot read an unsigned 32-bit field
Sum the bytes as doubles (`sum(as.numeric(raw[i + 1:4]) * 256^(0:3))`) to read a u32 or u64 from a binary header.

### ajv honours keywords beside a `$ref`; Python's jsonschema ignores them
Keep every `$ref` alone in a draft-07 schema tested with jsonvalidate and read by pystac.

### `load_all()` runs every `.R` file at the top of a package's `data/` as a data script
Keep helper and ad hoc scripts out of `data/`, which pkgload treats as package data, so `load_all()` sources any `data/*.R` it finds there.

### `ifelse()` with an all-NA test returns a logical vector, whatever `yes` and `no` are
Resolve NA before an `ifelse()` whose result must keep a type (`blocked <- !is.na(blocked) & blocked`), or use `dplyr::if_else(..., missing = )`.

### `sub()` takes one replacement, not one per element
Paste a per-element suffix on instead (`paste0(sub("]$", "", x), suffix)`): a `replacement` longer than one is used as its first element everywhere, with only a warning.

### `officer::body_replace_all_text()` misses a phrase that spans Word runs
Replace whole paragraphs, not phrases inside them: officer matches within one text run, and Word splits a paragraph into runs wherever formatting or editing history changes.

### Fill an xlsx template through its sheet XML, not openxlsx's `saveWorkbook()`
Write the input cells into the sheet XML with xml2 and re-zip, so only the parts you edit change.

### Copy a live SQLite database with its `-wal`
Keep the pair only if both files' mtime and size held across the copy.

### jsonlite writes an empty name as the element's position
Write a JSON object with an empty key as text, not through `toJSON()`.

# Code Check — Shell
Tool-level traps in bash, sed, git and `gh`, and in the host toolchain those commands depend on.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/code-check-shell.md`; read it before writing or reviewing code in its area. `/code-check` loads it in full.*

### `git diff a..b` compares TIPS; a change on `a` shows up as the branch's
Use three-dot `git diff a...b` for what a branch changed; two-dot compares the tips, so changes that landed on `a` show up as the branch's, inverted.

### git pathspec excludes: use the long form
- `:!path` is short-form magic, and git keeps parsing magic characters after the `!`.

### `sed 1d f1 f2 f3` strips only the FIRST file's header
`sed` treats multiple file arguments as one concatenated stream, so a line-address script applies once across the whole set rather than per file.

### `sed -n '/X/,$d' file` prints nothing at all
`-n` suppresses auto-print, and `d` only deletes — so nothing is ever emitted and the output is empty.

### Reading a file line-by-line drops the last line without a trailing newline
- `while IFS= read -r line; do ...; done < file` skips a final line that has no newline after it.

### Empty arrays under `set -u` on bash 3.2
- macOS still ships bash **3.2**, where `"${ARR[@]}"` on an empty array is an unbound-variable error under `set -u`.

### Quoting
- Variables in double-quoted strings containing single quotes break if value has `'`

### Heredoc precedence in pipelines
- `cmd1 | cmd2 <<EOF` — the heredoc binds to `cmd2` (the rightmost simple command).

### A heredoc whose body contains its own delimiter ends early, and the rest runs as shell
Give an outer heredoc a delimiter its body cannot contain, or run the script from a file.

### Paths
- Hardcoded absolute paths (`/Users/<name>/...`) break for other users

### Diagnose env/PATH problems in the shell that actually runs, not the ambient one
- Get ground truth **before** forming any theory: `env -i HOME=$HOME TERM=$TERM bash -lc 'echo $PATH | tr ":" "\n" | nl'` (swap in `zsh` to check the other side).

### Parallel writers sharing one output file interleave mid-record
- `xargs -P N ... >> shared_file` (or any fan-out where N processes append to the same fd/path) is only safe while each record fits in a single `write()`.

### `mktemp` template needs enough X's, and a failed `mktemp` leaves an empty var
- BSD/macOS `mktemp -d -t <name>` requires the template to contain at least 3 `X`s (`XXXXXX` is the safe default).

### `cmd dir/*` dies on ARG_MAX at scale — and only after the expensive work succeeded
- A glob expands to argv.

### A `curl` in a parallel fan-out needs `--max-time`
- Without it, one hung connection pins a worker slot indefinitely.

### BSD vs GNU sed/grep portability (macOS hits this constantly)
- macOS ships BSD `sed`/`grep`.

### On this Mac `stat` and `date` are GNU, so the same flag letter means something else
Prefer a flavour-free form (`find -newermt`, `python3`), or call the binary by absolute path.

### `&` binds to the whole `&&` list, so assignments never reach the parent
- `cmd1 && VAR=$(...) && nohup prog > "$VAR.log" & disown` backgrounds the **entire list**, not just `nohup`.

### `gh` CLI
- **`gh pr create` resolves branch from CWD, not `--repo`**.

### On a fork, `main` may track upstream by design — comparing it answers nothing
`gh api repos/ORG/REPO/compare/upstream:main...ORG:main` returning `ahead: 0, behind: 0, status: identical` reads as *"this fork has no local work"*.

### A destructive setup and its undo must not share one timeout-able command
Never chain a destructive setup and its undo (`git stash && slow && git stash pop`) in one timeout-able command.

### `git checkout <path>` restores from the index, not from HEAD
After a `git add`, `git checkout <path>` reinstates the broken *staged* copy — so the "fix" reproduces the failure and reads as though the edit was wrong.

### Git plumbing calls whose default answers a different question
Pass the flag that names the question you mean.

### A value validated with one numeric grammar and consumed with another
Normalise a numeric string once (digits only and at most 9 of them, then `x=$((10#$x))`, then a bounded range): `test` reads base 10, `$(( ))` reads a leading zero as octal and wraps past 2^63.

### `wait` with no argument waits for every background job in the shell
Wait on the PIDs you started (`wait "$pid"`), because a bare `wait` also blocks on every other background job in the shell.

### `if ! cmd; then rc=$?` captures the negation, not the command
Inside the branch, `$?` is the status of the `!` compound — which is **0 by construction**, because the negation succeeded.

### A `pgrep -f` waiter matches a waiter's command line, so it never exits
Wait on a PID with `while kill -0 "$PID"; do sleep 30; done`, never on `pgrep -f "job"`, whose pattern matches a waiting loop's command line so it never exits.

### `timeout` is GNU coreutils — a portable deadline
An assertion around something that might hang can only pass or hang, never fail (`code-check.md`, "Restore the bug and prove the guard fires").

### `aws s3 cp` cannot tell a missing key from a missing bucket
Probe `s3api head-bucket` then `head-object`: only a 404 from a reachable bucket means absent, and a 403 is permissions.

### An S3 multipart ETag depends on the uploader's part size, so try every size that gives its part count
Verify an upload by comparing each object's ETag with its file, trying for a multipart ETag every part size that gives its part count.

### A verification command can be shadowed by a shell function or alias
- The shell is initialized from the user's profile, so `diff`, `grep`, `ls`, `cat` and friends may resolve to a wrapper rather than the binary you assume.

### `pwd` keeps typed case; key on `env pwd -P`
Key on `env pwd -P`.

### psql does not interpolate `:'var'` inside a dollar-quoted string, and `\quit N` exits 0
Two traps in the same file type, both of which read perfectly and fail at run time.

### A second `trap … EXIT` replaces the first
`trap` registers **one** handler per signal.

### A `local` statement cannot read a variable it is assigning in the same statement
`local a="$1" lab="$2" m="/tmp/marker_${lab}"` expands `${lab}` **before** `lab` is assigned.

### Inside an `EnterWorktree` session, the Bash tool refuses command text that names git
The harness applies an isolation guard to a session that entered a worktree: *"a worktree-isolated session's git operations must target its own worktree."*

### A `git filter-repo` seed carries the source repo's tags, and a path sed misses the language's path constructor
Two traps from seeding one repo out of another's history (2026-09-02), both silent.

### `git check-ignore -v` prints the matching pattern, and its exit status is not a per-file verdict
`-v` reports the **last matching pattern**, negations included.

### `sips -Z` scales up as well as down
`sips -Z N` resamples so the longest side is N — in **either** direction.

### Assert capabilities, not versions — a tool upgrade can remove one silently
A tool upgrade across the fleet can remove a capability without reporting failure.

### An amd64-only image needs `--platform`, and it works on your machine because it is cached
Pass `--platform` to `docker run` for an amd64-only image.

### Headless Qt in a container needs `QT_QPA_PLATFORM=offscreen`, and without it the run hangs or crashes
Pass `-e QT_QPA_PLATFORM=offscreen` to any `docker run` that starts QGIS or another Qt program with no display.

### `s3cmd ls` given several paths lists only the FIRST, and says nothing
Query one path per `s3cmd ls` call, or `--recursive` on the prefix and `grep`: given several paths it lists only the first, with exit 0.

### `grep -c` prints the count AND exits 1 when it is zero
Write `n=$(grep -c …) || n=0`, never `|| echo 0` inside the substitution.

### A failed `git fetch` leaves the comparison you make next reading stale refs
`git fetch` and the check that follows it are two commands, and nothing links them.

### macOS `/usr/bin/awk` aborts when a regex meets a byte slice that cuts a multibyte character
Test a `substr()` slice with `==`, never with `~`, `match()` or `sub()`.

### macOS `sed` dies on an invalid byte, and GNU sed misparses it
Parse logs with `LC_ALL=C sed`: a regex that scans an invalid UTF-8 byte exits 1 on macOS and misparses silently with GNU sed.

### A variable in a sed replacement is parsed, so its `\` and `&` are not literal
Never interpolate data into the replacement half of `sed "s#…#$var#"`: sed reads `\(` as `(`, and `&` as the whole match, so the line written is not the value held.

### A fetch can fail and still deliver the commit, so when you need an object, test the object
When the goal is a specific commit, resolve its sha first (`git ls-remote`) and test `git cat-file -e "$sha^{commit}"` after the fetch rather than the fetch's exit status.

### A default `GIT_SSH_COMMAND` outranks the machine's own ssh choice
Supply a default ssh command only when `GIT_SSH_COMMAND`, `core.sshCommand` and `GIT_SSH` are all unset.

### `curl -o` without `-L` saves the redirect page as the download
`curl` does not follow redirects unless it is given `-L`, and it exits 0 on a 3xx.

### `conda run` captures its child's output, so a pipe gets nothing
`conda run -n env cmd` buffers the child's stdout and re-emits it, and that re-emission does not reach a pipe.

### `exit` inside a loop condition ends the shell, not the test
Count instead: `while :; do left=0; for i in $ids; do done_yet "$i" || left=$((left+1)); done; [ "$left" -eq 0 ] && break; sleep 90; done`.

### A failed `cd` lets every later command run in the directory you were already in
Write `cd "$D" || exit 1` (or `cd "$D" && …`), never `cd "$D"; …`.

### macOS `/bin/bash` 3.2 quote-matches a heredoc inside `$( )`, so an apostrophe in the body is a syntax error
Pass multi-line text through a file (`--body-file`, `-F`), never a heredoc inside `$( )`, and open each `case` pattern inside `$( )` with `(`.

### A skill's bash blocks run as separate calls, and its `$` + digits are replaced by its arguments
Open every block after the first with guards on what it inherits: re-set its variables, confirm the path is the expected tree, and refuse edits or commits the previous block did not check.

### An apostrophe in a `${VAR:?message}` inside double quotes is an unterminated quote
Keep apostrophes out of the message of a `"${VAR:?…}"` guard.

### An apostrophe in a comment inside a single-quoted program closes the program
Keep apostrophes out of comments inside an `awk '…'`, `sed '…'` or `python3 -c '…'` program in a script: the shell ends the quote at the `'`, whatever the program reads as a comment.

### A `git push` can land and still report failure, so confirm the ref rather than the exit code
After a rejected push, read the remote ref before concluding anything: `git fetch -q origin && git merge-base --is-ancestor HEAD origin/<branch>`.

### Over Tailscale SSH to a Mac, `ssh` exits 0 whatever the remote command returned
Never branch on the exit status of `ssh <mac-host> cmd` when the host serves Tailscale SSH: test what the command prints, or move the loop to the remote side and gate on its output.

### awk `==` compares version strings as numbers, so `1.1` matches `1.10`
Compare a field to a version as strings, `($i "") == (v "")`.

### `gh api` prints an HTTP error's body on stdout and exits 1, ignoring `--jq`
Branch on `gh api`'s exit status before reading its output.

### Put cleanup on the EXIT trap, not RETURN: a shell killed by a signal never runs RETURN
Clean up temp files and worktrees in one EXIT handler that reads globals.

### `git worktree prune` deregisters every missing worktree in the repo, not only yours
Remove only your own registration: `git worktree remove --force "$wt"`, and on failure delete only its admin dir.

### `git push --porcelain` ends with `Done` on a rejection, so `tail -1` names no reason
Take the reason from the `!` row's third tab field, falling back to the last line that is not `Done`: `awk -F'\t' '$1 == "!" { print $3; exit }'`.

### In a Perl replacement, `$1` followed by a digit is a different group
Write `${1}` whenever the text after a backreference starts with a digit: Perl reads `$1281399` as group 1281399, which does not exist, so the replacement is empty and the run exits 0.

### `for x in $(cmd | grep … || true)` hides a failing `cmd`
Assign the command on its own line under `set -e` (`out=$(cmd)`), then filter `out` with `|| true`.

### A sed/awk range can run to EOF
Never pipe a `sed`/`awk` range extract into an interpreter.

### A Python CLI redirected to a log writes nothing until it exits, so the log cannot show progress
Run a long Python command with `PYTHONUNBUFFERED=1` (or `python -u`) when its output goes to a file.

### `aws s3` progress lines end in `\r`, so a line-based count of a saved log reads zero
Translate before counting: `tr '\r' '\n' < log | grep -c '^upload:'`.

### `a && b || c` runs `c` when any step before the `||` fails
Give each setup step its own `|| exit 1` and branch with `if`.

# Code Check Conventions
Structured checklist for reviewing diffs before commit.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/code-check.md`; read it before writing or reviewing code in its area. `/code-check` loads it in full.*

## Mechanisms
Fourteen shapes that keep producing bugs.

### A guard that fails toward pass
A check decides whether to do something consequential — cut a tag, run a migration, report a sweep clean.

### A fixture that cannot reach the failure mode
Hand-picked fixtures test the cases you thought of.

### A proxy is not the property
A condition that stands in for the thing you actually want.

### Verification that reads its own output
A check whose reference was produced by the thing it checks cannot disagree with it.

### A guard's scope, escape hatches, and remedies
Every guard grows the things that silently disable it.

### A fix lands in one of two callers that share a harness
Two entry points over one library, two workflows over one action, two scripts sourcing one shell lib.

### Restore the bug and prove the guard fires
A test that stays green against the code it was written to reject is decoration, and reading it will not tell you.

### A shared working tree, and what generators leave in it
A working tree has one checked-out branch.

### A wrapper's exit is not the work
A wrapper reports its own exit.

### Zero-length, empty, and unset are three different things
`paste0(character(0), "x")` is `"x"` — one phantom row from an empty frame.

### The probe is broken before the world is
When an ad-hoc probe reports that long-shipped code is broken, the prior belongs on the probe.

### Written data outlives the fix
Changing the writer changes nothing already written.

### Serialization loses meaning silently
Set `na=` and `null=` explicitly on every writer, because a serializer's default for no value is usually a valid-looking value (`"NA"`, `{}`, `'None'`) that every schema check accepts.

### One fact derived twice
A count taken from one artifact and the things counted produced from another, with a guard comparing the two.

## Rules that stand alone
General, and not an instance of a mechanism above.

### Do not edit files a long test run is reading
- `devtools::test()` (and most runners) load each test file **when they reach it**, not at launch.

### Test a persistent change through its per-process override first
Try a persistent setting's per-process override before changing the setting.

### Adopting Existing Config
When importing config from one location into a canonical one (legacy `~/.bash_profile` → dotfiles repo, old script's env → repo, another project's `settings.json` → soul):

### Test the cold/create path of idempotent code, not just the warm no-op
- Idempotent provisioning code has a **cold** path that creates and a **warm** path that finds the artifact present and skips.

### Fetch an expiring credential just before its first use, not at job start
Put the step that fetches short-lived credentials immediately before the first step that uses them.

### Do not write to an artifact a human is testing on
- Handing someone a deployed thing to test — a synced project, a staging database, a preview build — and then continuing to push changes into it makes two writers for one artifact.

### Percent-encode a URL at construction, not at consumption
- A URL built by string-concatenation from filenames inherits whatever those filenames contain.

### A preview flag is only safe if it previews
- `--dry-run`, `DRY=1`, `--plan` conventionally mean "show me what would happen".

### Bare `y`, `n`, `on`, `off`, `yes`, `no` are booleans in YAML 1.1
- The YAML 1.1 core schema resolves `y`, `Y`, `n`, `N`, `yes`, `no`, `on`, `off`, `true`, `false` (and their case variants) to **booleans**.

### Documentation Staleness
- Moving/renaming scripts: update CLAUDE.md, READMEs, usage comments

### An ordered dispatch makes severity ordering load-bearing, and nothing enforces it
A `CASE`, an `if/elif` chain, or any first-match dispatch that reports a *verdict* carries an unwritten invariant: every serious arm precedes every advisory one.

### A link to a repo-hosted artifact must be *tracked*, not merely present
When the published site **is** the repository — GitHub Pages serving `docs/`, or a `raw.githubusercontent.com` URL — the question "does this file exist" is the wrong predicate.

### An assertion that matches an interpolated value cannot see the claim around it
`expect_error(f(x), "some_column")` looks like it pins the guard.

### A pluralisation marker takes the quantity of whatever was substituted last
`cli`'s `{?a/b}` reads the most recent quantity in the string, and **any** substitution resets it — including a length-1 one that is not what the marker is about.

## Security

### Process Visibility
- Secrets passed as command-line args are visible in `ps aux`

### Secrets in Committed Files
- `.tfvars` must be gitignored (contains tokens, passwords)

### Firewall Defaults
- `0.0.0.0/0` for SSH is world-open — document if intentional

### Credentials
- Passwords with special chars (`'`, `"`, `$`, `!`) break naive shell quoting

### Gitleaks pre-commit hook
Configuration patterns and false-positive handling for the `gitleaks` pre-commit hook (kdot's Brewfile ships `gitleaks` + `pre-commit`; cyclops standardizes the hook):

### "Public bucket" ≠ listable: GetObject vs ListBucket
- A bucket policy granting only `s3:GetObject` on `bucket/*` makes exact-key fetches public but NOT listing.

## Spreadsheets and PDFs

### A stored value is not wrong just because the raw number looks wrong
Before reporting that a spreadsheet value is off by a factor, check the cell's **number format**.

### Verify PDF links from the annotations, not the extracted text
`pdftotext` returns anchor text, not the href.

### Extracted PDF text carries corrupted glyphs, and a tolerant parser turns them into wrong numbers
Never strip non-digits to clean a number extracted from PDF text.

### Merge PDFs with `qpdf`, and check the merged file
Merge with `qpdf --empty --pages a.pdf b.pdf -- out.pdf`, not `pdfunite`, and run `qpdf --check` on the result.


# NGE Feature Workflow

For non-trivial issue-driven work, follow this checklist. Each step exists for a reason — skipping leads to rework, broken builds, and avoidable bugs that we've hit repeatedly.

## The Sequence

1. **Start with `/planning-init <N>`** — given an issue number, enters plan mode for codebase exploration, presents a phase breakdown for user approval, then scaffolds branch + PWF baseline with the approved phases. One command replaces the manual issue → explore → plan → branch → scaffold dance.
2. **Write robust tests first** — failing tests that reproduce the issue or document the new behavior. Tests are the contract; they fail until the work makes them pass.
3. **Name with intent** — functions, parameters, internal helpers carry the naming style of the package they live in. Look at existing exports as the guide; consistency over cleverness. For files rather than functions — shell scripts and operational R scripts under `scripts/` or `data-raw/` — the standard is the `noun_verb-detail` pattern in `newgraph.md`, noun first.
4. **Examples that run** — every exported function gets a runnable `@examples` block. Pkgdown renders them; CI executes them. An example that doesn't run is documentation rot.
5. **Code-check before it merges** — `/code-check` on the staged diff before each commit, or `/code-check branch` once over the branch before the PR ("When to Skip" below). Catches what tests miss: edge cases, hard-coded paths, unguarded variables, security issues.
6. **Atomic commits** — each commit bundles code change + checkbox flip in `task_plan.md`. The diff and the progress live in the same commit; `git log -- planning/` tells the full story.
7. **`/planning-archive` when complete** — moves PWF to `archive/YYYY-MM-issue-N-slug/`, creates a fresh `active/`. Then `/gh-pr-push` opens the PR; `/gh-pr-merge` handles the release bookkeeping.

## Where the checkpoints are not

Step 1's plan approval is the authorization for every step after it. Run steps 2–7
through to the **open PR** without stopping to report between phases — the merge in
step 7 is outside the mandate unless the instruction includes it; put the decisions that
genuinely change what gets built at the plan gate, batched, with a recommendation
first; report once when the PR is open. The rule, its boundary (before a plan
exists, a question wants an answer) and its exceptions are `agent-operations.md` §4.

## Re-read origin before you open the PR, not just before you cut the branch

Verifying local is current with origin (`code-check-shell.md`, "Before you *cut* a
branch") protects the branch point. It
says nothing about the build window, which is where a parallel session lands, and both
sessions' pre-flight checks pass.

*4 lines of evidence for this rule are in `conventions/feature-workflow.md`.*

Before opening a PR, and again before merging:

```bash
git fetch -q origin
git log --oneline HEAD..origin/main          # what landed while you worked
git diff origin/main -- DESCRIPTION NEWS.md  # a version you did not bump
```

**A version bump you did not make is the tell**, and usually the only one — the tree is
clean, the branch is healthy, and nothing in git hints that someone solved your problem
an hour ago.

On a collision, do not resolve conflicts file by file. The merge conflict hides the
useful question, which is *which body of work survives*. Ask, then re-land the delta on
top of what shipped; two independent attempts at one problem are usually complementary
rather than redundant, and a mechanical resolution keeps whichever half git preferred.

When main only moved under you, with other work and no duplicate, bring it in with
`git merge origin/main`, not a rebase: `progress.md` and the archive README cite the
branch's commit SHAs, and a rebase rewrites every one they name (2026-10-12).

## Re-read the issue body before the baseline

Re-fetch it and diff against the copy you planned from. An edit made during plan mode
is invisible to a plan built on the first read: in stac_airphoto_bc#47 the body gained
two requirements that way, caught only by the plan review after three phases had landed.

## An issue number you did not file yet is somebody else's

GitHub allocates one sequence across issues **and** PRs, on creation. So a number
written down before the issue exists — a branch name, a code comment, a config header,
a commit trailer — is a reservation nobody honours, and in an active repo it will
eventually name a real issue about something else entirely.

That is the expensive direction. A number pointing at *nothing* is obvious; a number
pointing at a **stranger's issue** resolves, renders as a link, and reads as provenance.
Nothing downstream checks that the issue it names has anything to do with the code
beside it.

*5 lines of evidence for this rule are in `conventions/feature-workflow.md`.*

- **Cite an issue only after it exists.** If the work has no issue and does not warrant
  one, write no number: a comment that explains itself is better than a wrong pointer.
- **Before merging, resolve every issue number the branch introduces** and check the
  title is about this work — one call, and it is the only thing that separates a good
  citation from a plausible one:

  ```bash
  git diff --stat origin/main...HEAD >/dev/null   # three-dot: the branch's own changes
  git diff origin/main...HEAD | grep -oE '(^\+.*)(rtj|rfp|gq|soul|link)#[0-9]+' \
    | grep -oE '[a-z_]+#[0-9]+' | sort -u
  # then, per hit:
  gh issue view <N> --repo NewGraphEnvironment/<repo> --json title -q .title
  ```

- **Name the branch for the work when there is no issue** (`<client>-<area>-<year>`), and
  rename it once one exists — `git branch -m` before the first push costs nothing.

Sibling of the section above: both are parallel sessions moving underneath work that
looked settled when it started.

## The version lives in one place

Do not restate the current version in `README.md` or `CLAUDE.md` prose. A version
string typed into prose drifts from the moment it is written — the release step
maintains `DESCRIPTION` and `NEWS.md`, and one report repo's
`CLAUDE.md` was found eight minor versions behind, its `README.md` one behind, with both
canonical files correct. Link to `NEWS.md` instead. Where a claim genuinely must stay in
prose, `/gh-pr-merge` step 7 greps for the previous version string outside the two
canonical files and updates the prose restatements it finds, reporting each.

## When to Skip

The skip covers the **workflow**, never the **review**. Two questions, answered separately:

- **PWF, branch, archive: decided by size.** For one-line fixes, version-bump-only PRs, or
  small documentation edits, the scaffolding is overhead. Use judgment. The threshold is
  roughly: **multi-step issue, multi-file change, or anything that requires scoping** →
  use the workflow.
- **`/code-check`: not decided by size.** Every change to something that runs or is
  loaded as instructions (code, a script, a skill, a convention, config) is reviewed
  before it merges, however short it is. For a lone commit that means before the commit.
  On a PWF branch it means once over the branch's diff (`/code-check branch`), with the
  same three-round floor. Size does not predict whether a review finds something; where
  the change lands does, and a one-line edit to something every repo loads is still a
  one-line edit to something every repo loads.

Three things are exempt, each for a stated reason:

- **Whitespace, and spelling inside a single word.** Changing a word changes what a rule
  says, and one batch's wrong claims each read correctly on their own.
- **Commits a skill writes itself and gates mechanically**: `/gh-pr-merge`'s release
  bookkeeping, CLAUDE.md syncs, `CITATION.cff` refreshes.
- **Unattended skills' capture commits**: `/compact-prep` step 2's, which can carry code,
  and `/claude-memory-audit`'s `CLAUDE.md` and `research/` writes. Not covered, as each
  reaches one repo; a soul `skills/` commit on `main` is the open exception. Convention
  appends get one reviewer instead, held on a finding.

The review is the cheap half. Scaffolding costs a plan, a branch and an archive; a review
costs a few reviewer agents, and its three-round floor stays, because small edits are
exactly where its findings have come from.

*7 lines of evidence for this rule are in `conventions/feature-workflow.md`.*

## Skills That Slot In

- `/planning-init <N>` — start
- `/planning-update` — sync checkboxes mid-session
- `/code-check` — before each commit, or once over the branch (`/code-check branch`)
- `/planning-archive` — when issue closes
- `/gh-pr-push` — open the PR
- `/gh-pr-merge` — merge with release bookkeeping

## Issue bodies get edited, not appended

When work changes what an issue should say, **edit the body**. Don't add a
comment that corrects it, and retitle when the scope moves.

**Why:** an issue is read as a spec by whoever picks it up. A body saying one
thing with a comment three screens down saying the opposite costs the reader the
reconciliation, every time.

**How to apply:** `gh issue view N --json body -q .body` into a file, revise,
`gh issue edit N --body-file`. Name what changed and why when the correction is
load-bearing — the goal is a body that reads correctly top to bottom, not an
erasure of history. Comments are for genuine commentary: a merge notice, a
cross-repo pointer, a question. Applies to PR bodies too. Commit messages are
immutable history and are never rewritten this way.

**The failure mode that keeps recurring: research findings feel like
commentary.** They are not — they are the spec. If a finding changes what
someone would *build*, it belongs in the body, with the durable version in
`research/` and the body linking to it. What `research/` holds, how a file is
named and what its header carries is `planning.md`, "`research/` — what is
known, outliving the issue that found it".

**Bodies drift at the moment work finishes, not while it is in flight.** Four
instances in a single day of rfp work, all of the same shape — the code learned
something and the issue did not:

| drift | what a reader saw |
|---|---|
| premise disproved by measurement | an issue arguing for a fix that was no longer needed |
| a conclusion asserted in the body but never landed in code | body and tree contradicting each other |
| the shape of the work moved during exploration | a spec describing a design nobody built |
| a decision made and shipped, body still listing options A–D | "decision needed" on a decision a year old |

Vigilance does not catch this, because the drift happens exactly when attention
moves to the merge. `/gh-pr-merge` reconciles at that moment — see its step 3b.

## Work owed between two open issues stays in both bodies

A task whichever PR merges second must do stays in both issue bodies until it is done, and
the merge that does it ticks both copies. Never write "moved to #M": a move bets on a merge
order nobody has decided. `/gh-pr-merge` 3b re-reads the other issue before writing a pointer to it.

*4 lines of evidence for this rule are in `conventions/feature-workflow.md`.*

## Public-repo text describes the package, and points nowhere private

In a public repo, issues, PRs, comments, commit messages, NEWS and roxygen describe
behaviour **in terms of the package's own inputs and conditions**. Our machines, tunnels,
ports, local env files and private repos stay out, with the two exceptions below. Check
where the text lands before you draft it, naming the destination: with no argument, `gh`
reports the repo the session stands in, which reads private when you file from a private
repo into a public one.

```bash
gh repo view <owner>/<repo> --json nameWithOwner,visibility --jq '"\(.nameWithOwner): \(.visibility)"'
```

**Why:** a public package is a tool for anyone who installs it. "On our dev box the
tunnel on port N is down" tells an outside reader nothing about the package, and it
publishes our setup. A link to a private repo 404s for everyone outside the
organisation, and it names internal work as it does so.

**How to apply:**

- **Restate an infrastructure-only repro as its general condition.** "Credentials are
  set and the server is unreachable, so the test errors instead of skipping" is the bug.
  Which host it happened on is not. Propose a general mechanism, such as gating on a
  reachable connection, not a workaround for one setup.
- **Host names, tunnels, ports and local env files** (`~/.Renviron` and its like) stay in
  private repos or machine-local notes. A public repo's `planning/` is committed, so it
  is public too. One exception: where the machine is the subject of a measurement, such
  as a benchmark between hosts or a run log named for the host that produced it, its
  label stays. The setup around it still goes.
- **No links to private repos, and no `owner/private-repo#N`, not even as provenance.**
  Describe the dependency in words ("work on a downstream estimate is in progress"), or
  leave it out.
- **One exception: the R&D tracking cross-reference.** `/gh-pr-push` writes it into PR
  bodies, resolved from the tracking issues' titles. It stays: it is deliberate claim
  tagging, and the only private pointer this rule allows.
- **A scrub covers the surfaces you were editing; re-grep the others before merging.** The
  issue body is drafted at plan time and the code later, so scrubbing the tree and the PR
  body leaves the body untouched. `/gh-pr-merge` step 3b is the moment to grep it, then
  read it for the bare names a grep misses. It also refuses a branch whose diff adds a
  private repo's URL, `name#N` or, for the names on its bare list, the bare name to tracked
  files (`private_refs.sh`).
- **A leaked body is recreated, not edited: GitHub shows its edit history to anyone.** A fresh
  issue with no discussion is deleted (`gh issue delete`, admin) and refiled clean, the private
  side in a private-repo issue. Where the number must stay, edit it, then delete each older
  revision in the web UI (the "edited" menu); the API cannot. GraphQL `userContentEdits` lists
  the revisions. A leaked title stays in its `RenamedTitleEvent`, so only deleting the issue
  removes it. A private repo flipping public meets this for every body at once, before the flip.
- **A public repo's `CLAUDE.md` is contributor text, and it is still public.** Package-level
  setup, such as which env vars the connection helper reads and how live tests skip, stays.
  Our host topology does not: which machine runs what, cross-host ssh recipes, tunnel ports.
  Write those as a generic example, or keep them in machine-local memory. The
  conventions synced below the marker are generated, so fix a private reference in them
  at their source, never in place; soul's `check_public_render.sh` fails on one there.

This is the public-repo half of the rule that keeps project and client identifiers out of
public text. Both apply wherever the destination is public, whichever repo the session is
running in.

*22 lines of evidence for this rule are in `conventions/feature-workflow.md`.*


# LLM Behavioral Guidelines

<!-- Source: https://github.com/forrestchang/andrej-karpathy-skills/main/CLAUDE.md -->
<!-- Last synced: 2026-02-06 -->
<!-- These principles are hardcoded locally. We do not curl at deploy time. -->
<!-- Periodically check the source for meaningful updates. -->
<!-- Only the upstream guidelines live here. NGE's own operating rules, once sections 5-8 of this file, are in agent-operations.md. -->

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


# Planning Conventions

How Claude manages structured planning for complex tasks using planning-with-files (PWF).

## When to Plan

Use PWF when a task has multiple phases, requires research, or involves more than ~5 tool calls. Triggers:
- User says "let's plan this", "plan mode", "use planning", or invokes `/planning-init`
- Complex issue work begins (multi-step, uncertain approach)
- Claude judges the task warrants structured tracking

Skip planning for single-file edits, quick fixes, or tasks with obvious next steps.

## The Workflow

1. **Explore first** — Enter plan mode (read-only). Read code, trace paths, understand the problem before proposing anything. When the work codifies a pattern that already exists in multiple places (reference implementations across repos), read **every** reference in full, not just the canonical one — variation across references surfaces patches before v0.1 instead of as churn later (measured: reading all 4 references preempted 5 of the 7 fixes a dry-run would have found). Don't substitute Explore-agent summaries for direct reads; agents sometimes report existing files as absent.
2. **Plan to files** — Write the plan into 3 files in `planning/active/`:
   - `task_plan.md` — Phases with checkbox tasks
   - `findings.md` — Research, discoveries, technical analysis
   - `progress.md` — Session log with timestamps and commit refs
3. **Plan-review with the Plan agent — concurrently, not as a gate** — Once `task_plan.md` is scaffolded, spawn the Plan subagent (`Agent({subagent_type: "Plan", prompt: "..."}`) and ask it to critically review the task_plan against the issue body + actual codebase. Categorize findings as Blocker / Gap / Ordering / Assumption / Scope / Acceptance. The agent reads files fresh — it catches what you miss when you've been thinking about the design too long.

   **Do not wait for it.** Spawn, then start the lowest-risk phase. Background agents have repeatedly returned late — in one case after the entire issue had shipped — so treating the review as a precondition stalls the work for as long as the agent takes (see `agent-operations.md` §2). Fold findings in whenever they land: pre-baseline they edit the plan; mid-implementation they become follow-up commits — unless the finding is a stored-data fork of the kind `agent-operations.md` §4 reserves for the user. If you genuinely cannot proceed without the result, run it with `run_in_background: false` so the blocking is explicit.

   **On a park the review runs before the baseline, so keep it a review of the plan:** read it against the issue, its comments and the code it names. One cheap probe (a grep, a listing) may settle a design fork; a question needing more becomes a checkbox in the phase that measures it.

   Verify before acting, in both directions. Findings have been confidently wrong (a "BLOCKER" disproved by a 30-second probe) and confidently right about things nobody suspected. Reproduce the claim first.

   **"Both directions" includes the reviewer's conclusions, not just its findings.**
   A review is wrong in the *alarming* direction loudly — a BLOCKER you probe and
   disprove costs one round-trip. It is wrong in the *reassuring* direction
   silently, because nothing prompts you to check a sentence telling you that you
   are finished. Treat *"this is now terminal / complete /
   definitional"* as a claim with an author, exactly like an issue asserting a
   question can only be answered by testing.

   **Spawn review agents UNNAMED.** A named spawn becomes a *teammate* that goes **idle** rather than completing, so its report never arrives on its own; pass `name` only for a collaborator you will keep messaging, and shut it down when done.

   **Get the findings into a file — but check who is doing the writing.** Message delivery can fail silently, by idle pings with no content or by routing to another session. From this side an idle ping is indistinguishable from an agent that had nothing to say, so the loss is invisible. A file (`planning/active/review-<N>.md`) survives routing, survives the agent exiting, and is greppable later. One path per **spawn**: a replacement gets its own, because the original may still deliver into the one it was given, and a missing file reads as a lost review only after the completion notification or the deadline in `agent-operations.md` §2, "Don't trust status".

   **The `Plan` and `Explore` agent types have no Write tool, so they cannot write that file.** Asked to, they return the review as reply text instead. So:

   - **Read-only agent** (`Plan`, `Explore`): ask for the findings **in the reply**, then write them to `planning/active/review-<N>.md` yourself. The file is still the deliverable; you are just the one creating it.
   - **Agent type that can write**: put the file-path instruction in the first prompt, not as a follow-up.

   **A reviewer asked to prove a guard fires will patch your working tree, and that races
   your own test runs.** "Restore the defect and watch it go red" is the right instruction
   (`code-check.md`), and a subagent given it edits the same files the parent is testing.
   From the parent's side the result is a test run that reports failures belonging to
   nobody's code — the reviewer's planted defect, caught mid-flight. Tell reviewers to work
   in a copy (`git worktree add --detach <tmp> <ref>` or `git clone`, never `cp -r` of a
   checkout whose `.git` is a file) and say so in the prompt; they honour it
   when asked. Then snapshot the files you care about and `cmp` them before **and after**
   every run whose result you intend to act on, so "the tree was intact for this
   measurement" is a fact rather than an assumption. Same hazard as a mid-flight edit in
   `agent-operations.md` §1, arriving from an agent instead of from you.

   **A copy protects the files, not where a script writes or the CPU.** A copied script
   still writes where its paths point (an absolute path from anywhere; a relative one or
   `here::here()` when it runs from the repo), so name each output variable to redirect and have the reviewer confirm the
   substitution matched before it runs. And time nothing while a reviewer is probing: start
   a benchmark after its completion notification, or tell it to read and not run code.

   **Review the fixes, not just the code.** The second pass is where the value concentrates, because a fix written under a wrong assumption reproduces the same defect. **Convergence is the signal to stop, not a fixed number of rounds.**

   Convergence is measured, not felt — a quiet round and an exhausted reviewer look
   identical, and a reviewer saying you have converged is a claim. End on a **mechanical
   enumeration of the candidate set showing nothing sits above its source of truth**
   (`code-check.md`, "A guard's scope, escape hatches, and remedies"), a mutation table for
   the guards a fix introduced. `/code-check` treats three rounds as the floor and keeps
   going while a round finds a defect inside the previous fix.

   Ask for the **mechanism**, not more instances, such as an invariant enforced by two lists happening to agree.

   The thing reviewers catch that self-probing does not is **interop**. Ask the consumer.

*35 lines of evidence for this rule are in `conventions/planning.md`.*

4. **Lock naming before the baseline** — If naming feedback surfaces during planning (legacy filename, inconsistency with an existing file family), fold the rename into the convention + task_plan BEFORE the baseline commit, not as a follow-up. Pre-baseline it's free; retrofitting after implementation cascades (measured: `build_exec_pdf.R` → `run_pagedown_exec_summary.R` locked in pre-baseline meant zero downstream rework).
5. **Commit the plan** — After Plan-agent review + fixes. This is the baseline.
6. **Work in atomic commits** — Each commit bundles code changes WITH checkbox updates in the planning files. The diff shows both what was done and the checkbox marking it done.
7. **Code check before commit** — Run `/code-check` on staged diffs before committing, or once over the branch with `/code-check branch` before the PR (`feature-workflow.md`, "When to Skip"). Per commit, don't mark a task done until its diff passes review. In branch mode each commit still carries its own checkbox flip (Atomic Commits, below), the Validation box for `/code-check` is the one that waits for the branch review, and its fixes land as follow-up commits.
8. **Archive when complete** — Move `planning/active/` to `planning/archive/` via `/planning-archive`. Write a README.md in the archive directory with a one-paragraph outcome summary and closing commit/PR ref — future sessions scan these to catch up fast. Where the work produced measurements, that README is also the evidence record; see below.

## The archive README is the measurement record

Debugging and benchmarking sessions are systematic investigation: a stated unknown, an
experiment, a number, a conclusion, and usually two or three informative dead ends. That
is SRED evidence, and it scatters — into PR bodies, issue comments, and log files whose
names encode a timestamp and nothing else. In six months the chain *we did not know X,
we measured Y, therefore Z* survives only in a chat transcript.

**The archive README is where that chain lives.** Not a separate run record: the PWF
triple already holds every part of it — the question in `task_plan.md`'s frame, the
method in `progress.md`, the numbers in `findings.md`, the dead ends in its "Errors
Encountered" table. A second document would restate all of it and be half-populated.
The README is the index over them.

So an archive README for work that produced measurements carries two more sections:

```markdown
## Measurement

<host-a> 0.0391 vs <host-b> 0.0872 min/1k segments — hosts are 2.23x apart.
Moved the provincial estimate 5.0 h -> 4.3 h and changed how work packs across machines.

## Evidence

`data-raw/logs/study_area_run/20260831_19*` — four spins, one defect each.
```

Three rules on those sections:

- **Numbers carry units, and say what changed because of them.** A measurement nobody
  acted on is still worth recording if it turned an assumption into a number — say that
  too. "Confirmed the expected" is a real outcome.
- **Cite a prefix or glob, never a file list.** A list rots the moment a run is re-run;
  a prefix survives. This is why campaign subdirectories exist (`newgraph.md`, "Which
  logs to commit").
- **Keep the wrong turns.** A diagnosis made, retracted on a bad inference, then
  confirmed by measurement *is* the evidence of systematic investigation. Sanitising it
  into a tidy conclusion destroys exactly what makes the record worth keeping.

**The case this does not cover.** Measurement that predates an issue has no PWF to
attach to — `/planning-init` takes an issue number, and exploratory runs often *produce*
the issues rather than follow them. That measurement belongs in the issue or PR it
spawned, with the log directory's own README as the index. Do not build a third system
to close this gap. The *finding* it settles goes where every settled finding goes —
`research/`, next section — which is not a third record of the run but the one place its
verdict is kept current.

## `research/` — what is known, outliving the issue that found it

Three homes, one job each: **the PWF archive is the story, committed logs are the
measurements, `research/` is the durable verdict** — floodplains' `research/README.md`
had that framing before this section existed. A research file holds what is now *known*: a
settled method, a measured fact about an external system, a search that established an
absence — so that someone picking the work up months later does not re-derive it.
`planning/archive/<issue>/` holds what was *done*, in order, for one issue, and is rarely
opened by anyone who never saw that issue. The research file is the one they will look for.

What does **not** go there: a work log; a run record (Run / Hardware / Software /
Configuration blocks — that is the archive README's `Measurement` and `Evidence`, above);
the raw numbers (committed logs). A living document revised as knowledge moves is the shape
that moves the state of knowledge; a dated run record duplicates the archive.

*5 lines of evidence for this rule are in `conventions/planning.md`.*

### One topic file, revised in place — git is the version record

`research/<topic>.md`, noun-first, **no date in the filename**. A new measurement that
changes what is known revises the topic file; it does not add a dated sibling.
`git log --follow research/<topic>.md` is the dated history, the archive README it cites
is the *why*, and the logs are the numbers — everything an R&D claim needs, with no second
copy of any of it.

Existing dated files — `20260711_…`, `…_2026_05_25.md` — are **not renamed**. They are
cited by path from `CLAUDE.md` files and from other conventions (`bookdown.md`,
`agent-operations.md` §3), and a rename breaks the citation the way it breaks log evidence
(`newgraph.md`, "Which logs to commit"). Convergence is forward-only, and the README says
when.

### The header is the provenance, in prose

No research file in any repo carries YAML frontmatter and nothing consumes it, so
provenance is one line under the H1. floodplains' is the shape to adapt — it already carries
the date and the issues, and names its log prefix in the body:

```markdown
**Date opened:** 2026-07-11 · **Issue:** #8 · **drift:** 0.6.0 (`dft_stac_fetch(tile_size=)`,
drift#36) · **Status:** OPEN — design set, runs pending.
```

Three things the line must carry — `**Verified:** <date> · **Issues:** … · **Produced by:** …`
is the minimal form:

- **When it was last true.** The file's date, and a section-level date wherever one
  section is re-verified alone. A research file whose numbers cannot be re-derived ages
  into folklore, and one that states a scope or a quantity drifts silently when the code
  moves — three link documents, two of them research files, asserted a recompute "runs over
  every WSG in the schema" after two commits had changed it (`agent-operations.md` §3, "Documents
  that share an ancestor corroborate nothing"). When code changes a behaviour a research
  file describes, grep `research/` for the sentence. Files written before 2026-09-06 gain
  the line when next revised; no fleet sweep is required.
- **What produced it.** The script path or log prefix for a measurement; the source list or
  reference-manager collection for a literature review. Never a number without its producer.
- **Which issues it came from and which it spawned.** The issue body links the research
  file (`feature-workflow.md`, "Issue bodies get edited, not appended"); the research file
  names its issues; and an archive README whose `Measurement` was distilled into a research
  file links it. Both ways, every time — one direction leaves the other end unfindable.

### The directory carries a README

An index: one row per file, what it covers — rfp's is the model. Where other repos hold
related work, a "Related work" list of links. Where two naming patterns coexist, the
cutover line in the form `newgraph.md` uses for logs:

```markdown
Naming: `<topic>.md`, revised in place, from 2026-09-06.
Files dated before that carry a `yyyymmdd_` prefix; they are not being renamed.
```

The README is the index. `CLAUDE.md` links the README once and cites an individual file
only where a rule depends on it. Twenty-three topic files with no README and a `CLAUDE.md`
citing four of them by path — link, measured 2026-09-06 — is the state this prevents.

### R packages and public repos

`research/` is top-level and excluded from the tarball: `^research$` in `.Rbuildignore`
(`code-check-r.md`, "`R CMD build` ships every top-level directory not in
`.Rbuildignore`"). Not `inst/notes/` or `inst/research/`, which ship inside the installed
package — the three packages carrying those (eight files, 2026-09-06) migrate by issue,
forward-only. In a package, `research/` is also where durable reference notes go, because
`docs/` belongs to pkgdown and `inst/` ships. And a public tool repo's `research/` is
public: report findings from internal work aggregated, never by the names of who it was for.

## Atomic Commits (Critical)

Every commit that completes a planned task MUST include:
- The code/script changes
- The checkbox update in `task_plan.md` (`- [ ]` -> `- [x]`)
- A progress entry in `progress.md` if meaningful

This creates a git audit trail where `git log -- planning/` tells the full story. Each commit is self-documenting — you can backtrack with git and understand everything that happened.

## File Formats

### task_plan.md

Phases with checkboxes. This is the core tracking file.

```markdown
# Task: <issue title> (#<N>)

<issue body — Problem section if present, otherwise first paragraph>

## Phase 1: [Name]
- [ ] Task description
- [ ] Another task

## Phase 2: [Name]
- [ ] Task description
```

Mark tasks done as they're completed: `- [x] Task description`

### findings.md

Append-only research log. Discoveries, technical analysis, things learned.

```markdown
# Findings

## [Topic]
[What was found, with source/date]

## Errors Encountered

| Error | Resolution |
|-------|------------|
```

### progress.md

Session entries with commit references.

```markdown
# Progress

## Session YYYY-MM-DD
- Completed: [items]
- Commits: [refs]
- Next: [items]
```

<!-- The Reboot Test and the error ledger below are adapted from -->
<!-- OthmanAdi/planning-with-files (MIT). Soul does not install or invoke that -->
<!-- plugin — the useful parts are carried here as text. Adapted 2026-08-26. -->
<!-- Same precedent as the attribution header in karpathy.md. -->

## The Reboot Test

The planning files exist so the work survives an interruption. Whether they
actually do is checkable: at any point mid-task, these five questions must be
answerable from the files alone, without the conversation.

| Question | Answer source |
|----------|---------------|
| Where am I? | Current phase in `task_plan.md` |
| Where am I going? | Remaining phases in `task_plan.md` |
| What's the goal? | The `# Task: <title> (#N)` frame and problem statement at the top of `task_plan.md` |
| What have I learned? | `findings.md` |
| What have I done? | `progress.md` |

If an answer lives only in the session, **write it down and commit it**. Written
is not sufficient: an uncommitted `findings.md` does not move between machines,
and a repo whose `planning/` is gitignored accepts `git add planning/` with exit
0 while tracking nothing — see Directory Structure below.

This is the operational check for the rule that every interruption should be a
resume point: a session death, sleep, or machine swap should cost a re-run at
most, never lost context. That rule states the goal; this tests it.

Run it before any long wait, before compaction, and before switching machines —
the moments that take a session without warning. `/compact-prep` and
`/planning-update` are where it gets run; this section is what it asks.

## Directory Structure

```
planning/
  active/          <- Current work (3 PWF files)
  archive/         <- Completed issues
    YYYY-MM-issue-N-slug/
```

If `planning/` doesn't exist in the repo, run `/planning-init` first.

**`planning/active/` must be tracked, not gitignored.** The atomic-commit rule
above requires each commit to carry its own checkbox flip in `task_plan.md`; an
ignored `active/` drops it silently, so `git log -- planning/` shows archives
appearing fully-formed with no history behind them. In-flight PWF also stops
surviving a move between machines.

The failure is quiet in both directions. `git add planning/` reports nothing and
exits 0 on an ignored path, and files tracked *before* the rule existed keep
being tracked — including through a `git mv` into the ignored directory. So a
repo can look like it is working right up until the first genuinely new PWF file,
which simply never appears in a commit.

Check rather than assume:

```bash
git check-ignore -v planning/active/task_plan.md   # expect no output
```

*3 lines of evidence for this rule are in `conventions/planning.md`.*

## When Something Keeps Failing

Before a second attempt, name the failure class. A **deterministic** failure
returns the same result to the same inputs, so re-running unchanged only spends a
turn — change the inputs or change the approach. A **transient** failure
(network, a provider read, a rate limit, a resource still settling) is the case
where a re-run *is* the attempt: `code-check-infra.md` prescribes exactly that for a
tofu plan that falsely reports a resource deleted. The rule is not "never retry";
it is never retry unchanged while expecting a different answer.

Escalate rather than iterate once the approach itself is in question. Report what
was tried and the exact error, and hand over the commands to run — the user is
assumed to be away, so a question answerable from a phone beats a retry loop they
cannot see. Escalating is not stopping: commit the current state, then move to
the lowest-risk independent part of the plan while the question is outstanding.

Two classes escalate immediately rather than after retries, because further
attempts make them worse:

- **A clamped session.** Once a live credential has been read, later
  system-mutating commands are refused regardless of route — seven consecutive
  refusals across unrelated routes is the documented case (`newgraph.md`,
  "Reading a secret clamps the rest of the session"). Trying more phrasings is
  the failure mode, not the remedy, and `/permissions` does not clear it.
- **Rate limits.** Retrying extends the block (`ci-monitoring.md`).

### Log the errors that cost a retry

An error that took more than one attempt to get past goes in `findings.md`, so
one task does not hit the same wall twice:

```markdown
## Errors Encountered

| Error | Resolution |
|-------|------------|
| `fatal: Unimplemented pathspec magic '_'` | Long-form `:(exclude)path` |
```

That row is also what graduation looks like: it began as one task's blocker and
now lives in `code-check-shell.md` as a general rule about pathspec magic. Most rows
never make that trip and should not — the ledger's job is to stop one task
repeating itself.

When a failure does generalize, it graduates to the convention that owns its
class: the `code-check*.md` family for a bug class in a diff — `code-check.md` for a
mechanism, `-shell`, `-r`, `-python`, `-spatial` or `-infra` for a tool quirk — `ci-monitoring.md` for CI
behaviour, the domain convention otherwise.

## Skills

| Skill | When to use |
|-------|-------------|
| `/planning-init` | First time in a repo — creates directory structure |
| `/planning-update` | Mid-session — sync checkboxes and progress |
| `/planning-archive` | Issue complete — archive and create fresh active/ |

# Provenance
How an output says what made it and what came out, and how a rebuild is judged against it.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/provenance.md`; read it before writing or reviewing code in its area.*

### One receipt per output, in one shape: output, recipe, result, context
Once the receipt writer for its language ships (rule 4), write one `receipt.json` per output, replacing a `manifest.json` or `provenance.json` when the writer is next touched; until then, write the repo's current format and map its names (rule 10).

### Keep what changes on every rebuild out of the output's bytes
Write time, host and run id beside an output, never inside it, and pin what a format would stamp (GeoPackage `last_change`, layer order), so one recipe writes the same bytes: in new outputs, and in a writer when it is next touched.

### A recipe identity and a result identity; the machine is context
Hash code, config, seed and each input's **recipe** identity into one recipe hash (a receipt's `recipe_id`); never fold an input's result into it, and never let the host or toolchain into either identity, nor the host into a record that is published.

### crate holds the contract; each language implements it once against its test vectors
Write receipts through crate's contract (schema, RFC 8785 `recipe_id`, table fingerprint, test vectors): R packages call `crt_receipt_write()`, Python `stacs.receipt`, and any other writer passes the same vectors.

### Compare two records to one of three verdicts, and name the side that differed
Compare a rebuild with its reference copy and report `identical` (same recipe, same result), `equivalent` (same recipe, result within the declared tolerance) or `different` (another recipe, or past the tolerance), naming which of recipe or result differed and where.

### Declare tolerances per output, beside the code that writes it
State each output's tolerance where its writer lives: exact for a table of counts, a rounding for a floating sum, a declared spread or an invariant ("the same pick and region") for a model fitted with random draws.

### A published output keeps its result and record as the reference copy
Keep what is published, its bytes and its record, as the reference copy in the bucket; anything not published is rebuilt from its recipe and compared to that copy, never assumed equal.

### Read a record to report a difference; refuse only on integrity or same-operation parity
Read a provenance record to **report** what differs; refuse on one only when bytes received differ from what the sender listed, two parties in one operation must hold the same bytes now, or the record is older than its input.

### A per-field register says what a difference in each field does
Keep a register, one row per record field, saying whether a difference refuses, warns or is recorded, make it the comparison's input rather than a description of it, and test it with two records that differ in one field each.

### Map existing names to the shared keys and to STAC's; converge forward-only
Map each existing field name to its key in the receipt and, on a catalogue, to STAC's own (`file:checksum`, `file:size`, `processing:software`, `processing:datetime`), and rename only when the writer moves to a receipt (rule 1).

# Python Conventions
How New Graph Environment repos declare and run Python, the sibling of `r-packages.md`.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/python.md`; read it before writing or reviewing code in its area.*

### Declare dependencies in `pyproject.toml` and commit `uv.lock`
A repo whose Python is a package, or whose scripts import a shared module of the repo's own, declares its dependencies in `pyproject.toml`, commits the `uv.lock` that `uv lock` writes, runs through `uv run`, and adds no `environment.yml`.

### A loose script carries its dependencies inline
A standalone script that imports no module of the repo's own declares its third-party imports in PEP 723 inline metadata and runs with `uv run --script`; one that imports only the standard library needs none.

### Two exceptions, each named in the repo's `CLAUDE.md`
Conda stays where a conda-forge binary that has no wheel is load-bearing, and PyQGIS scripts declare nothing, because QGIS's own interpreter runs them.

### Never `conda run -n` an environment the repo does not declare
A script that runs `conda run -n <env>` against an environment declared in no file of its own repo cannot run from a fresh clone, so declare the dependencies here instead.

# Writing a README
A README tells a stranger what a package is, why it is worth their time, and how to try it, in that order and in the fewest words that stay true.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/readme.md`; read it before writing or reviewing code in its area.*

### Open with what the package is and why it is valuable, not with a list of features
Open with one to three sentences on what the package is, what data it works on, and why that is valuable, naming the conservation or restoration decision it informs where there is one.

### Write the tagline, the description field, the GitHub About and the opening together
Change the README tagline, the DESCRIPTION `Title` (or pyproject `description`) and the GitHub About text together so they say the same thing, and keep the `Description` field and the README opening in step.

### Show a little code and its real output, a figure of real output, or both
Show the package working instead of listing what it can do: a figure of real output where it is spatial or visual, a short example with its real printed output, or both.

### Describe nothing that is not fully built
Leave out every capability that has not shipped, including partly built ones and those framed as a target, a next iteration or a roadmap; add each one when it ships.

### Check each claim against the code path a run takes
Before publishing a README sentence, find the code path a real run takes for it, and check that each "every", "each", "both" or plural holds for every member of its set.

### Sections run in a fixed order
Order a README as: name, hex sticker, a lifecycle badge while unstable, and tagline; the opening; the figure; Installation; the example; Learn more; Ecosystem; Data and methods it builds on; Citation, License and NOTICE.

### State development status with a lifecycle badge, not a warning in the prose
Mark an unstable installable package with a lifecycle badge under the title, and after the install command say that functions change between releases, link NEWS, and show how to pin one.

### A README figure of output is made by committed code
Make every README figure of the package's output from a committed script that runs on real data, check it at its published width, give it alt text and a short caption saying what it shows, and style a map through gq.

### Leave out what another file already keeps
Leave out roadmaps, changelogs, function tables, version strings in prose, counts of published things, and internal hosts or private repos, because each is kept elsewhere and goes stale in a README.

# Writing for the Reader
Anything an outside reader sees answers their questions in their order and carries nothing that served only its authors.

*Index only: each rule's heading and first sentence. The full text is soul's `conventions/writing.md`; read it before writing or reviewing code in its area.*

### Headings are the reader's questions, in the order they ask them
Make each heading a question the reader brings, in their order, within any sections a report template fixes; in a data product's article, limits and validation go last.

### Open with the answer
State the finding, with its numbers, in a sentence or two before any method, so a reader who stops there has the right answer.

### Orient the reader in one sentence per place
Say where each place is by the river it joins and the nearest town with a compass direction, checked against the Freshwater Atlas, and show the places on regional maps with keymaps.

### Write each article to stand alone
Never use a sibling article as the reference point: describe each method, bar and comparison on its own terms, and carry the sentence the reader needs rather than the sibling's figure or paragraph.

### Define a term in its own place, before it is used
Give a term the article depends on its own short section before its first use, with its rule, why it exists, and how many cases fall each way.

### Prefer a plain phrase to a term
Name a quantity by what it does for the reader ("the score; lower is better"), and keep a term only if the article reuses it, giving it its own place.

### Species common names in lower case
Write chinook salmon, coho and steelhead in lower case in prose and captions: it is our house style.

### Choose the form that lands with the reader
Pick a sentence, table, figure or map by which one tells the reader the story fastest, and judge it by its effect on the reader, not by a preference for prose.

### A sentence beside a table says what it shows, never what it holds
Say the pattern beside a figure or table and leave its values to it: restated medians, shares and month names are read twice, and a statistic the table does not hold has no source on the page.

### A caption names every mark the figure draws
When a figure gains a mark, its caption gains a phrase, or the new mark reads as one the caption already names.

### Define, read and cite every statistic you name
Give every statistic an article names, at the table that carries it, what it compares, how to read its values, a source, and a published rating scale beside the values where one exists.

### Cut what serves the authors
Remove what the authors needed and the reader does not: parity with superseded products, paths to internal research, and how a decision was reached.

### State a weakness as what the product does, not what the reader should do
Describe each weakness in one sentence about what the product does, with no advice on working around it beyond the product's own rule.

### State each claim by the code's definition
Describe a set the code defines by that definition, never by its best-known member or a nearby proxy, or the sentence and its guard cover the proxy, not the set.

### Check that each guard covers the set its sentence names
Give each claim a guard over the whole set its sentence names, at the precision written, and re-read the guard whenever the sentence moves or is reworded, as "State each claim by the code's definition" asks of the sentence.

### When explaining a decision, list every check and the way it points
Count the checks from the data, not the conclusion, give each its direction, and call a choice the evidence did not make a decision.

### Name, link and cite the software
Cite every package an article uses inline at its first mention, ours included, data to its publisher and each claim to the page that says it, from one `.bib` of Zotero entries and the packages' own `citation()`.

### Measure the simplification
Report word and line counts before and after a rewrite, against the forecast, and name what set the floor.

### Lead with what the product does and why it matters
Open every public piece with what the product does for the reader and why it matters, before anything about how it was made.

### Let visuals carry the story where they land better
Put the story in a map, figure or table whenever the reader takes it in faster there than from prose, and keep the prose to what the visual cannot say.

### Show one case before the statistic that counts cases
Show what an effect does in one case, a figure or a worked example, before the table that counts how often it happens, and say in the table's lead-in why the count matters.

### Review a rendered article where the reader will read it
Offer the rendered page in a form that opens on a phone, before the merge, without being asked.

### Cut any number or caveat that does not change what the reader understands
Drop a number, a precision or a caveat that leaves the reader's understanding of the product where it was, because detail the reader does not need walls them off.

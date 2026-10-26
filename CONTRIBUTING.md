# Contributing to AgentOS

Repository: https://github.com/adityashaw5338-creator/AgentOS.
AgentOS combines a Python tool engine, persistent workflows, and a local dashboard.
## Working together

Create a feature branch and submit a pull request against `main`. Contributors with write
access can push a branch to this repository; other contributors should push to a fork.
Use your own Git identity, with a verified email or your GitHub noreply address:

```bash
git config user.name "Your name"
git config user.email "Your GitHub-linked email"
git switch -c feat/your-change
```

Review `git status`, stage the intended project files, inspect the staged diff, then commit
and submit your pull request. Describe the changed behavior and the checks you ran.
Keep databases, access tokens, virtual environments, build outputs, and verification artifacts
out of Git. Profile credit depends on commit authorship and a default-branch merge.
Collaborator access alone does not create contribution activity.

For shared authorship, agree on a `Co-authored-by: Name <GitHub-linked email>` trailer.
Preserve authorship when merging; uploading another person's files under your own identity
does not preserve their contribution credit.

## Validation and extension contracts

Install `.[dev]`, then run pytest, Ruff checks, Ruff format checks, and a package build
as in the [README](README.md#development). GitHub Actions runs these checks on Python
3.11, 3.12, and 3.14. Exercise invalid arguments, approval policy, and retry behavior when
adding tools. Test with
temporary databases and controlled test tools, without real external side effects.

Tools take typed keyword arguments, use unique registry names, and return JSON-serializable
results. Nested Pydantic model arguments must reach the callable as validated model instances
and survive a saved approval resume. Put mandatory approval on the registry definition.
Plans reference prior steps
with `{"$ref": step_id}`. Claim task revisions before resuming execution and handle stale
updates without running a tool. Do not automatically retry a task after a process crash.

For dashboard changes, preserve the [design system](DESIGN.md), use real task data, and
verify desktop, tablet, and phone layouts. Run both browser scripts using the isolated
server setup in the README. Delayed responses must not overwrite a newer task revision;
disconnect must clear workspace data, and keyboard focus must follow approval actions.

Update README.md when installation, commands, API behavior, or configuration changes.
Record user-visible changes in CHANGELOG.md and update DESIGN.md when interface behavior
or tokens change. A pull request that changes a contract should include a regression test.

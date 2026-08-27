# Main Branch Protection Verification

- Verified at: 2026-08-28 (Asia/Shanghai)
- Repository: `zj1310426307-stack/dayu-tiangong`
- Protected branch: `main`
- Protection mechanism: GitHub classic branch protection

## Active rules

| Rule | Observed value |
|---|---|
| Pull request required | enabled |
| Required branch update | `strict = true` |
| Conversation resolution | enabled |
| Administrator enforcement | enabled |
| Required approvals | `0` (single-maintainer decision explicitly authorized) |
| Force pushes | disabled |
| Branch deletion | disabled |

Required checks, read back from the GitHub API:

```text
MODEL02 Ubuntu Python 3.11
MODEL02 Windows Python 3.11
Legacy hydraulic
Frontend contract
```

## D1 release evidence

- PR: `#10`, merged by merge commit.
- Merge commit: `cc6936d9d48d64c46a78ba85bed77c473e20cff3`.
- Merge parents: `c00a05fa508f3f186e87f05dd26b67ea88cfc0fc` and `0b93ec52c0e2722b4eef1b6059cd7fb7f0be999f`.
- Annotated tag object: `1f5b9fc0ed920b1d23b3ac493ede0a869b3531e8`.
- Tag target: `hydro-model-02-d1-rc1^{}` = `cc6936d9d48d64c46a78ba85bed77c473e20cff3`.
- Post-merge `main` CI: GitHub Actions run `33105713834`, all four jobs passed.

The protection was configured before PR #10 was merged. D2 must retain these four
D1 checks; future D2 checks may be added only after their real check-context names
have completed successfully.

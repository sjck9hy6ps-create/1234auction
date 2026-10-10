---
name: auction-app-workflow
description: How the 1234auction app is deployed and how changes now ship (local clone + gh push)
metadata:
  type: project
---

App: https://1234auction.vercel.app. GitHub repo sjck9hy6ps-create/1234auction (public) auto-deploys to Vercel on push to main; GitHub Actions runs scripts in scripts/; Supabase backend.

Since 2026-10-01 the repo is cloned at `/Users/alex/Downloads/Cowork task Personal auction app 2026-09-30/1234auction` and GitHub CLI is at `../.tools/gh_2.102.0_macOS_arm64/bin/gh` (logged in as sjck9hy6ps-create, `gh auth setup-git` done; git/gh network calls need the sandbox disabled). Repo paths: public/index.html, api/*.js, scripts/*.mjs, .github/workflows/*.yml. The old `outputs/` folder is the Cowork-era copy — edit the repo instead.

The user asked Claude to edit, commit and push itself (no more copy-paste), and to trigger/inspect Actions runs via gh (`gh workflow run`, `gh run view --log`). Pushing to main deploys to production, so say what was pushed each time. Commit author: srreuk <sjck9hy6ps@privaterelay.appleid.com>. See [[deliver-full-files]] (superseded for normal changes).

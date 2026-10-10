---
name: deliver-full-files
description: "User needs complete modified files, never find/replace patches or diffs"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e40deffb-5e35-4dd6-a1f1-5fe116791dc5
  modified: 2026-09-30T13:32:27.473Z
---

SUPERSEDED 2026-10-01: repo is now cloned locally and Claude pushes directly (see [[auction-app-workflow]]); only use the steps below if the user must apply a change by hand.

Always deliver the complete, fully-updated file content for every changed file — never "find X, replace with Y" patch instructions.

**Why:** The user (근수, non-developer) finds locating and editing code sections difficult; they copy whole files into their GitHub repo (1234auction) by hand. In Cowork they always received full files.

**How to apply (updated 2026-10-01):** Attached file cards were hard for the user to apply. For files under ~300 lines, paste the full content in a chat code block (copy button) plus the direct GitHub edit link https://github.com/sjck9hy6ps-create/1234auction/edit/main/<path>. Never write repo paths like scripts/x.mjs as markdown links — the app opens them locally and shows 'file not found'. Big files (index.html, data-coverage.js) can't be pasted; propose connecting the repo locally so Claude can commit/push. Previously: After editing a file in `outputs/`, send the whole file via SendUserFile (large files like data-coverage.js ~240KB are too big to paste in chat); paste full content in chat only for small files. Tell them which repo path it goes to (api/, scripts/, root index.html). See [[auction-app-workflow]].

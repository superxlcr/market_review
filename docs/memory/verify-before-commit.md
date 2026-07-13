---
name: verify-before-commit
description: "Don't commit code changes until user has verified they work"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 562434d4-216b-4bec-8992-0ef2fa32705d
---

Don't commit code changes until the user has explicitly verified the changes work correctly. Restart/refresh first, let them check, then commit.

**Why:** User wants to confirm changes are correct before they're locked into git history. Avoids wasted commits and reverts.

**How to apply:** After making code changes, restart the dashboard (or run the relevant verification), tell the user it's ready, and wait for their confirmation before committing.

<!-- The recovery table of the multi-agent lanes design, section 5.5 (land one
lane at a time), copied verbatim for test_lanes_recovery.py. One test case per row. -->

**Recovery** (re-run `land` with the same `op`; uncertainty refuses rather than guesses):

| Crash point | Recovery |
|---|---|
| A lease or the registry lock held by an exited process | The OS released it. |
| Step 1, journal written, card still `active` | Resume the freeze, or abandon the op. The card has no `op`, so nothing is reserved twice. |
| Step 1 done, before step 4 | Remove the candidate; set the card back to `active`. Nothing in the lane changed. |
| Steps 4–5 | Rebuild the candidate from the kept refs. Evidence and verdicts count only for the same tree id of `T`. |
| Step 6 | Nothing to recover: `ready` waits for authority without a lock. |
| Step 7, ref not updated | The `published: started` entry and the reflog decide (`commit_batch.py` lines 1054, 1070). `main` still `P`: publish again. |
| Step 7, ref updated, record missing | `commit_batch.py` recognizes `P → C` in the reflog and finishes; it never publishes twice. An unclear reflog refuses `publication_unclear` for the human. |
| Step 8 partly done | Resume the sync. A path at neither `P` nor `C` stops the land. |
| Step 9 | Close idempotently. Never touch a card with another generation or `op`. |

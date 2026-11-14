---
name: expert-pass
description: The packet for one expert pass on a set of briefs before the human sees them (HDP §5a). The reviewer reads only and asks three questions.
---

# Expert Pass

Use this packet when HDP §5a applies: a set of Decision Briefs goes to the human at a planned
stop. Send it to the advisory peer reviewer (`peer_reviewer`) in a fresh context. The routing
row is in the Quick decision guide of `.agent/docs/model-routing.md`.

## Packet

Fill in the five parts and send them as the prompt.

1. **Domain.** The domain of the decisions, and the role: "You are a senior practitioner of
   <domain>."
2. **Stage.** Two or three lines: who does the work, the present size, and what does not exist
   yet. Mark each number "measured" or "assumed".
3. **Paths.** The paths of the briefs and of the files that the briefs cite, with line ranges.
4. **The three questions.** For each recommendation: Does it add work that the present stage
   does not need? Can it be done as written, at the present size? Can it be undone? Does each
   thing that the brief names exist? If the brief lists no cheaper option, what is one?
5. **Result form.** For each brief, return one result: holds, cut down, changed or widened.
   Give a reason of two or three sentences and the evidence (`file:line` or a URL). Mark a claim
   that has no evidence "inference". "Holds" is a valid result.

End the packet with this line: "Read only. Do not edit, write or create a file. Return the
result as text."

## After the pass

- Save the result to a receipt.
- Check each finding against the files, and check that each thing the reviewer names exists
  (HDP §5a step 5).
- Write the set line and the per-brief lines of HDP §5a step 6.
- The pass is advice. It makes no ruling and writes no verdict file.

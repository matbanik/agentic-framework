# {Provider} Deep Research — {Topic Title}

## Current Capabilities (verified {VERIFIED_DATE})
{MODEL_LINE — "Expected model: <picker_label> (<basis>). State in your report which model
 actually ran." The basis is the snapshot's Model verdict in one clause: the vendor's own
 statement of the research engine, or "selected in the model picker; <vendor> does not say which
 model runs deep research". When picker_label is `unknown`: "Expected model: not named by
 <vendor>. State in your report which model actually ran." Never tell the portal what model it
 is or runs on, and never write "the latest model".}
Available to you: {CAPABILITIES — snapshot Portal Affordances that matter for this topic}.
Known constraints: {CONSTRAINTS — snapshot Constraints that matter for this topic}.
{NEW_CAPABILITY_DIRECTIVE — one line telling the model to actually use a newly added
 affordance, present only when the snapshot's Delta section ADDED one}

## Portal Setup
For the human, before pasting this prompt:
{PORTAL_STEPS — from the lens template, each step backed by a snapshot claim}

## Context
{TOPIC_CONTEXT — 3–6 sentences from the Step 3 topic search, with dated URLs}

## Research Objective
{PROVIDER_SPECIFIC_OBJECTIVE — the lens template's Objective emphasis applied to this topic}

## Deliverable
{DELIVERABLE — from the lens template}

## Expected Research Plan
{RESEARCH_PLAN — from the lens template: the steps the portal's proposed plan must contain.
 The human edits the portal's plan until every step is there.}

## Required Output Structure
Use these headings, in this order:
{OUTPUT_HEADINGS — a bulleted list of the answer's headings, each in backticks so it does not
 become a heading of this prompt; the last one is `## Sources`}

## Evidence Rules
- Put the source URL and its publication date inline with every factual claim.
- Tag every insight with the attribution tag of the model that produced it: [GPT], [Gemini] or
  [Claude]. Use your own tag only: {ATTRIBUTION_TAG}.
- Mark every number you derived or projected yourself with [ESTIMATED], and every claim you
  could not confirm in a source with [UNVERIFIED]. Do not omit such claims; mark them.
- Where sources conflict, give both, say which is better supported and why.
- Follow the Required Output Structure exactly.
- End with a ## Sources section that lists every URL used, one per line, with its date.

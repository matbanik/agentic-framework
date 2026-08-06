# Natural Writing Guide

> **Scope**: Project-wide mandatory guide for all AI-generated prose — blog posts, Bits, social drafts, translations, hooks, and creative writing.
>
> **Core principle**: Make prose specific, situated, rhythmically alive, and honest about what the author actually knows.

---

## The Core Problem

AI defaults to "corporate mid" — uniform sentence lengths, hedged opinions, formulaic transitions, and zero personality. Readers feel it instantly, even if they can't name why. The fix isn't one trick — it's structural.

Two metrics explain everything:
- **Perplexity** — how predictable each word choice is. AI picks the obvious word. Humans pick the *expressive* word.
- **Burstiness** — how much sentence length varies. AI writes 15–25 word sentences like a metronome. Humans alternate between 4-word punches and 30-word explorations.

---

## Match the Genre First

Natural does not always mean chatty. Adjust the dial:

| Genre | Register | What "natural" means here |
|-------|----------|--------------------------|
| Blog narrative | Conversational, first-person | Coffee-shop explanation to a smart friend |
| Technical setup notes | Clear, direct, respectful of reader intelligence | Someone who's done it before walking you through the steps |
| Medical/safety disclaimers | Plain but precise | Direct factual statements — no corporate legalese, but no casualness that weakens the warning |
| Field Cards (reference) | Dense, scan-friendly | A colleague handing you a cheat sheet, not telling you a story |
| Social posts | Typed, not drafted | Someone who just experienced, observed, argued, or noticed something and wants to share it |
| Translations | Spirit-matched to source | Preserve the rhythm, register, and personality of the English original in target-language idiom |

> **Rule**: Read the genre row before drafting. The techniques below serve the genre, not the other way around.

---

## Audit Flags

Flag these during editing. They are AI fingerprints when used as generic filler — but **keep them when they are technically necessary, genuinely idiomatic, or convey real uncertainty**.

### Words to Flag
`delve` · `utilize` · `leverage` · `synergy` · `cutting-edge` · `game-changer` · `paradigm` · `transformative` · `empower` · `harness` · `elevate` · `unleash` · `embark` · `realm` · `holistic` · `streamline` · `best-in-class` · `it is worth noting` · `in today's world` · `certainly` · `indeed`

### Transitions to Flag
`Furthermore` · `Moreover` · `Additionally` · `In addition` · `In conclusion` · `To sum up` · `In summary` · `It's worth noting that...` · `It's important to mention...` · `Interestingly enough...`

> **Keep when justified**: "Additionally" in a numbered list of genuinely separate items is fine. "Furthermore" connecting a real logical extension is fine. The problem is reflexive insertion, not the token itself.

### Phrases to Flag
- "It's important to note that..."
- "Additionally, it's worth considering..."
- "Let's explore / dive into / delve into..."
- "In the ever-evolving landscape of..."
- "There are various perspectives to consider..."

### Patterns to Flag
- Every sentence 15–25 words (the metronome)
- Paragraphs all the same length in a row
- Lazy hedging: "may," "might," "could potentially" used to avoid committing to a known fact
- On-the-one-hand / on-the-other-hand false balance
- Generic examples that any competitor could write
- Zero first-person perspective (when source material supports it)

> [!IMPORTANT]
> **Protect factual uncertainty.** Do NOT remove hedging when it represents real uncertainty, risk, probability, evidence limits, or medical/legal caution. "This variant *may* increase risk" is honest science. "This approach *may* be helpful" as a way to avoid having an opinion is filler. The difference matters.

---

## What Works Instead

### 1. Vary Sentence Length Drastically

This is the single highest-impact fix. Short punches. Then a longer sentence that takes its time, winds through a thought, and lands somewhere you didn't expect. Then another short one.

**Before** (AI default):
> Understanding enzyme status can provide valuable insights into medication efficacy. This information can be particularly relevant when discussing treatment options with your healthcare provider.

**After** (human):
> You have enzymes that break down drugs. Some of yours work differently than most people's. That means the standard dose of one drug might not work for you at all, while a half-dose of another might hit you like a full one. Your prescriber may not know this about you. You can bring it to them.

### 2. Use Contractions

"It is" → "it's". "They would not" → "they wouldn't". AI avoids contractions at a measurably higher rate than humans. Switching is mechanical but effective.

> **For translations**: Use the target-language equivalent of informal register. This means informal "you" (tú/du/tu/ty), informal verb forms, and natural spoken contractions where the language supports them. Not every language has English-style contractions — the goal is *spoken-register naturalness*, not literal contraction mapping.

### 3. Commit to Your Points (When You Can)

Say "this works" instead of "this may work" — *when the evidence supports it*. Have a take. AI presents balanced views on everything. Humans commit.

**Weak**: "This approach could potentially be beneficial for some users."
**Strong**: "This is better. Here's why."

> **Exception**: For medical, scientific, financial, and safety content, uncertainty is often the honest position. "CYP2D6 poor metabolizers *may* experience reduced codeine efficacy" is correct pharmacogenomics — don't flatten it to "codeine won't work." Commit to what you know; hedge what you genuinely don't.

### 4. Use First Person (When Backed by Source Material)

"I tested this." "In my experience." "Here's what I found." AI almost never writes in first person unless forced. Adding "I" instantly signals a human author.

> [!CAUTION]
> **Never invent lived experience.** Use first person only when source notes, user input, actual testing logs, or author history support it. If the source material lacks a personal detail, ask for it, mark it with `[EXPERIENCE NEEDED: what's missing]`, or write around it honestly. Do not fabricate anecdotes, dates, reactions, or tool outputs to sound human.

### 5. Add Specific, Observable Details

Not "many people have found this useful" but "the CYP2D6 result came back with three specific alleles flagged." Specificity — tool names, data points, observable outcomes — is something AI struggles to generate convincingly.

> **Guardrail**: Only use details the author could plausibly know from source material, research notes, or documented testing. Do not invent "slightly odd details" for flavor. Concrete and real beats colorful and fabricated.

### 6. Break Perfect Flow Intentionally (In Moderation)

Start a sentence with "But." Or "And." Use a one-word sentence for emphasis. A fragment after a key point. A parenthetical aside that shows your thought process.

> **Constraint**: Do not add quirks mechanically. If two consecutive sections use the same casual move (e.g., both start with "But."), remove one. The goal is natural variation, not a costume.

### 7. Cut the Reflexive Transitions

Search for "Furthermore," "Moreover," "Additionally," "In conclusion." If they're just filler connecting sentences that would flow fine without them, delete them. Sometimes the best transition is no transition at all.

> **Keep when earned**: A "However," that genuinely signals a contradiction. An "Additionally," introducing a truly separate, parallel point in a list. The test: does removing it make the logic unclear? If yes, keep it.

### 8. Let Personality Show

Small conversational markers: "honestly," "here's the thing," "look." A few of these soften the tone and make readers feel like they're listening to a person. But don't overdo it — one or two per section max.

### 9. Read It Out Loud

If a sentence sounds stiff when spoken, it reads stiff. Your ear catches what your eyes miss. If you wouldn't say it to a friend over coffee, rewrite it.

> **Genre check**: For Field Cards and technical reference, the test is "would a knowledgeable colleague say this?" not "would I say this at a bar?"

### 10. Allow Imperfection (Don't Manufacture It)

When the text feels too polished, loosen it up. Drop the corporate tone, trim the jargon, let it sound like someone thinking out loud.

> **But**: Do not add imperfection artificially. If two fragments in a row feel forced, they are. Real beats performed-real every time.

---

## The Human Writing Test

A paragraph feels human when:

- It has a reason to exist.
- It says one concrete thing, not a cloud of adjacent ideas.
- It includes a stake, tradeoff, surprise, or friction.
- It uses examples the author could plausibly know.
- It sounds like someone making a judgment, not summarizing consensus.

If a paragraph passes none of these, cut or rewrite it.

---

## The "Do Not Fake It" Rule

> [!CAUTION]
> **Never invent lived experience, test results, dates, tool outputs, personal reactions, or author opinions to sound human.** If the source material lacks a detail, you have three options:
> 1. Ask for it (mark with `[EXPERIENCE NEEDED: what's missing]`)
> 2. Write around it honestly ("The documentation shows..." instead of "I found that...")
> 3. Use concrete observable details from the source material without pretending they're personal experience

This rule overrides every other instruction in this guide. Authenticity means honesty about what we actually know, not performance of knowing.

---

## The Writing Prompt Template

Use this as a system-level instruction when drafting. Adapt for genre (see genre table above):

```
Write as a knowledgeable person explaining this to a smart friend — not delivering a presentation or writing copy.

Rules:
- Match the genre first. Blog narrative = conversational. Technical docs = clear and direct. Reference = scan-friendly.
- Vary sentence length drastically. One sentence. Then a longer one that explores the idea.
- Commit to your points when the evidence supports it. "This works" not "this may work." But preserve genuine uncertainty — don't flatten real hedges.
- Use contractions. "It's" not "it is."
- Include specific details from source material — real tool names, real outputs, real numbers.
- Break perfect flow intentionally, but don't manufacture quirks. One fragment is emphasis; three fragments is a costume.
- Reduce signposting. Don't say "let's explore three aspects" — just explore them.
- Let personality show where natural. Have opinions. Use the occasional aside. But don't force casual markers into every paragraph.
- Use first person only when source material supports it. Never invent personal experience.

Avoid:
- "It's important to note that..." / "Additionally, it's worth considering..."
- "Let's explore / dive into / delve into..."
- Lazy hedging — "may," "might," "could" used to avoid having an opinion (keep when representing real uncertainty)
- Perfectly uniform paragraph lengths
- Corporate buzzwords used as filler (leverage, synergy, robust, streamline)
- Formulaic transitions (Furthermore, Moreover, Additionally) — keep only when they serve genuine logic
- Overusing em dashes — one or two per section max
- Fabricated first-person details, anecdotes, dates, or tool outputs

Tone: Expert but approachable. Like a smart colleague explaining something at a whiteboard, not a consultant writing a report.
```

---

## The Editing Checklist

Before publishing, verify:

- [ ] Do adjacent paragraphs have the same shape, rhythm, and length? If yes, vary one.
- [ ] Zero instances of reflexive "Furthermore," "Moreover," or "Additionally" (kept only when logically necessary)?
- [ ] First-person references are backed by source material (not fabricated)?
- [ ] At least one specific, verifiable detail per section (name, number, tool, outcome)?
- [ ] Would you actually say this out loud to someone?
- [ ] Does it commit to its points where evidence permits, and hedge only where uncertainty is real?
- [ ] Are there contractions throughout (or target-language informal register for translations)?
- [ ] For narrative posts: is the opening hook a feeling or a situation — not a definition? (For technical/reference/safety content, a clear problem statement or definition is fine)
- [ ] Are transitions logical (from proximity or context) rather than mechanical?
- [ ] Does the genre register match? (Conversational for blogs, direct for reference, precise for medical/safety)

---

## Translation Application

The principles in this guide apply to all 8 active languages, but adapted for each language's natural idiom:

| English Principle | Translation Equivalent |
|-------------------|----------------------|
| Use contractions | Use informal register and spoken-form naturalness in target language |
| Audit flagged transitions | Flag target-language equivalents of formulaic connectors (e.g., "darüber hinaus" in German, "de plus" in French) |
| Vary sentence length | Same in all languages — burstiness is universal |
| First person ("I") | Maintain first-person perspective. In pronoun-drop languages (es, pt, ja), the verb conjugation or context carries the "I" — don't force an explicit pronoun where the language doesn't need one |
| Informal "you" | Use informal second person: tú (es), du (de), tu (fr/pt), ty (cs), तुम (hi). For Japanese: preserve informal register through verb endings and sentence-final particles (だ/よ/ね) rather than forcing あなた, which sounds unnatural in conversational Japanese |
| Conversational markers | Find target-language equivalents ("oye" not literal "look," "schau mal" not literal "here's the thing") |
| Coffee shop test | "Would a native speaker say this to a friend?" — same test, target language |

> Do not apply English-specific rules literally in other languages. The goal is *the same spirit* in natural target-language prose.

---

## Key Sources

Research from Exa neural searches and web research:

| Source | Best Insight |
|--------|-------------|
| [garrettlanders.com](https://garrettlanders.com/humanize-ai-content/) | "When the AI is told how to sound, it shifts from copying structure to copying rhythm" |
| [humanizethisai.com](https://humanizethisai.com/md/blog/rewrite-ai-text-sound-human.md) | Kill-list of transition words; 5-step editing workflow |
| [atomwriter.com](https://www.atomwriter.com/blog/make-ai-content-sound-human/) | Perplexity + burstiness as measurable metrics |
| [prompts.chat "PlainTalk"](https://prompts.chat/prompts/cmlfumwr90001k0045t3rlxgz_make-ai-write-naturally) | Copy-paste system prompt for everyday language |
| [aidly.me](https://aidly.me/blog/prompt-human-sounding-ai-text) | "Mild asymmetry" + "commit to your points" prompt template |
| [jvns.ca](https://jvns.ca/blog/2021/05/24/blog-about-what-you-ve-struggled-with/) | "Blog about what you've struggled with" — authenticity from real experience |
| [lindsaybrunner.com](https://lindsaybrunner.com/thoughts/2025-06-14/developer-content-conversation-not-broadcast/) | "Good developer content isn't a lecture, it's banter" |
| [adventures.michaelfbryan.com](https://adventures.michaelfbryan.com/posts/writing-technical-content/) | "Conversational authority" — conspiratorial asides build rapport |
| [masterprompting.net](https://masterprompting.net/blog/how-to-write-system-prompt-non-developers) | "Write like a knowledgeable colleague, not a formal report" |

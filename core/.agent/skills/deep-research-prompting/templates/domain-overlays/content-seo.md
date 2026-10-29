# Domain Overlay — Content & SEO Niche Discovery

Use this overlay when the topic is a content vertical (a hobby, a niche or a subject area) that a
blog or newsletter wants to enter. It adds content-strategy depth to the three lens templates; it
replaces nothing in them. The snapshot still decides the model line, the portal steps and every
capability claim (§4, §5), and the skeleton's Evidence Rules stay as they are.

## Slots

| Slot | Meaning | Source |
|---|---|---|
| `{VERTICAL}` | The vertical being researched, e.g. `archery` | Topic or the project's brief |
| `{OTHER_VERTICALS}` | The publication's other verticals, for intersection scoring | Project stub |
| `{BRIEF}` | The project's scope brief (audience, goal, experience seeds), if it keeps one | Project stub |
| `{YEAR}` | The current year, in context queries only | System clock (Step 1) |

Fold `{BRIEF}` into `{TOPIC_CONTEXT}` together with the Step 3 search results. The portal cannot
read the project, so restate the brief inline.

## How to apply

For each provider, append the overlay's **Objective additions** to
`{PROVIDER_SPECIFIC_OBJECTIVE}`, its **Plan steps** to `{RESEARCH_PLAN}` and its **Output
headings** to `{OUTPUT_HEADINGS}` (before `## Sources`). Run the **Context queries** in Step 3,
within the search budget. Keep the overlap rule: every prompt still covers the vertical's main
pain points, so the answers can be triangulated.

Every prompt also gets one **AI-differentiation line** per recommended topic: what a writer's own
experience adds that a chat assistant's answer cannot. If an assistant would give a reader 80% or
more of the article's value, the topic needs substantial first-hand experience, or it is dropped.

---

## D1 — Competition & pain points (ChatGPT lens)

**Context queries**
- `"{VERTICAL}" frustrations site:reddit.com`; `"{VERTICAL}" advice is wrong OR myths`;
  `"{VERTICAL}" what nobody tells you`
- `"{VERTICAL}" keyword difficulty SEO {YEAR}`; `"{VERTICAL}" beginner guide content saturation`
- `"{VERTICAL}" blog top rated OR best`; `"{VERTICAL}" newsletter Substack popular`;
  `"{VERTICAL}" content missing OR gap OR "no one talks about"`

**Objective additions**
- Pain points: questions asked again and again on forums with no good answer; frustration with
  current advice; advice the community calls outdated or wrong. For each: prevalence
  (common / moderate / niche), direction (rising / stable / declining), the platform where it is
  most discussed, and two post-title ideas.
- Keyword and intent landscape: cluster keywords by intent (informational, commercial,
  navigational). Per cluster: the top 5 keywords with estimated monthly search volume, a
  saturation score from 1 (blue ocean) to 10, and the user journey from problem search to action.
  Name the "bridge" content that links under-served clusters to high-volume ones.
- Competitor audit: the top 10 blogs and newsletters for the vertical, each with estimated
  traffic, content depth, posting frequency, strengths and misses. Name the topics no competitor
  covers well.
- Niche foothold scoring for each recommended topic, as a table:
  `Topic | Est. search volume | allintitle count | KGR | Top-SERP quality | First-mover window`.
  KGR (allintitle count ÷ monthly search volume) below 0.25 is high priority, 0.25–1.0 moderate,
  above 1.0 skip for now. The first-mover window is how long until authority sites notice the
  topic.

**Plan steps**
- Mine forum pain points and unanswered questions, with counts and quoted excerpts.
- Cluster keywords by intent and score saturation per cluster.
- Audit the top 10 competitors and list their gaps.
- Score each recommended topic for foothold (KGR table).

**Output headings**: `## Pain Points`, `## Keyword Clusters`, `## Competitor Audit`,
`## Niche Foothold Scores`

---

## D2 — Trends & communities (Gemini lens)

**Context queries**
- `"{VERTICAL}" Google Trends {YEAR}`; `"{VERTICAL}" rising OR trending {YEAR}`;
  `"{VERTICAL}" new product OR gear {YEAR}`; `"{VERTICAL}" new regulations OR policy changes`
- `"{VERTICAL}" site:reddit.com subreddit`; `"{VERTICAL}" forum OR community -reddit`;
  `"{VERTICAL}" podcast top rated`

**Objective additions**
- Trend velocity: 10 or more subtopics, products or approaches inside the vertical, each with a
  lifecycle stage: Alpha (under 1 year, niche forums only), Breakout (1–2 years, reaching
  mainstream), Mainstream (3+ years, crowded) or Decline. Table:
  `Topic | Stage | Velocity | Search trend (YoY) | Opportunity score`.
- For the top 5 Alpha or Breakout topics: the event or product driving interest, permanent shift
  or cycle, and links to other verticals. Name the topics that will be competitive in 6–12 months;
  those are the foothold targets.
- Community map: subreddits (subscribers, post frequency, fastest month-on-month growth), forums
  outside Reddit, and the top 5 podcasts. Per community: posts per day, sentiment (supportive /
  critical / experimental) and the recurring question a post could answer definitively.
- Leading indicators: product launches creating search demand, regulatory changes, influencer
  adoption spikes, price drops that open the niche to a wider audience.

**Plan steps**
- Place each subtopic on the lifecycle and date the evidence for its stage.
- Map the communities and their recurring questions.
- Flag leading indicators from the last 6 months.

**Output headings**: `## Lifecycle Matrix`, `## Foothold Targets`, `## Community Map`,
`## Leading Indicators`

---

## D3 — Strategy & differentiation (Claude lens)

**Context queries**
- `"{VERTICAL}" cliche OR overused advice`; `"{VERTICAL}" myths debunked OR outdated`;
  `"{VERTICAL}" tools OR calculators OR comparison`
- `"{VERTICAL}" AND "{OTHER_VERTICAL}" blog` for each of `{OTHER_VERTICALS}`
- `"{VERTICAL}" pillar page topic cluster`; `"{VERTICAL}" low competition keywords {YEAR}`

**Objective additions**
- ERRC grid for the publication's content, not for a product: Eliminate (overused formats,
  outdated advice competitors repeat, content that adds noise and ranks poorly — each with example
  URLs), Reduce (over-explained basics that saturate results, production effort that does not
  move rankings), Raise (evidence-based claims with citations, actionable specificity, depth of
  first-hand experience), Create (tools, calculators, comparison tables, cross-vertical insight,
  data-driven experiment posts — each with an MVP format and an effort level).
- Cross-vertical intersections with each of `{OTHER_VERTICALS}`. Table:
  `Intersection | Example topic | Competition | Demand evidence | Score`. Flag the intersections no
  existing site covers, that serve both audiences, and whose cross-links strengthen both clusters.
- Topic cluster architecture: one pillar page and 8–12 cluster articles, ordered lowest
  competition first, with the internal-linking plan. Table:
  `Article | Target keyword | Est. competition | Depends on | Priority`.
- Niche saturation: current saturation (1–10), the number of authority sites (DR above 50), the
  months until the niche is crowded, and the publishing pace needed to hold a foothold before then.
- AI commodity test for each recommended topic (see How to apply).

**Plan steps**
- Build the ERRC grid from the evidence, with example URLs for each Eliminate item.
- Score the cross-vertical intersections.
- Design the pillar and cluster architecture and its build order.
- Assess saturation and apply the AI commodity test to each topic.

**Output headings**: `## ERRC Grid`, `## Cross-Vertical Intersections`,
`## Topic Cluster Architecture`, `## Saturation & AI Commodity Test`

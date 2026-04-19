import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import { FACULTY } from "@/lib/faculty";

// GET reports whether the server already has a key configured. Used by the
// client to decide whether to prompt the visitor for their own key.
export async function GET() {
  return NextResponse.json({ serverKey: !!process.env.ANTHROPIC_API_KEY });
}

type MatchOut = { matches: { id: string; rationale: string }[] };

const MODEL = "claude-haiku-4-5-20251001";

// How many pre-filtered candidates to send to Claude. Rate-limit budget on
// Haiku tier 1 is 50k input tokens/min; ~150 compact records is ~25k tokens.
const SHORTLIST_SIZE = 150;

const STOPWORDS = new Set([
  "a","an","and","are","as","at","be","by","for","from","has","have","in","into",
  "is","it","of","on","or","that","the","this","to","was","were","will","with",
  "we","our","its","their","they","i","my","you","your","can","could","would",
  "should","but","not","no","do","does","did","using","use","used","based",
  "about","more","some","any","other","many","new","study","studies","research",
  "project","work","interest","interests","area","areas","topic","topics",
  "looking","find","want","wants","need","needs","develop","developing",
]);

function tokenize(s: string): string[] {
  return (s.toLowerCase().match(/[a-z][a-z-]+/g) ?? [])
    .filter((t) => t.length > 2 && !STOPWORDS.has(t));
}

function shortlist(query: string) {
  // Simple token-overlap scoring with a small boost for research_areas (the
  // most specific signal) and a tiny boost for title. Strong matches in
  // summary contribute too but are diluted by length.
  const qTokens = new Set(tokenize(query));
  if (qTokens.size === 0) {
    return FACULTY.slice(0, SHORTLIST_SIZE);
  }
  const scored = FACULTY.map((f) => {
    const areas = (f.research_areas ?? []).join(" ").toLowerCase();
    const summary = (f.summary ?? "").toLowerCase();
    const title = (f.title ?? "").toLowerCase();
    const roles = (f.roles ?? []).join(" ").toLowerCase();
    let score = 0;
    for (const t of qTokens) {
      if (areas.includes(t)) score += 5;
      if (roles.includes(t)) score += 2;
      if (title.includes(t)) score += 1;
      if (summary.includes(t)) score += 1;
    }
    return { f, score };
  });
  scored.sort((a, b) => b.score - a.score);
  // If nothing matched at all, fall back to a random slice so we still send
  // *something* — otherwise the user's broad/off-domain query returns empty.
  if (scored[0].score === 0) return FACULTY.slice(0, SHORTLIST_SIZE);
  return scored.slice(0, SHORTLIST_SIZE).map((s) => s.f);
}

function compactDirectory(records: typeof FACULTY) {
  return records.map((f) => ({
    id: f.id,
    name: f.name,
    institution: f.institution,
    department: f.department ?? "",
    title: f.title ?? "",
    research_areas: (f.research_areas ?? []).slice(0, 8),
    summary: (f.summary ?? "").slice(0, 500),
  }));
}

export async function POST(req: NextRequest) {
  let project = "";
  try {
    ({ project } = await req.json());
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  if (!project || typeof project !== "string") {
    return NextResponse.json({ error: "missing project" }, { status: 400 });
  }

  const userKey = req.headers.get("x-anthropic-key") || undefined;
  const apiKey = userKey || process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "No Anthropic API key available. Paste one on the AI Match page." },
      { status: 400 },
    );
  }

  const client = new Anthropic({ apiKey });

  const directory = compactDirectory(shortlist(project));

  const system = `You rank potential academic collaborators for a researcher based in Singapore.
You will receive (a) a project description and (b) a JSON array of faculty records.
Return STRICT JSON matching this schema:
  { "matches": [ { "id": "<faculty id>", "rationale": "<one sentence>" } ] }
Rules:
- Return exactly 10 matches unless the directory has fewer than 10 records.
- Only use ids that appear in the directory.
- Rationale must be one concrete sentence (<= 30 words) explaining the specific overlap: shared methods, systems, diseases, organisms, or techniques.
- Prefer stronger specificity over seniority. If a record has no research_areas or summary, use it only if nothing better fits.
- Do not include prose, markdown, or code fences — JSON only.`;

  // Prompt caching: the directory is identical across visitors, so we mark it
  // as a cache breakpoint. The project description comes AFTER the cache point
  // so each query reuses the cached directory (>=1024 tokens required for a
  // cache hit; we're well over that).
  const directoryText = `DIRECTORY (JSON):\n${JSON.stringify(directory)}`;
  const projectText = `\n\nPROJECT:\n${project.trim()}`;

  try {
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: 2000,
      system,
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: directoryText, cache_control: { type: "ephemeral" } },
            { type: "text", text: projectText },
          ],
        },
      ],
    });
    const text = resp.content
      .map((b) => (b.type === "text" ? b.text : ""))
      .join("")
      .trim();

    // Tolerate stray markdown fences even though we asked for none.
    const stripped = text.replace(/^```(?:json)?\s*|\s*```$/g, "").trim();
    let parsed: MatchOut;
    try {
      parsed = JSON.parse(stripped);
    } catch {
      return NextResponse.json(
        { error: "Model did not return JSON", raw: text },
        { status: 502 },
      );
    }
    // Defensive: drop ids that don't exist in the directory.
    const knownIds = new Set(FACULTY.map((f) => f.id));
    parsed.matches = (parsed.matches ?? []).filter((m) => knownIds.has(m.id)).slice(0, 10);
    return NextResponse.json(parsed);
  } catch (e: any) {
    const msg = e?.error?.message || e?.message || "Upstream error";
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}

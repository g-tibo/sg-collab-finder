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

function compactDirectory() {
  // Keep payload small. We send one line per faculty with just the fields
  // Claude needs to rank relevance. The full record is reattached client-side.
  return FACULTY.map((f) => ({
    id: f.id,
    name: f.name,
    institution: f.institution,
    department: f.department ?? "",
    title: f.title ?? "",
    research_areas: (f.research_areas ?? []).slice(0, 8),
    summary: (f.summary ?? "").slice(0, 600),
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

  const directory = compactDirectory();

  const system = `You rank potential academic collaborators for a researcher based in Singapore.
You will receive (a) a project description and (b) a JSON array of faculty records.
Return STRICT JSON matching this schema:
  { "matches": [ { "id": "<faculty id>", "rationale": "<one sentence>" } ] }
Rules:
- Return exactly 5 matches unless the directory has fewer than 5 records.
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
      max_tokens: 1200,
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
    parsed.matches = (parsed.matches ?? []).filter((m) => knownIds.has(m.id)).slice(0, 5);
    return NextResponse.json(parsed);
  } catch (e: any) {
    const msg = e?.error?.message || e?.message || "Upstream error";
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}

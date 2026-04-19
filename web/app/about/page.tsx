import { FACULTY } from "@/lib/faculty";

const STOPWORDS = new Set([
  "of", "and", "the", "for", "in", "at", "a", "an",
]);

// Derive a short tag (e.g. "SBS", "IMCB") from a department string.
// Prefer a parenthesized acronym; otherwise take initials of capitalized
// significant words.
function deptTag(dept: string): string {
  const parens = [...dept.matchAll(/\(([^)]+)\)/g)].map((m) => m[1].trim());
  for (const p of parens) {
    const inner = [...p.matchAll(/\(([^)]+)\)/g)].map((m) => m[1]);
    if (inner.length) return inner[inner.length - 1];
    // If the parenthesized text is itself a short uppercase-ish acronym, use it.
    if (/^[A-Z][A-Za-z]{1,8}$/.test(p)) return p;
  }
  // Otherwise, initials of capitalized significant words (exclude stopwords).
  const head = dept.split(/[(]/)[0];
  const initials = head
    .split(/\s+/)
    .filter((w) => w && !STOPWORDS.has(w.toLowerCase()) && /^[A-Z]/.test(w))
    .map((w) => w[0])
    .join("");
  return initials || head;
}

function coverageSentence(): string {
  const byInst: Record<string, Set<string>> = {};
  for (const f of FACULTY) {
    const tag = deptTag(f.department ?? "");
    if (!tag) continue;
    (byInst[f.institution] ??= new Set()).add(tag);
  }
  // Stable display order: NTU, NUS, A*STAR first; then alphabetical.
  const order = ["NTU", "NUS", "A*STAR"];
  const insts = Object.keys(byInst).sort((a, b) => {
    const ai = order.indexOf(a);
    const bi = order.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
  const parts = insts.map((inst) => {
    const tags = [...byInst[inst]].sort();
    return `${inst} (${tags.join(", ")})`;
  });
  if (parts.length <= 1) return parts.join("");
  if (parts.length === 2) return parts.join(" and ");
  return parts.slice(0, -1).join(", ") + ", and " + parts[parts.length - 1];
}

export default function AboutPage() {
  const coverage = coverageSentence();

  return (
    <article className="max-w-none">
      <h1 className="text-3xl font-semibold tracking-tight">About</h1>

      <p className="mt-4 text-black/75 dark:text-white/75">
        <strong>SG Collab Finder</strong> is a directory of faculty at Singapore
        research institutions, built to help researchers identify potential
        collaborators. It was inspired by{" "}
        <a
          className="text-accent hover:underline"
          href="https://plen-collab-finder.vercel.app/"
          target="_blank"
          rel="noopener noreferrer"
        >
          plen-collab-finder
        </a>{" "}
        (University of Copenhagen), and adapted for the Singapore ecosystem.
      </p>

      <p className="mt-4 text-black/75 dark:text-white/75">
        It covers faculty at {coverage}. Coverage will continue to expand as
        more institutions are added.
      </p>

      <h2 className="mt-8 text-xl font-semibold">How the matching works</h2>
      <p className="text-black/75 dark:text-white/75">
        When you describe a project on the <a className="text-accent hover:underline" href="/match">AI Match</a> page,
        your description is sent to Anthropic&rsquo;s Claude API along with the
        full directory, which Claude ranks for relevance.
      </p>

      <h2 className="mt-8 text-xl font-semibold">Privacy</h2>
      <p className="text-black/75 dark:text-white/75">
        All profile content here is aggregated from public academic web pages.
        No user accounts, no tracking, no analytics. Your match queries are
        sent to Anthropic&rsquo;s API only for the purpose of generating
        ranked matches, and are not retained by this site. Profiles are a
        snapshot and may be out of date — each card links back to the
        canonical institutional page so you can confirm current affiliation
        and contact details before reaching out.
      </p>

      <h2 className="mt-8 text-xl font-semibold">Corrections and removal</h2>
      <p className="text-black/75 dark:text-white/75">
        If you&rsquo;re listed here and would like your entry corrected or
        removed, email{" "}
        <a className="text-accent hover:underline" href="mailto:thibault@ntu.edu.sg">
          thibault@ntu.edu.sg
        </a>
        . If you know of an institution or department that should be added,
        please get in touch.
      </p>

      <h2 className="mt-8 text-xl font-semibold">Colophon</h2>
      <p className="text-black/75 dark:text-white/75">
        Created and maintained by{" "}
        <a
          className="text-accent hover:underline"
          href="https://www.thibaultlab.com/biography"
          target="_blank"
          rel="noopener noreferrer"
        >
          Guillaume Thibault
        </a>{" "}
        (School of Biological Sciences, Nanyang Technological University).
        Built with Next.js, Tailwind, and the Anthropic SDK.
      </p>
    </article>
  );
}

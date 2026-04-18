import { FACULTY } from "@/lib/faculty";

export default function AboutPage() {
  const byInst: Record<string, number> = {};
  for (const f of FACULTY) byInst[f.institution] = (byInst[f.institution] ?? 0) + 1;

  return (
    <article className="max-w-none">
      <h1 className="text-3xl font-semibold tracking-tight">About</h1>

      <p className="mt-4 text-black/75">
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

      <h2 className="mt-8 text-xl font-semibold">How the matching works</h2>
      <p className="text-black/75">
        When you describe a project on the <a className="text-accent hover:underline" href="/match">AI Match</a> page,
        your description is sent to Anthropic&rsquo;s Claude API along with the
        full directory, which Claude ranks for relevance. Nothing is stored by
        this site — no accounts, no analytics, no query logs.
      </p>

      <h2 className="mt-8 text-xl font-semibold">Current coverage</h2>
      <ul className="text-black/75 list-disc pl-6">
        {Object.entries(byInst).map(([inst, n]) => (
          <li key={inst}>
            <strong>{inst}</strong>: {n} profiles
          </li>
        ))}
      </ul>
      <p className="text-black/60 text-sm">
        v1 covers NTU School of Biological Sciences, A*STAR IMCB, and NUS
        Department of Biological Sciences. Planned expansion: the rest of NTU
        (LKCMedicine, CCEB), NUS (YLLSoM, Pharmacy, Chemistry, Physiology),
        remaining A*STAR RIs, Duke-NUS, TLL, NNI, NCCS, SNEC, and other
        institutions listed on the{" "}
        <a
          className="text-accent hover:underline"
          href="https://en.wikipedia.org/wiki/Category:Research_institutes_in_Singapore"
          target="_blank"
          rel="noopener noreferrer"
        >
          Wikipedia directory
        </a>
        .
      </p>

      <h2 className="mt-8 text-xl font-semibold">Data source</h2>
      <p className="text-black/75">
        Profiles are compiled from public institutional web pages and
        department directories. The data is a snapshot and may be out of date.
        Links point back to the canonical institutional profile so you can
        confirm current affiliation and contact details before reaching out.
      </p>

      <h2 className="mt-8 text-xl font-semibold">Corrections and removal</h2>
      <p className="text-black/75">
        If you&rsquo;re listed here and would like your entry corrected or
        removed, email{" "}
        <a className="text-accent hover:underline" href="mailto:thibault@ntu.edu.sg">
          thibault@ntu.edu.sg
        </a>
        . If you know of an institution or department that should be added,
        please get in touch.
      </p>

      <h2 className="mt-8 text-xl font-semibold">Colophon</h2>
      <p className="text-black/75">
        Built with Next.js, Tailwind, and the Anthropic SDK. Maintained by
        Guillaume Thibault (NTU SBS).
      </p>
    </article>
  );
}

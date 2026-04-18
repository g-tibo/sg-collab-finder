import type { Faculty } from "@/lib/faculty";

// NTU serves images with `Cross-Origin-Resource-Policy: same-site`, which
// blocks cross-origin embedding. Route those through our own /api/img proxy.
// A*STAR and NUS have no such restriction and can be loaded directly.
const HOSTS_NEEDING_PROXY = new Set(["www.ntu.edu.sg"]);

function imgSrc(url: string): string {
  try {
    const u = new URL(url);
    if (HOSTS_NEEDING_PROXY.has(u.host)) {
      return `/api/img?u=${encodeURIComponent(url)}`;
    }
  } catch {
    /* fall through */
  }
  return url;
}

export function FacultyCard({ f, rank, rationale }: { f: Faculty; rank?: number; rationale?: string }) {
  return (
    <article className="rounded-xl border border-black/10 bg-white p-4 flex gap-4 hover:shadow-sm transition-shadow">
      {f.photo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imgSrc(f.photo_url)}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          className="w-20 h-20 rounded-lg object-cover bg-black/5 shrink-0"
        />
      ) : (
        <div className="w-20 h-20 rounded-lg bg-black/5 shrink-0 grid place-items-center text-xs text-black/40">
          no photo
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          {rank !== undefined && (
            <span className="text-xs font-mono bg-accent/10 text-accent px-1.5 py-0.5 rounded">#{rank}</span>
          )}
          <a
            href={f.profile_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium hover:underline"
          >
            {f.name}
          </a>
          {f.title && <span className="text-xs text-black/60">· {f.title}</span>}
        </div>
        <div className="text-xs text-black/60 mt-0.5">
          {f.institution}
          {f.department ? ` · ${f.department}` : ""}
        </div>
        {f.research_areas && f.research_areas.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {f.research_areas.slice(0, 8).map((a) => (
              <span key={a} className="text-[11px] bg-black/5 rounded px-1.5 py-0.5">
                {a}
              </span>
            ))}
          </div>
        )}
        {rationale && (
          <p className="mt-2 text-sm text-black/70 italic">{rationale}</p>
        )}
        {!rationale && f.summary && (
          <p className="mt-2 text-sm text-black/70 line-clamp-3">{f.summary}</p>
        )}
        <div className="mt-2 flex gap-3 text-xs text-black/60">
          {f.email && <a className="hover:underline" href={`mailto:${f.email}`}>{f.email}</a>}
          {f.lab_url && (
            <a className="hover:underline" href={f.lab_url} target="_blank" rel="noopener noreferrer">
              Lab site ↗
            </a>
          )}
          {f.scholar_url && (
            <a className="hover:underline" href={f.scholar_url} target="_blank" rel="noopener noreferrer">
              Scholar ↗
            </a>
          )}
          {f.orcid && (
            <a className="hover:underline" href={f.orcid} target="_blank" rel="noopener noreferrer">
              ORCID ↗
            </a>
          )}
        </div>
      </div>
    </article>
  );
}

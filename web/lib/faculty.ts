import data from "@/public/faculty.json";

export type Faculty = {
  id: string;
  name: string;
  institution: string;
  department?: string;
  title?: string;
  roles?: string[];
  research_areas?: string[];
  summary?: string;
  email?: string;
  profile_url: string;
  lab_url?: string;
  scholar_url?: string;
  orcid?: string;
  photo_url?: string;
};

// Best-effort "last name" extractor for sorting. Names in the directory
// come in several shapes:
//   "Guillaume Thibault", "Antonia Monteiro" (Given Family — Western)
//   "Todd, Peter Alan"                       (Family, Given — comma form)
//   "Sherry Aw", "Qi-Jing Li"                (Given FAMILY → title-cased)
// The rule below handles the comma form explicitly and falls back to the
// last whitespace-separated token, which matches how most researchers are
// looked up in directories.
function lastNameKey(name: string): string {
  // Drop parenthesized content first — some records carry Chinese characters
  // in parens ("Luke Ong (翁之昊)"). Without this, the last whitespace token
  // becomes "(翁之昊)" and the record sorts under "翁" instead of "Ong".
  const stripped = name.replace(/\([^)]*\)/g, " ").replace(/\s+/g, " ").trim();
  if (stripped.includes(",")) {
    return stripped.split(",")[0].trim().toLowerCase();
  }
  const parts = stripped.split(/\s+/);
  return parts[parts.length - 1].toLowerCase();
}

// Sort alphabetically by last name across the whole directory so Browse is
// consistent regardless of whether an institution filter is applied.
export const FACULTY: Faculty[] = (data as Faculty[])
  .slice()
  .sort((a, b) => lastNameKey(a.name).localeCompare(lastNameKey(b.name))
              || a.name.localeCompare(b.name));

export function institutions(): string[] {
  return Array.from(new Set(FACULTY.map((f) => f.institution))).sort();
}

export function departments(institution?: string): string[] {
  const pool = institution ? FACULTY.filter((f) => f.institution === institution) : FACULTY;
  return Array.from(new Set(pool.map((f) => f.department).filter((x): x is string => !!x))).sort();
}

export function search(query: string, filters: { institution?: string; department?: string }): Faculty[] {
  const q = query.trim().toLowerCase();
  return FACULTY.filter((f) => {
    if (filters.institution && f.institution !== filters.institution) return false;
    if (filters.department && f.department !== filters.department) return false;
    if (!q) return true;
    const hay = [
      f.name,
      f.title ?? "",
      f.department ?? "",
      f.institution,
      ...(f.research_areas ?? []),
      ...(f.roles ?? []),
      f.summary ?? "",
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

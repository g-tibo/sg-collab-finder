"use client";

import { useEffect, useState } from "react";
import type { Faculty } from "@/lib/faculty";
import { FACULTY } from "@/lib/faculty";
import { FacultyCard } from "@/components/FacultyCard";

type Match = { id: string; rationale: string };

const KEY_STORAGE = "sg-collab-finder-anthropic-key";

export default function MatchPage() {
  const [project, setProject] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [keyFromServer, setKeyFromServer] = useState<boolean>(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [matches, setMatches] = useState<Match[]>([]);

  useEffect(() => {
    // Check whether the server already has a key configured.
    fetch("/api/match").then(async (r) => {
      const j = await r.json().catch(() => ({ serverKey: false }));
      setKeyFromServer(!!j.serverKey);
    });
    const stored = localStorage.getItem(KEY_STORAGE);
    if (stored) setApiKey(stored);
  }, []);

  async function submit() {
    setError("");
    setMatches([]);
    if (!project.trim()) {
      setError("Describe your project first.");
      return;
    }
    if (!keyFromServer && !apiKey.trim()) {
      setError("Paste an Anthropic API key, or ask the site owner to configure one.");
      return;
    }
    if (apiKey) localStorage.setItem(KEY_STORAGE, apiKey);
    setLoading(true);
    try {
      const r = await fetch("/api/match", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "x-anthropic-key": apiKey } : {}),
        },
        body: JSON.stringify({ project }),
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || `Request failed (${r.status})`);
      }
      const j = (await r.json()) as { matches: Match[] };
      setMatches(j.matches || []);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  const byId = new Map<string, Faculty>(FACULTY.map((f) => [f.id, f]));

  return (
    <>
      <section className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight">AI Collaborator Match</h1>
        <p className="mt-2 text-black/70 dark:text-white/70 max-w-2xl">
          Describe your project, question, or technique. Claude will rank Singapore
          researchers by topical fit and explain why each one might be a good match.
          Your description and the directory are sent to the Anthropic API; nothing
          is stored by this site.
        </p>
      </section>

      <label className="block text-sm font-medium mb-1">Project description</label>
      <textarea
        value={project}
        onChange={(e) => setProject(e.target.value)}
        placeholder="e.g., We're looking for a collaborator who can study ER stress in aging neurons using C. elegans, to complement a new mouse aging cohort we're setting up."
        className="w-full min-h-[160px] rounded-lg border border-black/15 dark:border-white/15 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30"
      />

      {!keyFromServer && (
        <div className="mt-4">
          <label className="block text-sm font-medium mb-1">
            Anthropic API key{" "}
            <span className="text-black/50 dark:text-white/40 font-normal">(stored locally, never sent to this site)</span>
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-ant-…"
            className="w-full rounded-lg border border-black/15 dark:border-white/15 bg-white dark:bg-neutral-900 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      )}

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={submit}
          disabled={loading}
          className="rounded-lg bg-accent text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {loading ? "Finding matches…" : "Find matches"}
        </button>
        {error && <span className="text-sm text-accent">{error}</span>}
      </div>

      {matches.length > 0 && (
        <section className="mt-8">
          <h2 className="text-sm font-medium text-black/60 dark:text-white/60 mb-3">Top matches</h2>
          <div className="grid gap-3">
            {matches.map((m, i) => {
              const f = byId.get(m.id);
              if (!f) return null;
              return <FacultyCard key={m.id} f={f} rank={i + 1} rationale={m.rationale} />;
            })}
          </div>
        </section>
      )}
    </>
  );
}

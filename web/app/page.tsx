"use client";

import { useMemo, useState } from "react";
import { FACULTY, institutions, departments, search } from "@/lib/faculty";
import { FacultyCard } from "@/components/FacultyCard";

export default function BrowsePage() {
  const [q, setQ] = useState("");
  const [inst, setInst] = useState("");
  const [dept, setDept] = useState("");

  const deptOptions = useMemo(() => (inst ? departments(inst) : departments()), [inst]);
  const results = useMemo(
    () => search(q, { institution: inst || undefined, department: dept || undefined }),
    [q, inst, dept],
  );

  return (
    <>
      <section className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">
          Singapore research collaboration finder
        </h1>
        <p className="mt-2 text-black/70 dark:text-white/70 max-w-2xl">
          Browse {FACULTY.length} faculty at NTU, NUS, and A*STAR — or head to{" "}
          <a href="/match" className="text-accent hover:underline">AI Match</a>{" "}
          to describe your project and get ranked suggestions.
        </p>
      </section>

      <section className="mb-4 grid gap-3 md:grid-cols-[1fr_auto_auto]">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search names, departments, keywords…"
          className="rounded-lg border border-black/15 dark:border-white/15 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30"
        />
        <select
          value={inst}
          onChange={(e) => { setInst(e.target.value); setDept(""); }}
          className="rounded-lg border border-black/15 dark:border-white/15 bg-white dark:bg-neutral-900 px-3 py-2 text-sm"
        >
          <option value="">All institutions</option>
          {institutions().map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
        <select
          value={dept}
          onChange={(e) => setDept(e.target.value)}
          className="rounded-lg border border-black/15 dark:border-white/15 bg-white dark:bg-neutral-900 px-3 py-2 text-sm"
        >
          <option value="">All departments</option>
          {deptOptions.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </section>

      <p className="text-xs text-black/50 dark:text-white/40 mb-3">
        {results.length} result{results.length === 1 ? "" : "s"}
      </p>

      <div className="grid gap-3">
        {results.map((f) => <FacultyCard key={f.id} f={f} />)}
      </div>
    </>
  );
}

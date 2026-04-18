import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "SG Collab Finder",
  description:
    "Find research collaborators across Singapore universities and research institutes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <header className="border-b border-black/10 bg-paper/70 backdrop-blur sticky top-0 z-30">
          <div className="mx-auto max-w-5xl px-4 py-3 flex items-center gap-6">
            <Link href="/" className="font-semibold tracking-tight text-lg">
              <span className="text-accent">SG</span> Collab Finder
            </Link>
            <nav className="ml-auto flex items-center gap-5 text-sm">
              <Link className="hover:underline" href="/">Browse</Link>
              <Link className="hover:underline" href="/match">AI Match</Link>
              <Link className="hover:underline" href="/about">About</Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
        <footer className="mx-auto max-w-5xl px-4 py-10 text-xs text-black/50">
          Public directory compiled from institutional pages · no accounts · no tracking.
        </footer>
      </body>
    </html>
  );
}

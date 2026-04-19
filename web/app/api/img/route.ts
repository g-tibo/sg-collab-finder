import { NextRequest, NextResponse } from "next/server";

// Hosts whose images are safe to proxy. Kept explicit to prevent this route
// being abused as an open image proxy.
const ALLOWED_HOSTS = new Set<string>([
  "www.ntu.edu.sg",
  "dr.ntu.edu.sg",
  "www.a-star.edu.sg",
  "www.dbs.nus.edu.sg",
  "www.nus.edu.sg",
]);

export const runtime = "nodejs";
// Cache proxied bytes on Vercel for a day (Next.js fetch cache on the edge).
export const revalidate = 86400;

export async function GET(req: NextRequest) {
  const u = req.nextUrl.searchParams.get("u");
  if (!u) return new NextResponse("missing u", { status: 400 });

  let target: URL;
  try {
    target = new URL(u);
  } catch {
    return new NextResponse("bad url", { status: 400 });
  }
  if (target.protocol !== "https:" || !ALLOWED_HOSTS.has(target.host)) {
    return new NextResponse("host not allowed", { status: 400 });
  }

  const upstream = await fetch(target, {
    // Send a clean UA; never leak the visitor's referer or cookies.
    headers: {
      "User-Agent":
        "Mozilla/5.0 (compatible; SGCollabFinderImgProxy/0.1; +https://github.com/)",
      Accept: "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    },
    // Long edge cache is fine — faculty photos rarely change.
    next: { revalidate: 86400 },
  });

  if (!upstream.ok) {
    return new NextResponse("upstream " + upstream.status, { status: upstream.status });
  }

  const ct = upstream.headers.get("content-type") ?? "image/jpeg";
  const body = await upstream.arrayBuffer();
  return new NextResponse(body, {
    status: 200,
    headers: {
      "Content-Type": ct,
      "Cache-Control": "public, max-age=86400, s-maxage=604800, immutable",
      // Explicitly permit embedding cross-site — overrides upstream's CORP.
      "Cross-Origin-Resource-Policy": "cross-origin",
    },
  });
}

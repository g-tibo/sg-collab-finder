import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "www.ntu.edu.sg" },
      { protocol: "https", hostname: "www.a-star.edu.sg" },
      { protocol: "https", hostname: "www.dbs.nus.edu.sg" },
      { protocol: "https", hostname: "www.nus.edu.sg" },
    ],
  },
};

export default nextConfig;

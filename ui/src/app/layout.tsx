import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "video2reels — AI Short-Form Clip Studio",
  description:
    "Transform long-form videos into scored, captioned, vertical 9:16 clips ready for TikTok, Reels & Shorts.",
  keywords: ["video clips", "AI", "short-form", "reels", "TikTok", "Shorts"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text y='26' font-size='28'>🎬</text></svg>" />
      </head>
      <body>{children}</body>
    </html>
  );
}

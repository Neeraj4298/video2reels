"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Projects", icon: "🎬" },
  { href: "/brand-kits", label: "Brand Kits", icon: "🎨" },
  { href: "/settings", label: "Settings", icon: "⚙️" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">🎬</div>
        <span className="sidebar-logo-text">video2reels</span>
      </div>

      <nav className="sidebar-nav">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-link ${pathname === item.href ? "active" : ""}`}
          >
            <span className="nav-link-icon">{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>

      <div style={{ padding: "0 var(--space-3)" }}>
        <div
          style={{
            background: "rgba(124,58,237,0.08)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            padding: "var(--space-3)",
          }}
        >
          <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "4px" }}>
            API Status
          </p>
          <div className="flex items-center gap-2">
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "var(--green-400)",
                display: "inline-block",
                boxShadow: "0 0 6px var(--green-400)",
              }}
            />
            <span style={{ fontSize: "0.8125rem", color: "var(--green-400)", fontWeight: 600 }}>
              Connected
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}

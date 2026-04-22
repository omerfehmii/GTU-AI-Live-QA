"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getJson } from "@/lib/api";

export function Navbar() {
    const pathname = usePathname();
    const [online, setOnline] = useState(false);

    useEffect(() => {
        let mounted = true;
        async function check() {
            try {
                await getJson<{ status: string }>("/health");
                if (mounted) setOnline(true);
            } catch {
                if (mounted) setOnline(false);
            }
        }
        void check();
        const interval = setInterval(check, 15_000);
        return () => {
            mounted = false;
            clearInterval(interval);
        };
    }, []);

    return (
        <nav className="navbar">
            <Link href="/" className="navbar-brand">
                <span className="brand-dot" />
                GTU <span className="brand-accent">AI Live QA</span>
            </Link>

            <div className="navbar-links">
                <Link
                    href="/"
                    className={`navbar-link${pathname === "/" ? " active" : ""}`}
                >
                    Canlı Görünüm
                </Link>
                <Link
                    href="/admin"
                    className={`navbar-link${pathname === "/admin" ? " active" : ""}`}
                >
                    Admin
                </Link>

                <div className="navbar-status">
                    <span className={`status-dot${online ? "" : " offline"}`} />
                    {online ? "Bağlı" : "Bağlantı yok"}
                </div>
            </div>
        </nav>
    );
}

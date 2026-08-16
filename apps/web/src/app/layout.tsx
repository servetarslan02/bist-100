import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { LiveTicker } from "@/components/ui/LiveTicker";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "ALPHA BIST — Market Intelligence",
  description: "BIST Market Intelligence & Quant Engine",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr" className="dark">
      <body className={`${inter.variable} ${jetbrains.variable} font-sans bg-zinc-950 text-zinc-300 antialiased`}>
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <div className="flex-1 flex flex-col overflow-hidden">
            <LiveTicker />
            <main className="flex-1 overflow-y-auto">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}

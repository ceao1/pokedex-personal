import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Figtree, Martian_Mono } from "next/font/google";
import "./globals.css";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["700", "800"],
  variable: "--font-display",
});

const body = Figtree({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-body",
});

const data = Martian_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-data",
});

export const metadata: Metadata = {
  title: "Pokédex viviente",
  description: "El índice digital de un binder físico de los 151 originales.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#16233a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${display.variable} ${body.variable} ${data.variable}`}>
      <body>{children}</body>
    </html>
  );
}

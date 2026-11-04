import type { Metadata, Viewport } from "next";
import { Inter, Zilla_Slab, Besley } from "next/font/google";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { GeistPixelSquare } from "geist/font/pixel";
import "./globals.css";
import { licensedFontCss } from "@/lib/fonts/licensed";

/*
 * Type system
 * - Inter: marketing body copy, nav and buttons (matches the reference measurement).
 * - Display slab: PP Right Slab, exactly as the reference, when licensed files are present in
 *   public/fonts (see lib/fonts/licensed.ts); otherwise Zilla Slab Light, the closest open face.
 * - Pixel labels: FT Activica when licensed files are present; otherwise Geist Pixel Square.
 * - Geist Sans + Besley: the authenticated application, the same families the reference app uses.
 */
const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });
const slab = Zilla_Slab({
  variable: "--font-slab",
  subsets: ["latin"],
  weight: ["300", "400"],
  display: "swap",
});
const besley = Besley({ variable: "--font-besley", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "Pramana", template: "%s | Pramana" },
  description:
    "Pramana investigates problems that exist only in the physical world. It asks the right people the right questions and turns what they observe into evidence.",
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#0E0E15",
  colorScheme: "dark light",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const licensed = licensedFontCss();
  const vars =
    (licensed.slab ? `--display-slab:"PP Right Slab",var(--font-slab),Georgia,serif;` : "") +
    (licensed.pixel ? `--display-pixel:"FT Activica",var(--font-geist-pixel-square),monospace;` : "");
  return (
    <html
      lang="en"
      className={`${inter.variable} ${slab.variable} ${besley.variable} ${GeistSans.variable} ${GeistMono.variable} ${GeistPixelSquare.variable} antialiased`}
      suppressHydrationWarning
    >
      <head>
        {licensed.css ? <style dangerouslySetInnerHTML={{ __html: `${licensed.css}:root{${vars}}` }} /> : null}
      </head>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}

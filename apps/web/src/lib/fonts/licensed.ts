import { existsSync } from "node:fs";
import path from "node:path";

/**
 * The reference site's display faces are commercial: PP Right Slab (Pangram Pangram) and
 * FT Activica. They cannot be redistributed, so the repository does not contain them.
 *
 * Drop licensed files into apps/web/public/fonts/ with the names below and they are used
 * automatically, ahead of the open-licensed stand-ins (Zilla Slab and Geist Pixel). When
 * the files are absent no @font-face is emitted, so nothing 404s.
 */
const FACES = [
  { family: "PP Right Slab", weight: 300, files: ["PPRightSlab-Light.woff2", "PPRightSlab-Light.woff", "PPRightSlab-Light.otf"] },
  { family: "PP Right Slab", weight: 400, files: ["PPRightSlab-Regular.woff2", "PPRightSlab-Regular.woff", "PPRightSlab-Regular.otf"] },
  { family: "FT Activica", weight: 400, files: ["FTActivica-Regular.woff2", "FTActivica-Regular.woff", "FTActivica-Regular.otf"] },
] as const;

const FORMAT: Record<string, string> = { woff2: "woff2", woff: "woff", otf: "opentype", ttf: "truetype" };

export function licensedFontCss(): { css: string; slab: boolean; pixel: boolean } {
  const dir = path.join(process.cwd(), "public", "fonts");
  let css = "";
  let slab = false;
  let pixel = false;
  for (const face of FACES) {
    const file = face.files.find((f) => existsSync(path.join(dir, f)));
    if (!file) continue;
    const ext = file.split(".").pop()!;
    css += `@font-face{font-family:"${face.family}";src:url("/fonts/${file}") format("${FORMAT[ext]}");font-weight:${face.weight};font-style:normal;font-display:swap;}`;
    if (face.family === "PP Right Slab") slab = true;
    else pixel = true;
  }
  return { css, slab, pixel };
}

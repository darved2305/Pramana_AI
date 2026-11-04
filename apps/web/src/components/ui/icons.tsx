/** Line icons drawn for Pramana on a 20px grid, 1.5px strokes. */
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = (p: P) => ({
  width: 20,
  height: 20,
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  ...p,
});

export const IconGrid = (p: P) => (
  <svg {...base(p)}><rect x="3" y="3" width="5.5" height="5.5" rx="1" /><rect x="11.5" y="3" width="5.5" height="5.5" rx="1" /><rect x="3" y="11.5" width="5.5" height="5.5" rx="1" /><rect x="11.5" y="11.5" width="5.5" height="5.5" rx="1" /></svg>
);
export const IconSearch = (p: P) => (
  <svg {...base(p)}><circle cx="9" cy="9" r="5.5" /><path d="m13 13 4 4" /></svg>
);
export const IconPlus = (p: P) => <svg {...base(p)}><path d="M10 4v12M4 10h12" /></svg>;
export const IconChevronRight = (p: P) => <svg {...base(p)}><path d="m8 5 5 5-5 5" /></svg>;
export const IconChevronDown = (p: P) => <svg {...base(p)}><path d="m5 8 5 5 5-5" /></svg>;
export const IconArrowLeft = (p: P) => <svg {...base(p)}><path d="M16 10H4m5-5-5 5 5 5" /></svg>;
export const IconArrowRight = (p: P) => <svg {...base(p)}><path d="M4 10h12m-5-5 5 5-5 5" /></svg>;
export const IconCollapse = (p: P) => <svg {...base(p)}><path d="M4 4v12M16 10H8m4-4-4 4 4 4" /></svg>;
export const IconExpand = (p: P) => <svg {...base(p)}><path d="M16 4v12M4 10h8m-4-4 4 4-4 4" /></svg>;
export const IconClose = (p: P) => <svg {...base(p)}><path d="m5 5 10 10M15 5 5 15" /></svg>;
export const IconMenu = (p: P) => <svg {...base(p)}><path d="M3 6h14M3 14h14" /></svg>;
export const IconPulse = (p: P) => <svg {...base(p)}><path d="M2 10h3l2-5 3 10 2-6 1.5 3H18" /></svg>;
export const IconUsers = (p: P) => (
  <svg {...base(p)}><circle cx="7.5" cy="7" r="3" /><path d="M2 17c.6-3 2.8-4.5 5.5-4.5S12.4 14 13 17" /><path d="M13 4.2a3 3 0 0 1 0 5.6M15.5 12.8c1.4.6 2.2 2 2.5 4.2" /></svg>
);
export const IconBuilding = (p: P) => (
  <svg {...base(p)}><rect x="4" y="2.5" width="12" height="15" rx="1" /><path d="M7.5 6h1M11.5 6h1M7.5 9.5h1M11.5 9.5h1M8.5 17.5v-3.5h3v3.5" /></svg>
);
export const IconHistory = (p: P) => (
  <svg {...base(p)}><path d="M3.5 10a6.5 6.5 0 1 0 2-4.7L3.5 7.2" /><path d="M3.5 3.5v3.7h3.7M10 6.5V10l2.5 1.5" /></svg>
);
export const IconChart = (p: P) => <svg {...base(p)}><path d="M3 17h14M6 14V9M10 14V5M14 14v-3" /></svg>;
export const IconSettings = (p: P) => (
  <svg {...base(p)}><circle cx="10" cy="10" r="2.5" /><path d="M10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1 4.7 4.7" /></svg>
);
export const IconUser = (p: P) => <svg {...base(p)}><circle cx="10" cy="7" r="3.5" /><path d="M3.5 17.5c.8-3.3 3.3-5 6.5-5s5.7 1.7 6.5 5" /></svg>;
export const IconMic = (p: P) => (
  <svg {...base(p)}><rect x="7.5" y="2.5" width="5" height="9" rx="2.5" /><path d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.5" /></svg>
);
export const IconWave = (p: P) => <svg {...base(p)}><path d="M3 8v4M6 5.5v9M9 3v14M12 6v8M15 8.5v3M18 9.5v1" /></svg>;
export const IconCheck = (p: P) => <svg {...base(p)}><path d="m4.5 10.5 3.5 3.5 7.5-8" /></svg>;
export const IconAlert = (p: P) => <svg {...base(p)}><path d="M10 3 2.5 16.5h15z" /><path d="M10 8v3.5M10 14v.01" /></svg>;
export const IconShield = (p: P) => <svg {...base(p)}><path d="M10 2.5 4 5v5c0 3.6 2.6 6.4 6 7.5 3.4-1.1 6-3.9 6-7.5V5z" /><path d="m7.5 10 2 2 3.5-4" /></svg>;
export const IconLock = (p: P) => <svg {...base(p)}><rect x="4" y="9" width="12" height="8.5" rx="1.5" /><path d="M7 9V6.5a3 3 0 0 1 6 0V9" /></svg>;
export const IconPlay = (p: P) => <svg {...base(p)}><path d="M6.5 4.5v11l9-5.5z" /></svg>;
export const IconPause = (p: P) => <svg {...base(p)}><path d="M7 4.5v11M13 4.5v11" /></svg>;
export const IconSkipBack = (p: P) => <svg {...base(p)}><path d="M5 4.5v11M15 4.5l-8 5.5 8 5.5z" /></svg>;
export const IconSkipFwd = (p: P) => <svg {...base(p)}><path d="M15 4.5v11M5 4.5l8 5.5-8 5.5z" /></svg>;
export const IconLink = (p: P) => (
  <svg {...base(p)}><path d="M8.5 11.5a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2L10 5.8" /><path d="M11.5 8.5a3 3 0 0 0-4.2 0l-2.6 2.6a3 3 0 0 0 4.2 4.2l1.1-1.1" /></svg>
);
export const IconCopy = (p: P) => <svg {...base(p)}><rect x="7" y="7" width="10" height="10" rx="1.5" /><path d="M13 7V4.5A1.5 1.5 0 0 0 11.5 3h-7A1.5 1.5 0 0 0 3 4.5v7A1.5 1.5 0 0 0 4.5 13H7" /></svg>;
export const IconTrash = (p: P) => <svg {...base(p)}><path d="M3.5 5.5h13M8 5.5V3.5h4v2M5 5.5l.8 11h8.4l.8-11" /></svg>;
export const IconEdit = (p: P) => <svg {...base(p)}><path d="M12.5 4 16 7.5 7.5 16H4v-3.5z" /></svg>;
export const IconUpload = (p: P) => <svg {...base(p)}><path d="M10 13V3.5M6 7.5l4-4 4 4M3.5 13v3.5h13V13" /></svg>;
export const IconSpark = (p: P) => <svg {...base(p)}><path d="M10 2.5v4M10 13.5v4M2.5 10h4M13.5 10h4M5 5l2.5 2.5M12.5 12.5 15 15M15 5l-2.5 2.5M7.5 12.5 5 15" /></svg>;
export const IconSun = (p: P) => <svg {...base(p)}><circle cx="10" cy="10" r="3.5" /><path d="M10 2v1.5M10 16.5V18M2 10h1.5M16.5 10H18M4.3 4.3l1 1M14.7 14.7l1 1M15.7 4.3l-1 1M5.3 14.7l-1 1" /></svg>;
export const IconBell = (p: P) => <svg {...base(p)}><path d="M5 13.5V9a5 5 0 0 1 10 0v4.5l1.5 2h-13zM8.5 17.5h3" /></svg>;
export const IconPhone = (p: P) => <svg {...base(p)}><rect x="5.5" y="2" width="9" height="16" rx="2" /><path d="M9 15h2" /></svg>;
export const IconEye = (p: P) => <svg {...base(p)}><path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10z" /><circle cx="10" cy="10" r="2.5" /></svg>;
export const IconEyeOff = (p: P) => <svg {...base(p)}><path d="M3 3l14 14M8.2 5a8 8 0 0 1 1.8-.2c5 0 8 5.2 8 5.2a14 14 0 0 1-2.3 2.9M5.2 6.6A14 14 0 0 0 2 10s3 5.5 8 5.5a7.6 7.6 0 0 0 3.3-.7" /></svg>;

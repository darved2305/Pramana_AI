/** The equipment library and starter site templates, shared by every organization. */
import { request } from "./http";
import type { EquipmentType, SiteTemplate } from "./types";

export const libraryApi = Object.freeze({
  equipment: (signal?: AbortSignal) => request<EquipmentType[]>("core", "/v1/library/equipment", { signal }),
  templates: (signal?: AbortSignal) => request<SiteTemplate[]>("core", "/v1/library/templates", { signal }),
});

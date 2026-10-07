import { apiRequest } from "./api/apiClient";

export type BoilerplateKind =
  | "firm_name"
  | "lawyer_name"
  | "enrollment_number"
  | "address"
  | "phone"
  | "email"
  | "letterhead"
  | "signature"
  | "other";

export interface OrganizationBoilerplateEntry {
  id: string;
  value: string;
  label?: string | null;
  kind: BoilerplateKind | string;
  active: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface CreateOrganizationBoilerplateEntry {
  value: string;
  label?: string;
  kind?: BoilerplateKind | string;
}

/**
 * Organization-owned fixed text is negative evidence for field discovery.
 * These calls deliberately go through the central API client so auth,
 * correlation IDs, and normalized error handling remain consistent.
 */
export async function listOrganizationBoilerplate(): Promise<OrganizationBoilerplateEntry[]> {
  return apiRequest<OrganizationBoilerplateEntry[]>("/api/organization/boilerplate");
}

export async function addOrganizationBoilerplate(
  entry: CreateOrganizationBoilerplateEntry
): Promise<OrganizationBoilerplateEntry> {
  return apiRequest<OrganizationBoilerplateEntry>("/api/organization/boilerplate", {
    method: "POST",
    body: JSON.stringify(entry),
  });
}

export async function removeOrganizationBoilerplate(entryId: string): Promise<void> {
  await apiRequest<void>(`/api/organization/boilerplate/${encodeURIComponent(entryId)}`, {
    method: "DELETE",
  });
}

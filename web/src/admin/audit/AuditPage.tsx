import { copy } from "@/copy/ko";

/** Audit log (route /admin/audit). Placeholder: the tabs, filters and table arrive in Plan 5 Task 12. */
export function AuditPage() {
  return <h1 className="text-xl font-semibold text-fg">{copy.audit.title}</h1>;
}

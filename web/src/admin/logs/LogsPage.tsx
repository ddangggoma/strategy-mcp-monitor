import { copy } from "@/copy/ko";

/** Log search (route /admin/logs). Placeholder: the filters, histogram and table arrive in Plan 5 Task 11. */
export function LogsPage() {
  return <h1 className="text-xl font-semibold text-fg">{copy.logs.title}</h1>;
}

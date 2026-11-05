import { copy } from "@/copy/ko";

/** Route placeholder (F16): Task 13 replaces it with the real page. Title only, no fake data. */
export function SettingsPage() {
  return <h1 className="text-xl font-semibold text-fg">{copy.settings.title}</h1>;
}

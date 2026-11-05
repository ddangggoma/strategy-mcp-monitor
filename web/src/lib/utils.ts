import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind-merge only knows Tailwind's default scale; teach it our token-named utilities so
// e.g. `text-metric` is treated as a font size (not a color) and `shadow-md` stays a shadow.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["xs", "sm", "base", "lg", "xl", "2xl", "metric", "display"],
      radius: ["xs", "sm", "md", "lg", "full"],
      shadow: ["xs", "sm", "md", "lg"],
      ease: ["out", "in-out", "hover"],
      "font-weight": ["normal", "medium", "semibold", "bold"],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

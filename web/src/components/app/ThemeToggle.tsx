import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { copy } from "@/copy/ko";
import { getThemePref, setThemePref, type ThemePref } from "@/lib/theme";

const ORDER: readonly ThemePref[] = ["light", "dark", "system"];

const ICONS: Record<ThemePref, React.ReactElement> = {
  system: <MonitorIcon aria-hidden="true" />,
  dark: <MoonIcon aria-hidden="true" />,
  light: <SunIcon aria-hidden="true" />,
};

function isThemePref(v: string): v is ThemePref {
  return (ORDER as readonly string[]).includes(v);
}

/** Top-bar theme menu: light (default), dark, or follow the OS. Infrequent, so a menu. */
export function ThemeToggle() {
  const [pref, setPref] = useState<ThemePref>(getThemePref);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={copy.common.theme.triggerLabel(copy.common.theme[pref])}>
          {ICONS[pref]}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-40">
        <DropdownMenuLabel className="text-xs text-fg-muted">{copy.common.theme.label}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={pref}
          onValueChange={(v) => {
            if (!isThemePref(v)) return;
            setThemePref(v);
            setPref(v);
          }}
        >
          {ORDER.map((p) => (
            <DropdownMenuRadioItem key={p} value={p}>
              {ICONS[p]}
              {copy.common.theme[p]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

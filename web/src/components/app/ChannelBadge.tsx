import { GlobeIcon, MonitorIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { copy } from "@/copy/ko";
import type { Channel } from "@/lib/api-types";
import { InfoTip } from "./InfoTip";

/**
 * Which door this tab came in through (§6.1), and what that door allows (the tip). Neutral: a
 * channel is not an MCP state.
 */
export function ChannelBadge({ channel }: { channel: Channel }) {
  const Icon = channel === "local" ? MonitorIcon : GlobeIcon;
  return (
    <span className="inline-flex shrink-0 items-center gap-0.5">
      <Badge variant="outline" data-channel={channel}>
        <Icon aria-hidden="true" />
        <span className="max-sm:sr-only">{copy.channel[channel]}</span>
      </Badge>
      <InfoTip
        label={copy.channel[channel]}
        content={channel === "local" ? copy.channel.localHint : copy.channel.externalHint}
        side="bottom"
        align="start"
      />
    </span>
  );
}

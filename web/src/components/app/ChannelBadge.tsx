import { GlobeIcon, MonitorIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { copy } from "@/copy/ko";
import type { Channel } from "@/lib/api-types";

/** Which door this tab came in through (§6.1). Neutral: a channel is not an MCP state. */
export function ChannelBadge({ channel }: { channel: Channel }) {
  const Icon = channel === "local" ? MonitorIcon : GlobeIcon;
  return (
    <Badge variant="outline" data-channel={channel}>
      <Icon aria-hidden="true" />
      <span className="max-sm:sr-only">{copy.channel[channel]}</span>
    </Badge>
  );
}

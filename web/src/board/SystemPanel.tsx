import { ArrowDownIcon, ArrowUpIcon, CpuIcon, GpuIcon, HardDriveIcon, MemoryStickIcon, NetworkIcon, type LucideIcon } from "lucide-react";
import { useId, type CSSProperties, type ReactNode } from "react";
import { InfoTip } from "@/components/app/InfoTip";
import { RollingNumber } from "@/components/status/RollingNumber";
import { Sparkline } from "@/components/status/Sparkline";
import { copy } from "@/copy/ko";
import type { GpuStatus, McpState, SystemStatus } from "@/lib/api-types";
import { useClock } from "@/lib/clock";
import { CPU_LOAD, DISK_LOAD, GPU_LOAD, GPU_MEMORY_LOAD, MEMORY_LOAD, formatBytes, formatRate, formatUptime, loadState } from "./system";
import "./BoardOverview.css";

const t = copy.board.system;

function Tile({
  title,
  icon: Icon,
  tone,
  tip,
  children,
}: {
  title: string;
  icon: LucideIcon;
  tone: McpState | null;
  /** A help tip beside the title (outside the heading: its button is not part of the heading's name). */
  tip?: ReactNode;
  children: ReactNode;
}) {
  const heading = (
    <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
      <span aria-hidden="true" className="ov-chip">
        <Icon className="size-4" />
      </span>
      {title}
    </h3>
  );
  return (
    <li data-tone={tone ?? undefined} className="ov-tile">
      {tip ? (
        <div className="flex items-center gap-0.5">
          {heading}
          {tip}
        </div>
      ) : (
        heading
      )}
      {children}
    </li>
  );
}

/** A ring filled to `percent` in the hue of its load, the number in the middle. */
function Gauge({ name, percent, state }: { name: string; percent: number; state: McpState }) {
  const pct = Math.min(100, Math.max(0, percent));
  return (
    <div className="ov-donut sys-gauge">
      <svg role="img" aria-label={t.gaugeLabel(name, Math.round(pct))} viewBox="0 0 100 100" className="size-full">
        <circle cx="50" cy="50" r={42} className="ov-donut-track" />
        <g transform="rotate(-90 50 50)">
          <circle
            cx="50"
            cy="50"
            r={42}
            pathLength={100}
            data-state={state}
            className="ov-donut-seg"
            style={{ strokeDasharray: `${pct} ${100 - pct}`, strokeLinecap: "round" }}
          />
        </g>
      </svg>
      <div aria-hidden="true" className="ov-donut-center">
        <RollingNumber value={pct} unit="%" className="text-2xl font-semibold text-fg" />
      </div>
    </div>
  );
}

/** CPU, memory or GPU: the ring, a line or two of detail, and the recent percentages. */
function LoadTile({
  title,
  icon,
  percent,
  load,
  detail,
  history,
  minutes,
  tip,
}: {
  title: string;
  icon: LucideIcon;
  percent: number;
  load: readonly [number, number];
  detail: ReactNode;
  history: number[];
  minutes: number;
  tip?: ReactNode;
}) {
  const state = loadState(percent, load);
  return (
    <Tile title={title} icon={icon} tone={state} tip={tip}>
      <div className="flex items-center gap-4">
        <Gauge name={title} percent={percent} state={state} />
        {typeof detail === "string" ? <p className="min-w-0 text-sm text-fg">{detail}</p> : <div className="min-w-0 flex-1">{detail}</div>}
      </div>
      <div className="flex flex-col gap-1">
        <div className="sys-trend" data-state={state}>
          <Sparkline points={history} label={t.trendLabel(title)} max={100} height={36} summary={t.trendSummary} />
        </div>
        <p aria-hidden="true" className="text-[0.6875rem] text-fg-muted">
          {t.recent(minutes)}
        </p>
      </div>
    </Tile>
  );
}

/** A labelled bar: a disk's fill, or the GPU's dedicated memory. */
function UsageMeter({
  label,
  mono = false,
  percent,
  state,
  caption,
}: {
  label: string;
  mono?: boolean;
  percent: number;
  state: McpState;
  caption: string;
}) {
  const id = useId();
  const pct = Math.min(100, Math.max(0, percent));
  const text = copy.common.units.percent(pct.toFixed(1));
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span id={id} className={mono ? "font-mono text-sm font-semibold text-fg" : "text-sm text-fg-muted"}>
          {label}
        </span>
        <span className="text-sm font-semibold text-fg tabular-nums">{text}</span>
      </div>
      <div
        role="meter"
        aria-labelledby={id}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={text}
        className="ov-meter"
        data-state={state}
      >
        <span className="ov-meter-fill" style={{ "--meter": pct / 100 } as CSSProperties} />
      </div>
      <span className="text-xs text-fg-muted tabular-nums">{caption}</span>
    </div>
  );
}

/** The GPU's dedicated memory: a bar when its size is known, else what is in use, else a note. */
function GpuMemory({ memory }: { memory: GpuStatus["memory"] }) {
  if (memory === null) return <p className="text-sm text-fg-muted">{t.gpuNoMemory}</p>;
  if (memory.total === null || memory.percent === null) {
    return (
      <p className="flex flex-col text-sm">
        <span className="text-fg-muted">{t.gpuMemory}</span>
        <span className="text-fg tabular-nums">{t.gpuMemoryOnly(formatBytes(memory.used))}</span>
      </p>
    );
  }
  return (
    <UsageMeter
      label={t.gpuMemory}
      percent={memory.percent}
      state={loadState(memory.percent, GPU_MEMORY_LOAD)}
      caption={t.gpuMemoryUsed(formatBytes(memory.used), formatBytes(memory.total))}
    />
  );
}

function Disks({ disks }: { disks: SystemStatus["disks"] }) {
  const worst = disks.reduce<number | null>((m, d) => (m === null || d.percent > m ? d.percent : m), null);
  return (
    <Tile title={t.disk} icon={HardDriveIcon} tone={worst === null ? null : loadState(worst, DISK_LOAD)}>
      {disks.length === 0 ? (
        <p className="text-sm text-fg-muted">{t.noDisk}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {disks.map((d) => (
            <DiskRow key={d.name} disk={d} />
          ))}
        </ul>
      )}
    </Tile>
  );
}

function DiskRow({ disk }: { disk: SystemStatus["disks"][number] }) {
  return (
    <li>
      <UsageMeter
        label={disk.name}
        mono
        percent={disk.percent}
        state={loadState(disk.percent, DISK_LOAD)}
        caption={t.diskUsed(formatBytes(disk.used), formatBytes(disk.total))}
      />
    </li>
  );
}

function Network({ network }: { network: SystemStatus["network"] }) {
  const rows: { label: string; icon: LucideIcon; bps: number | null }[] = [
    { label: t.received, icon: ArrowDownIcon, bps: network?.recv_bps ?? null },
    { label: t.sent, icon: ArrowUpIcon, bps: network?.sent_bps ?? null },
  ];
  return (
    <Tile title={t.network} icon={NetworkIcon} tone={null}>
      <dl className="flex flex-col gap-3">
        {rows.map(({ label, icon: Icon, bps }) => (
          <div key={label} className="flex items-center justify-between gap-3">
            <dt className="flex items-center gap-1.5 text-sm text-fg-muted">
              <Icon aria-hidden="true" className="size-4" />
              {label}
            </dt>
            <dd className="text-xl font-semibold text-fg tabular-nums" data-volatile="">
              {bps === null ? "—" : formatRate(bps)}
            </dd>
          </div>
        ))}
      </dl>
      {network === null ? <p className="text-xs text-fg-muted">{t.networkFirst}</p> : null}
    </Tile>
  );
}

function Uptime({ bootAt }: { bootAt: string }) {
  const { wall } = useClock();
  return <span data-volatile="">{t.uptime(formatUptime(bootAt, wall))}</span>;
}

/**
 * “서버 PC 리소스”: CPU, memory and (when the PC has GPU counters) the GPU as rings with their recent
 * trend, the GPU's dedicated memory and each fixed disk as a bar, and the network rate, from the
 * server's readings (every few seconds over the board stream). The hues are the state hues: green
 * under the load thresholds, amber over the first, red over the second. No GPU, no GPU tile.
 */
export function SystemPanel({ system }: { system: SystemStatus | undefined }) {
  const headingId = useId();
  const minutes = system ? Math.round((system.history.cpu.length * system.interval_sec) / 60) || 1 : 0;
  const gpu = system?.gpu ?? null;
  return (
    <section aria-labelledby={headingId} data-anim="rise" style={{ "--rise-i": 6 } as CSSProperties} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id={headingId} className="text-lg font-semibold text-fg">
          {t.title}
        </h2>
        {system ? (
          <p className="flex gap-2 text-sm text-fg-muted">
            <Uptime bootAt={system.boot_at} />
            <span aria-hidden="true">·</span>
            <span>{t.every(system.interval_sec)}</span>
          </p>
        ) : null}
      </div>
      {system ? (
        <ul className="ov-grid sys-grid" data-tiles={gpu ? 5 : 4}>
          <LoadTile
            title={t.cpu}
            icon={CpuIcon}
            percent={system.cpu.percent}
            load={CPU_LOAD}
            detail={t.cores(system.cpu.cores)}
            history={system.history.cpu}
            minutes={minutes}
          />
          <LoadTile
            title={t.memory}
            icon={MemoryStickIcon}
            percent={system.memory.percent}
            load={MEMORY_LOAD}
            detail={t.memoryUsed(formatBytes(system.memory.used), formatBytes(system.memory.total))}
            history={system.history.memory}
            minutes={minutes}
          />
          {gpu ? (
            <LoadTile
              title={t.gpu}
              icon={GpuIcon}
              percent={gpu.percent}
              load={GPU_LOAD}
              detail={<GpuMemory memory={gpu.memory} />}
              history={system.history.gpu ?? []}
              minutes={minutes}
              tip={<InfoTip label={t.gpu} content={copy.help.gpu} side="bottom" align="start" />}
            />
          ) : null}
          <Disks disks={system.disks} />
          <Network network={system.network} />
        </ul>
      ) : (
        <p className="text-sm text-fg-muted">{t.waiting}</p>
      )}
    </section>
  );
}

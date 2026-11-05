import { formatBytes, formatDuration, formatKst, formatKstShort, relativeKo } from "./time";

it("formats in KST regardless of the host time zone", () => {
  expect(formatKst("2026-11-04T05:03:22.418+00:00")).toBe("2026-11-04 14:03:22");
  expect(formatKstShort("2026-11-04T14:03:22.418+09:00")).toBe("11-04 14:03");
  // crosses midnight in KST, and noon/midnight hours stay two-digit 24-hour values
  expect(formatKst("2026-12-31T15:00:00Z")).toBe("2027-01-01 00:00:00");
  expect(formatKst("2026-11-04T03:00:00Z")).toBe("2026-11-04 12:00:00");
});

it("relative time in Korean", () => {
  expect(relativeKo("2026-11-04T14:00:00+09:00", new Date("2026-11-04T14:03:00+09:00"))).toBe("3분 전");
  expect(relativeKo("2026-11-04T14:00:00+09:00", new Date("2026-11-04T16:00:00+09:00"))).toBe("2시간 전");
  expect(relativeKo("2026-11-04T14:01:00+09:00", new Date("2026-11-04T14:00:00+09:00"))).toBe("1분 후");
});

it("relative time defaults to now", () => {
  vi.useFakeTimers({ now: new Date("2026-11-04T14:00:30+09:00") });
  expect(relativeKo("2026-11-04T14:00:00+09:00")).toBe("30초 전");
  vi.useRealTimers();
});

it("formats durations and bytes", () => {
  expect(formatDuration(1234)).toBe("1.2초");
  expect(formatDuration(123000)).toBe("2분 3초");
  expect(formatBytes(12_900_000)).toBe("12.3 MB");
});

it("covers duration and byte edges", () => {
  expect(formatDuration(null)).toBe("—");
  expect(formatDuration(0)).toBe("0.0초");
  expect(formatDuration(59_940)).toBe("59.9초");
  expect(formatDuration(59_960)).toBe("1분"); // rounds up into the minute form, never "60.0초"
  expect(formatDuration(120_000)).toBe("2분");
  expect(formatDuration(3_725_000)).toBe("1시간 2분");
  expect(formatBytes(0)).toBe("0 B");
  expect(formatBytes(1023)).toBe("1023 B");
  expect(formatBytes(1536)).toBe("1.5 KB");
  expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
});

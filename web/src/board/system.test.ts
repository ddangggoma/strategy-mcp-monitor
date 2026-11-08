import { CPU_LOAD, DISK_LOAD, formatBytes, formatRate, formatUptime, loadState } from "./system";

it("formats bytes in 1024 steps with one decimal", () => {
  expect(formatBytes(820)).toBe("820B");
  expect(formatBytes(1536)).toBe("1.5KB");
  expect(formatBytes(16 * 2 ** 30)).toBe("16.0GB");
  expect(formatBytes(3 * 2 ** 40)).toBe("3.0TB");
  expect(formatRate(1_572_864)).toBe("1.5MB/s");
});

it("says how long the PC has been up in the two largest units", () => {
  const boot = "2026-11-01T00:00:00.000+09:00";
  const at = (min: number) => Date.parse(boot) + min * 60_000;
  expect(formatUptime(boot, at(8))).toBe("8분");
  expect(formatUptime(boot, at(5 * 60 + 12))).toBe("5시간 12분");
  expect(formatUptime(boot, at(3 * 1440 + 4 * 60 + 30))).toBe("3일 4시간");
  expect(formatUptime(boot, at(2 * 1440))).toBe("2일");
});

it("reads a load against its thresholds", () => {
  expect(loadState(69.9, CPU_LOAD)).toBe("HEALTHY");
  expect(loadState(70, CPU_LOAD)).toBe("SUSPECT");
  expect(loadState(90, CPU_LOAD)).toBe("FAILED");
  expect(loadState(85, DISK_LOAD)).toBe("SUSPECT");
});

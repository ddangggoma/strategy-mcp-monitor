// Shared by the history tab and its lazily loaded chart (kept apart so the chart chunk does not
// import the tab module back).

export const PERIODS = [1, 6, 24, 168] as const;
export type Period = (typeof PERIODS)[number];

/** The chart's fixed height (plots + time axis band): the loading skeleton holds the same space. */
export const CHART_HEIGHT = 300;

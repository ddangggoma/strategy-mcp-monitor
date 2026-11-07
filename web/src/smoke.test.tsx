import { render, screen } from "@testing-library/react";

it("renders a React 19 tree under jsdom", () => {
  render(<h1>ok</h1>);
  expect(screen.getByRole("heading", { name: "ok" })).toBeInTheDocument();
});

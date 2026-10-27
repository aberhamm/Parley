import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { AnalyticsChoice } from "./AnalyticsChoice";
import { expectNoViolations } from "../test/axe";
afterEach(()=>{cleanup();localStorage.clear()});
it("provides an accessible identity-independent local choice",async()=>{
  const {container}=render(<MemoryRouter initialEntries={["/link#SECRET"]}><AnalyticsChoice/></MemoryRouter>);
  fireEvent.click(screen.getByText("Usage privacy"));
  const choice=screen.getByRole("checkbox",{name:"Allow usage analytics in this browser"});
  fireEvent.click(choice); expect(localStorage.getItem("umami.disabled")).toBe("1");
  expect(screen.getByText(/does not delete past analytics/)).toBeTruthy();
  await expectNoViolations(container);
});
it("honestly announces when the choice cannot persist",()=>{
  vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw new Error("denied")});
  render(<MemoryRouter><AnalyticsChoice/></MemoryRouter>);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("status").textContent).toContain("could not be saved");
});
it("does not show on excluded embedded routes",()=>{
  render(<MemoryRouter initialEntries={["/embed/meet/mainstage"]}><AnalyticsChoice/></MemoryRouter>);
  expect(screen.queryByText("Usage privacy")).toBeNull();
});

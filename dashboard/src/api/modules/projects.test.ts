import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));

vi.mock("../request", () => ({ request }));

import { projectsApi } from "./projects";

beforeEach(() => {
  request.mockClear();
});

describe("projectsApi", () => {
  it("lists and creates projects", () => {
    projectsApi.list();
    projectsApi.create({ name: "Alpha", root_dir: "E:/work/alpha" });

    expect(request).toHaveBeenNthCalledWith(1, "/projects");
    expect(request).toHaveBeenNthCalledWith(2, "/projects", {
      method: "POST",
      body: JSON.stringify({ name: "Alpha", root_dir: "E:/work/alpha" }),
    });
  });

  it("omits root_dir when creating an Octop-home project", () => {
    projectsApi.create({ name: "Beta" });

    expect(request).toHaveBeenCalledWith("/projects", {
      method: "POST",
      body: JSON.stringify({ name: "Beta" }),
    });
  });

  it("renames and deletes by project id", () => {
    projectsApi.rename("p1", "Renamed");
    projectsApi.remove("p1");

    expect(request).toHaveBeenNthCalledWith(1, "/projects/p1", {
      method: "PATCH",
      body: JSON.stringify({ name: "Renamed" }),
    });
    expect(request).toHaveBeenNthCalledWith(2, "/projects/p1", {
      method: "DELETE",
    });
  });

  it("lists threads bound to a project", () => {
    projectsApi.threads("p1", 50);

    expect(request).toHaveBeenCalledWith("/projects/p1/threads?limit=50");
  });

  it("encodes project ids in urls", () => {
    projectsApi.threads("a/b c");

    expect(request).toHaveBeenCalledWith("/projects/a%2Fb%20c/threads?limit=100");
  });
});

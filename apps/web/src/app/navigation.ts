export type WorldRoute =
  | { kind: "home" }
  | { kind: "world"; world: "planet" | "tribe" }
  | { kind: "wanjie" }
  | { kind: "wanjie-world"; worldId: string };

export function readWorldRoute(pathname = window.location.pathname): WorldRoute {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === "/worlds/planet") return { kind: "world", world: "planet" };
  if (normalized === "/worlds/tribe") return { kind: "world", world: "tribe" };
  if (normalized === "/wanjie") return { kind: "wanjie" };
  const officialWorld = /^\/wanjie\/([^/]+)$/.exec(normalized);
  if (officialWorld) return { kind: "wanjie-world", worldId: officialWorld[1] };
  return { kind: "home" };
}

export function scenarioForRoute(route: WorldRoute): "enterprise_earth" | "tribe_survival" | null {
  if (route.kind !== "world") return null;
  return route.world === "tribe" ? "tribe_survival" : "enterprise_earth";
}

export function navigateToPath(path: string): void {
  if (window.location.pathname === path) return;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

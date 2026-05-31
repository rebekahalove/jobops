import { gateDashboardRequest } from "../jobops/lib/dashboard-auth";

ensureAsyncLocalStorageCompatibility();

export async function middleware(request: Request) {
  return gateDashboardRequest(request, {
    dashboardBasePath: "/jobops",
    loginPath: "/jobops/login"
  });
}

export const config = {
  matcher: [
    "/jobops",
    "/jobops/about",
    "/jobops/login",
    "/jobops/forgot-password",
    "/jobops/reset-password",
    "/jobops/accept-invite",
    "/jobops/invite/:path*",
    "/jobops/privacy",
    "/jobops/portfolio/:path*",
    "/jobops/profile/:path*",
    "/jobops/companies/:path*",
    "/jobops/jobs/:path*",
    "/jobops/applications/:path*",
    "/jobops/materials/:path*",
    "/jobops/follow-ups/:path*",
    "/jobops/fit-scoring/:path*",
    "/jobops/account/:path*"
  ]
};

function ensureAsyncLocalStorageCompatibility() {
  // Next 15.5 middleware expects AsyncLocalStorage.snapshot; some Netlify runtimes expose AsyncLocalStorage without it.
  type SnapshotRunner = <Result>(callback: (...args: unknown[]) => Result, ...args: unknown[]) => Result;
  type AsyncLocalStorageConstructor = {
    bind?: <Callback extends (...args: unknown[]) => unknown>(callback: Callback) => Callback;
    snapshot?: () => SnapshotRunner;
  };

  const maybeAsyncLocalStorage = (
    globalThis as typeof globalThis & { AsyncLocalStorage?: AsyncLocalStorageConstructor }
  ).AsyncLocalStorage;

  if (!maybeAsyncLocalStorage) {
    return;
  }

  if (typeof maybeAsyncLocalStorage.bind !== "function") {
    Object.defineProperty(maybeAsyncLocalStorage, "bind", {
      configurable: true,
      value: <Callback extends (...args: unknown[]) => unknown>(callback: Callback) => callback
    });
  }

  if (typeof maybeAsyncLocalStorage.snapshot !== "function") {
    Object.defineProperty(maybeAsyncLocalStorage, "snapshot", {
      configurable: true,
      value: () => ((callback, ...args) => callback(...args)) as SnapshotRunner
    });
  }
}

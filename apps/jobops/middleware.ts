import type { NextRequest } from "next/server";
import { gateDashboardRequest } from "./lib/dashboard-auth";

export async function middleware(request: NextRequest) {
  return gateDashboardRequest(request, {
    dashboardBasePath: "",
    loginPath: "/login"
  });
}

export const config = {
  matcher: [
    "/",
    "/profile/:path*",
    "/companies/:path*",
    "/jobs/:path*",
    "/applications/:path*",
    "/materials/:path*",
    "/follow-ups/:path*",
    "/fit-scoring/:path*",
    "/api/command-center",
    "/api/profile-intake",
    "/api/profile-draft",
    "/api/applications",
    "/api/applications/:path*"
  ]
};

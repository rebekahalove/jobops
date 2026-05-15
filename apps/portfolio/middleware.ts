import type { NextRequest } from "next/server";
import { gateDashboardRequest } from "../jobops/lib/dashboard-auth";

export async function middleware(request: NextRequest) {
  return gateDashboardRequest(request, {
    dashboardBasePath: "/jobops",
    loginPath: "/jobops/login"
  });
}

export const config = {
  matcher: [
    "/jobops/:path*",
    "/api/command-center",
    "/api/profile-intake",
    "/api/profile-draft",
    "/api/applications",
    "/api/applications/:path*"
  ]
};

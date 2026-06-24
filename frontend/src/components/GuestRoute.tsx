import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";
import { RouteSkeleton } from "./SkeletonScreens";

export function GuestRoute() {
  const { loading, session } = useAuth();

  if (loading) {
    return <RouteSkeleton variant="auth" />;
  }

  if (session) {
    return <Navigate replace to="/chat" />;
  }

  return <Outlet />;
}

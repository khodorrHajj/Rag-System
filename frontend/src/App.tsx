import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { GuestRoute } from "./components/GuestRoute";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import { ChatPage } from "./pages/ChatPage";
import { DeveloperPage } from "./pages/DeveloperPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SignupPage } from "./pages/SignupPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";
import { RouteSkeleton } from "./components/SkeletonScreens";

function RootRedirect() {
  const { loading, session } = useAuth();

  if (loading) {
    return <RouteSkeleton variant="app" />;
  }

  return <Navigate replace to={session ? "/chat" : "/login"} />;
}

function DeveloperRoute() {
  const { canAccessDeveloperTools, loading } = useAuth();

  if (loading) {
    return <RouteSkeleton variant="app" />;
  }

  if (!canAccessDeveloperTools) {
    return <Navigate replace to="/chat" />;
  }

  return <DeveloperPage />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route element={<RootRedirect />} path="/" />

      <Route element={<GuestRoute />}>
        <Route element={<LoginPage />} path="/login" />
        <Route element={<SignupPage />} path="/signup" />
        <Route element={<VerifyEmailPage />} path="/verify-email" />
      </Route>

      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route element={<Navigate replace to="/chat" />} path="/dashboard" />
          <Route element={<DocumentsPage />} path="/documents" />
          <Route element={<ChatPage />} path="/chat" />
          <Route element={<DeveloperRoute />} path="/developer" />
        </Route>
      </Route>

      <Route element={<NotFoundPage />} path="*" />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}

import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="route-loader route-loader--not-found">
      <div className="empty-state">
        <p className="empty-state__title">Page not found</p>
        <p className="empty-state__description">
          The route you requested does not exist in this workspace.
        </p>
        <Link className="button button--primary" to="/chat">
          Go to chat
        </Link>
      </div>
    </main>
  );
}

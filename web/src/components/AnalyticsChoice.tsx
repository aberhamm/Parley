import { useEffect, useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";
import { analyticsPageCategory } from "../lib/analyticsContract";
import { analyticsDoNotTrack, analyticsPreference, initializeAnalytics, setAnalyticsDisabled, subscribeAnalytics, trackAnalyticsPage } from "../lib/analytics";
import "./AnalyticsChoice.css";

export function AnalyticsChoice() {
  const { pathname } = useLocation();
  const preference = useSyncExternalStore(subscribeAnalytics, analyticsPreference);
  useEffect(() => { initializeAnalytics(); trackAnalyticsPage(); }, [pathname]);
  if (analyticsPageCategory(pathname) === null) return null;
  const disabled = preference.endsWith("disabled");
  return <aside className="analytics-choice" aria-label="Usage analytics">
    <details>
      <summary>Usage privacy</summary>
      <p>Optional usage analytics count broad pages and actions, without names or meeting content.</p>
      <label><input type="checkbox" checked={!disabled} onChange={(event) => setAnalyticsDisabled(!event.target.checked)} /> Allow usage analytics in this browser</label>
      {analyticsDoNotTrack() && <p>Your Do Not Track setting also blocks analytics.</p>}
      {preference.startsWith("temporary") && <p role="status">This choice could not be saved. It applies only to this open page.</p>}
      <p>Opting out stops future sends. It does not delete past analytics. Enabling may require reloading this page.</p>
    </details>
  </aside>;
}

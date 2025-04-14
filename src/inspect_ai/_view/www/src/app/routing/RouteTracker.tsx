import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useStore } from "../../state/store";

export const RouteTracker = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const setUrlHash = useStore((state) => state.appActions.setUrlHash);
  const storedHash = useStore((state) => state.app.urlHash);

  // Restore a saved hash one time
  const hasRestoredHash = useRef(false);

  // Restore saved hash on mount
  useEffect(() => {
    if (storedHash && !hasRestoredHash.current) {
      hasRestoredHash.current = true;

      const currentHash = location.pathname;
      if (currentHash !== storedHash) {
        // Navigate to the saved hash (remove the leading # if needed)
        const target = storedHash.startsWith("#")
          ? storedHash.slice(1)
          : storedHash;
        navigate(target, { replace: true });
      }
    }
  }, [storedHash, location, navigate]);

  // Track changes
  useEffect(() => {
    setUrlHash(location.pathname);
  }, [location]);

  return null;
};

import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useStore } from "../../state/store";

export const RouteTracker = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const setUrlHash = useStore((state) => state.appActions.setUrlHash);
  const storedHash = useStore((state) => state.app.urlHash);

  // Restore a saved hash at mount, if one has been stored
  const restoredRef = useRef<boolean>(false);
  useEffect(() => {
    if (storedHash && !restoredRef.current) {
      const target = storedHash.startsWith("#")
        ? storedHash.slice(1)
        : storedHash;
      //navigate(target, { replace: true });
      restoredRef.current = true;
    
    }
  }, []);

  // Track changes
  useEffect(() => {
    setUrlHash(location.pathname);
  }, [location]);

  return null;
};

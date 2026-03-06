import { useCallback, useEffect, useRef } from "react";

export function useRevokableUrls() {
  const urlsRef = useRef<string[]>([]);

  const createRevokableUrl = useCallback(
    (data: BlobPart, type = "text/plain") => {
      const blob = new Blob([data], { type });
      const url = URL.createObjectURL(blob);
      urlsRef.current.push(url);
      return url;
    },
    [],
  );

  useEffect(() => {
    // Cleanup function revokes all created URLs
    return () => {
      urlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      urlsRef.current = [];
    };
  }, []);

  return createRevokableUrl;
}

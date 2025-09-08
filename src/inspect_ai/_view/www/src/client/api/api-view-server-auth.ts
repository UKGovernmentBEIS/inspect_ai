import {
  createViewServerApi,
  setGlobalHeaderProvider,
} from "./api-view-server";
import { LogViewAPI } from "./types";

// Constants for token cookies
export const INSPECT_AI_ACCESS_TOKEN = "inspect_ai_access_token";
export const INSPECT_AI_REFRESH_TOKEN = "inspect_ai_refresh_token";

// Utility function to check token expiry with a small buffer time
export function isTokenExpired(token: string, bufferSeconds = 60): boolean {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    const expiryTime = payload.exp * 1000;
    const currentTimeWithBuffer = Date.now() + bufferSeconds * 1000;
    return currentTimeWithBuffer >= expiryTime;
  } catch {
    return true; // Treat any parsing errors as expired
  }
}

// Stub for refreshing the access token
export async function refreshAccessToken(
  _refreshToken: string,
): Promise<string | null> {
  // Placeholder logic for refreshing token
  return null; // Replace this with actual refresh implementation
}

function getCookie(name: string): string | null {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop()?.split(";").shift() || null;
  return null;
}

function setCookie(name: string, value: string): void {
  document.cookie = `${name}=${value}; path=/`;
}

async function getValidAccessToken(): Promise<string | null> {
  let accessToken = getCookie(INSPECT_AI_ACCESS_TOKEN);

  if (!accessToken) {
    return null;
  }

  if (isTokenExpired(accessToken)) {
    const refreshToken = getCookie(INSPECT_AI_REFRESH_TOKEN);
    if (!refreshToken) {
      return null;
    }

    const newAccessToken = await refreshAccessToken(refreshToken);
    if (newAccessToken) {
      setCookie(INSPECT_AI_ACCESS_TOKEN, newAccessToken);
      accessToken = newAccessToken;
    } else {
      return null;
    }
  }

  return accessToken;
}

export function createViewServerApiWithAuth(
  options: { log_dir?: string } = {},
): LogViewAPI {
  // Set up global header provider for auth
  setGlobalHeaderProvider(async (): Promise<Record<string, string>> => {
    const token = await getValidAccessToken();
    console.log("Using access token:", token);
    if (token) {
      return { Authorization: `Bearer ${token}` };
    }
    return {};
  });

  // Return the base API which will now include auth headers
  return createViewServerApi(options);
}

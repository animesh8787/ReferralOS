// Firebase Auth is optional: without NEXT_PUBLIC_FIREBASE_API_KEY the app uses its own email/password sign-in.
import { getApp, getApps, initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

export const firebaseEnabled = !!process.env.NEXT_PUBLIC_FIREBASE_API_KEY;

export function fbAuth() {
  const app = getApps().length ? getApp() : initializeApp({
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  });
  return getAuth(app);
}

const MESSAGES: Record<string, string> = {
  "auth/invalid-credential": "Wrong email or password.",
  "auth/invalid-email": "That email address doesn't look right.",
  "auth/email-already-in-use": "An account with this email already exists. Try signing in.",
  "auth/weak-password": "Choose a longer password (at least 6 characters).",
  "auth/popup-closed-by-user": "The Google window was closed before sign-in finished.",
  "auth/too-many-requests": "Too many attempts. Please wait a few minutes and try again.",
  "auth/network-request-failed": "Network problem. Check your connection and try again.",
};

export function fbMessage(e: unknown): string {
  const code = (e as { code?: string }).code ?? "";
  return MESSAGES[code] ?? (e as Error).message ?? "Something went wrong.";
}

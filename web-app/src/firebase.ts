import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

const required = (name: string): string => {
  const value = import.meta.env[name];
  if (!value) throw new Error(`${name} is not configured`);
  return value;
};

const app = initializeApp({
  apiKey: required("VITE_FIREBASE_API_KEY"),
  authDomain: required("VITE_FIREBASE_AUTH_DOMAIN"),
  projectId: required("VITE_FIREBASE_PROJECT_ID"),
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: required("VITE_FIREBASE_APP_ID"),
});

export const auth = getAuth(app);
export const provider = new GoogleAuthProvider();
export const db = getFirestore(app);
export const householdId = required("VITE_HOUSEHOLD_ID");

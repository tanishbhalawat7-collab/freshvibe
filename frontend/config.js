// Fresh Vibe frontend configuration.
//
// Leave API_BASE empty when the backend serves this frontend (recommended:
// same origin, no CORS, works through one HTTPS tunnel).
//
// Only if you host the frontend somewhere else (e.g. Vercel / Netlify), set it
// to the HTTPS URL of your camera bridge and add this site's origin to
// CORS_ORIGINS in the bridge's .env, for example:
//   window.FRESHVIBE_CONFIG = { API_BASE: "https://freshvibe-bridge.example.com" };
window.FRESHVIBE_CONFIG = { API_BASE: "" };

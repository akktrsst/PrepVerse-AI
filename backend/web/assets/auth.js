// Firebase Google sign-in. Loaded as a module by app.js on every page.
// Reads the public Firebase web config from /api/config/public, so no keys live in the frontend code.
const FIREBASE_VERSION = "10.12.2";

async function init() {
  let cfg;
  try {
    cfg = await (await fetch("/api/config/public")).json();
  } catch {
    PV._setAuth({ enabled: false });
    return;
  }
  if (cfg.auth_disabled) {
    PV._setAuth({ enabled: false });
    return;
  }
  if (!cfg.firebase) {
    PV._setAuth({ enabled: true, configured: false, user: null });
    return;
  }

  const base = `https://www.gstatic.com/firebasejs/${FIREBASE_VERSION}`;
  const [{ initializeApp }, fb] = await Promise.all([
    import(`${base}/firebase-app.js`),
    import(`${base}/firebase-auth.js`),
  ]);
  const app = initializeApp(cfg.firebase);
  const firebaseAuth = fb.getAuth(app);
  await fb.setPersistence(firebaseAuth, fb.browserLocalPersistence);

  PV.auth._impl = {
    getToken: () => (firebaseAuth.currentUser ? firebaseAuth.currentUser.getIdToken() : Promise.resolve(null)),
    signIn: () => fb.signInWithPopup(firebaseAuth, new fb.GoogleAuthProvider()),
    signOut: () => fb.signOut(firebaseAuth),
  };
  fb.onAuthStateChanged(firebaseAuth, (u) => {
    PV._setAuth({
      enabled: true,
      configured: true,
      user: u ? { name: u.displayName, email: u.email, photo: u.photoURL } : null,
    });
  });
}

init().catch((e) => {
  console.error("auth init failed", e);
  PV._setAuth({ enabled: true, configured: false, user: null });
});

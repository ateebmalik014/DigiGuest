# DigiGuest — Hackathon Prototype

DigiGuest is a local prototype for guest identity checks and contactless group check-in. It creates one QR pass for a booking group and lets the host scan the pass and check in the group.

## Demo limitations and safe test data

- Use synthetic/demo ID images only. Do not upload real IDs or selfies.
- ID text processing uses local OCR. Face matching and liveness are demo checks; they do not provide real biometric or production security.
- New ID and selfie uploads are held temporarily for verification and removed after the checks. They are not served from the public `/static` route. Older local test files are left untouched and ignored by Git.
- The local demo host login is `host@digiguest.com` / `123456`. These default credentials are for a local hackathon demonstration only.

## Requirements

- Windows with Python 3.10 or newer
- Tesseract OCR installed and available on `PATH`
- A modern browser (camera access is needed for QR scanning)

## Run locally (PowerShell)

From the project folder:

```powershell
cd C:\Users\ateeb\Documents\Codex\HACKATHON
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. The seeded demo booking IDs are `DG48291`, `DG73924`, `DG15683`, and `DG90417`.

## Demo checklist

1. Verify a booking and enter the primary guest name and group size.
2. Guests aged 5 or older need a synthetic ID image and selfie; under-5 guests are exempt.
3. Confirm the group pass and its QR code appear.
4. Open `http://127.0.0.1:8000/host.html` and sign in with the local demo credentials above.
5. Scan the QR code or enter its token, review the group summary, and complete check-in.

`data/` contains local databases, temporary upload storage, and the generated host-session signing key. It is ignored by Git so local demo data and secrets are not committed.

## Render deployment preparation

The root `Dockerfile` installs Tesseract OCR and the Python packages from `backend/requirements.txt`, then starts the existing FastAPI app with Uvicorn on Render's `PORT` (falling back to port 8000 for local Docker runs). The browser UI continues to be served by the same FastAPI app. Render should build this repository with its Docker runtime and the repository root as the build context.

Set these environment variables in the Render service before making it public:

- `DIGIGUEST_HOST_EMAIL`: the host dashboard login email.
- `DIGIGUEST_HOST_PASSWORD`: a new, strong host dashboard password. The local default `123456` is for local demos only.
- `DIGIGUEST_SESSION_SECRET`: a long, random secret used to sign host login cookies. Keep it private and stable across restarts so existing sessions remain valid until they expire.

The app stores SQLite at `data/digiguest.db`, the generated session key at `data/.host_session_secret` when no environment secret is supplied, and temporary uploads under `data/uploads/`. Those paths are excluded from Git and Docker build context. Render's ordinary service filesystem is ephemeral, so database changes and files can be lost on restart or redeploy. If the SQLite data must persist, attach a paid Render persistent disk mounted at `/app/data`; this stage does not migrate the database or configure a disk.

For a local production-style Docker smoke test (with Docker installed), run from the project root:

```powershell
docker build -t digiguest-local .
docker run --rm -p 8000:8000 digiguest-local
```

Then open `http://127.0.0.1:8000`. This local-only example uses the documented demo login; set new values in Render as described above.

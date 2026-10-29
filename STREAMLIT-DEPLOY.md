# Deploying the Loan Approval System to Streamlit Community Cloud

This app runs entirely inside Streamlit. No AWS, no separate backend.
The ML model is trained from `data/loan-data.csv` on first load (no pickle needed).

## Files that matter

- `streamlit_app.py` — the whole app (frontend + prediction logic)
- `services/` — CIBIL, explainability, and input-validation modules (imported by the app)
- `data/loan-data.csv` — training data (model trains from this on the cloud)
- `requirements-streamlit.txt` — Python dependencies for the cloud build

## Run locally

```bash
pip install -r requirements-streamlit.txt
streamlit run streamlit_app.py
```
Open http://localhost:8501

## Deploy on Streamlit Community Cloud (free)

1. Push this repository to GitHub (your account).
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click **New app** and select:
   - **Repository:** your repo (e.g. `karthiga33/<repo-name>`)
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
4. Under **Advanced settings**, there is nothing required, but ensure the
   dependency file used is `requirements-streamlit.txt`. If Streamlit Cloud
   only auto-detects `requirements.txt`, rename `requirements-streamlit.txt`
   to `requirements.txt` at the repo root (or add its 5 lines to the root
   `requirements.txt`). The default heavy `requirements/requirements.txt`
   is NOT used by Streamlit Cloud unless it sits at the repo root.
5. Click **Deploy**. First build takes a few minutes (it installs deps and
   trains the model once). You get a public URL like `your-app.streamlit.app`.

## Notes / limitations

- **Ephemeral storage:** Streamlit Cloud resets the filesystem on restart.
  Submitted applications persist only for the session (kept in memory so
  "Track Application" works during that session). For permanent storage you
  would add a database later — not required for a demo.
- **First load** trains the model from the CSV (a few seconds), then caches it
  in memory for the rest of the session.

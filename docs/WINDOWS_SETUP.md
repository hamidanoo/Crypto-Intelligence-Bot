# Windows Setup

The recommended path on Windows is Docker Desktop with WSL 2:

1. Install Docker Desktop and enable WSL 2.
2. Clone the repository and copy `.env.example` to `.env`.
3. Run `docker compose up --build`.
4. Open http://localhost:3000 and http://localhost:8000/health.

Without Docker, install Python 3.12+ and Node.js 20+, create a
Python virtual environment in `backend/`, install
`requirements.txt`, and run the backend with
`uvicorn app.main:app --reload`. Run the frontend with
`npm install` and `npm run dev` from `frontend/`. PostgreSQL and
Redis must be installed and running locally, with their URLs in
`.env`.

# NicheScope Frontend

Dark-mode analytics dashboard (Next.js 14 + Tailwind + Shadcn-style UI).

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## Backend

Ensure FastAPI is running on port 8000:

```bash
uvicorn app.main:app --reload
```

## Pages

| Route | Feature |
|-------|---------|
| `/anomalies` | Viral video search with filters |
| `/mass-analysis` | 10–20 competitor channels bulk analysis |
| `/keywords` | Evergreen keyword opportunity score |
| `/leaders` | Fastest-growing YouTube channels |

## Stack

- Next.js 14 App Router
- Tailwind CSS (dark theme)
- Lucide icons
- Axios → FastAPI backend

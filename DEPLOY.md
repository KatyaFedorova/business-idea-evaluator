# Deploying to Vercel

Free on the Hobby plan. Python 3.14 runs the FastAPI app as one function.

## Once

```bash
vercel login            # browser, one time
vercel link             # pick or create the project
```

## Environment variables

```bash
vercel env add ANTHROPIC_API_KEY production
vercel env add BIE_MAX_ATTACHMENT_MB production      # 4 — Vercel caps request bodies at 4.5 MB
vercel env add BIE_MAX_COST_PER_DAY_USD production   # 5.00
```

Everything else falls back to the defaults in `src/bie/config.py`.

## Deploy

```bash
vercel deploy           # preview URL
vercel deploy --prod    # production URL
```

## What to know about the platform

- **Request bodies cap at 4.5 MB**, so the 10 MB attachment limit must come down to 4 MB in
  this environment or an upload returns `413`.
- **Function duration caps at 300 s on Hobby.** A verdict round with live research takes
  60–120 s, so there is headroom, but no extension exists on this plan.
- **The daily spend ceiling is an in-process counter**, so it is per instance and resets on
  cold start and on every deploy. Set a monthly budget on the key in the Anthropic Console —
  that is the only hard stop.
- **Scale to zero** after about five minutes idle. The first request after that is slow.

## Keeping the key safe

The URL is public and anonymous by default: anyone who finds it spends your Anthropic credit.
Either set a Console budget on the key, or turn on Vercel Deployment Protection (Settings →
Deployment Protection) so only people with the password can reach it.

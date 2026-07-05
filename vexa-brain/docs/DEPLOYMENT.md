# Vexa Brain — Deployment Guide

> Deploy Vexa Brain as a FastAPI server for your Android app to connect to.

---

## Deployment Phases

| Phase | Platform | Cost | Duration | Purpose |
|-------|----------|------|----------|---------|
| **Phase 1** | Render (Free) | $0/month | Testing (1-2 weeks) | Validate brain behavior, test from Android app |
| **Phase 2** | Render (Paid) or Railway | $7/month | Extended testing | Remove cold starts, reliable uptime |
| **Phase 3** | AWS / GCP | $15-30/month | Production | Full control, scaling, custom domain |

---

## Phase 1: Free Deployment (Render)

### Prerequisites
1. [Render account](https://render.com) (free signup)
2. [MongoDB Atlas account](https://cloud.mongodb.com) (free tier — 512MB)
3. [Groq API key](https://console.groq.com) (free tier — 30 req/min)
4. Your code pushed to a Git repo (GitHub/GitLab)

### Step 1: Set Up MongoDB Atlas (Free)

1. Go to [MongoDB Atlas](https://cloud.mongodb.com) → Create free account
2. Create a new **Shared Cluster** (FREE tier — M0 Sandbox)
   - Provider: AWS
   - Region: Mumbai (ap-south-1) — closest to India
3. Set up Database Access:
   - Create a database user (e.g., `vexa_brain`)
   - Generate a strong password — **save it**
4. Set up Network Access:
   - Add IP: `0.0.0.0/0` (allow from anywhere — needed for Render)
5. Get your connection string:
   - Click **Connect** → **Drivers** → Copy the URI
   - Replace `<password>` with your actual password
   - Replace `myFirstDatabase` with `observeai`
   - Example: `mongodb+srv://vexa_brain:YOUR_PASS@cluster0.xxxxx.mongodb.net/observeai?retryWrites=true&w=majority`

### Step 2: Get Groq API Key

1. Go to [Groq Console](https://console.groq.com)
2. Create an API key
3. **Free tier**: 30 requests/minute, 14,400 requests/day — plenty for testing

### Step 3: Deploy to Render

**Option A: One-click deploy (Blueprint)**

1. Push your `vexa-brain/` code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**
3. Connect your repo
4. Render will detect `render.yaml` and auto-configure
5. Set environment variables when prompted:
   - `GROQ_API_KEY` = your Groq key
   - `MONGODB_URI` = your Atlas connection string

**Option B: Manual deploy**

1. Go to [Render Dashboard](https://dashboard.render.com) → **New** → **Web Service**
2. Connect your GitHub repo
3. Configure:
   - **Name**: `vexa-brain`
   - **Region**: Oregon (or nearest)
   - **Branch**: `main`
   - **Root Directory**: `vexa-brain` (if it's inside a larger repo)
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
4. Add environment variables:
   - `GROQ_API_KEY` = your Groq key
   - `MONGODB_URI` = your Atlas connection string
   - `MONGODB_DB_NAME` = `observeai`
   - `DEBUG` = `false`
5. Click **Create Web Service**

### Step 4: Verify Deployment

Once deployed (2-3 minutes), test these endpoints:

```bash
# Health check
curl https://vexa-brain.onrender.com/api/health

# Root info
curl https://vexa-brain.onrender.com/

# Knowledge stats
curl https://vexa-brain.onrender.com/api/knowledge/stats

# Test knowledge retrieval
curl "https://vexa-brain.onrender.com/api/knowledge/query?q=cognizant+interview"

# Test chat
curl -X POST https://vexa-brain.onrender.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"userId": "vamsi_001", "prompt": "What do you know about me?"}'
```

### ⚠️ Free Tier Limitations

- **Cold starts**: Server sleeps after 15 min of inactivity. First request after sleep takes 30-60 seconds.
- **512MB RAM**: Enough for Vexa Brain (it's lightweight).
- **750 hours/month**: Free tier provides enough for a single always-on service.
- **No persistent disk**: OKF knowledge files are re-deployed from Git each time. **This means learned knowledge is lost on redeploy**. For persistence, commit knowledge changes to Git or use Phase 2.

### Handling Knowledge Persistence on Free Tier

Since Render's free tier doesn't have persistent disk, here are options:

1. **Git-based persistence** (Recommended for testing):
   - The initial knowledge files deploy from your repo
   - New knowledge learned during runtime will be lost on redeploy
   - This is fine for testing — you're evaluating behavior, not building permanent memory

2. **MongoDB-based knowledge** (For later):
   - Store OKF nodes in MongoDB instead of filesystem
   - This requires a code change but enables persistence on any platform

---

## Phase 2: Paid Deployment ($5-7/month)

### Option A: Render Starter ($7/month)
- No cold starts (always running)
- Persistent disk available
- Same deployment as Phase 1, just upgrade the plan

### Option B: Railway (~$5/month usage-based)
1. Go to [Railway](https://railway.app)
2. **New Project** → **Deploy from GitHub repo**
3. Set environment variables
4. Railway auto-detects Python and deploys
5. Pay-as-you-go: ~$5/month for light usage

### Option C: VPS + Coolify ($4-7/month)
1. Get a VPS from Hetzner ($4/mo) or DigitalOcean ($6/mo)
2. Install [Coolify](https://coolify.io) — self-hosted PaaS
3. Deploy Vexa Brain via Docker
4. Full control, no cold starts, persistent storage

---

## Phase 3: Production (AWS/GCP)

### AWS Option (~$15-25/month)

| Service | Purpose | Cost |
|---------|---------|------|
| **ECS Fargate** | Run Docker container | ~$10/month (0.25 vCPU, 512MB) |
| **MongoDB Atlas** (M10) | Dedicated database | ~$10/month |
| **Route53** | Custom domain | ~$1/month |
| **ACM** | Free SSL certificate | Free |

**Steps:**
1. Push Docker image to ECR (Elastic Container Registry)
2. Create ECS Fargate task with your image
3. Set up Application Load Balancer
4. Configure Route53 for custom domain
5. Set environment variables in ECS task definition

### GCP Option (~$15-25/month)

| Service | Purpose | Cost |
|---------|---------|------|
| **Cloud Run** | Serverless container | ~$5-10/month |
| **MongoDB Atlas** (M10) | Dedicated database | ~$10/month |
| **Cloud DNS** | Custom domain | ~$1/month |

**Steps:**
1. Build Docker image: `docker build -t vexa-brain .`
2. Push to GCR: `gcloud builds submit --tag gcr.io/YOUR_PROJECT/vexa-brain`
3. Deploy to Cloud Run: `gcloud run deploy vexa-brain --image gcr.io/YOUR_PROJECT/vexa-brain --allow-unauthenticated`
4. Set env vars: `gcloud run services update vexa-brain --set-env-vars="GROQ_API_KEY=xxx,MONGODB_URI=xxx"`

---

## Connecting Android App

After deployment, update your Android app to point to the deployed URL:

```kotlin
// Before (local)
const val BRAIN_URL = "http://192.168.1.100:8000"

// After (Render)
const val BRAIN_URL = "https://vexa-brain.onrender.com"

// After (production)
const val BRAIN_URL = "https://brain.vexa.app"
```

---

## Cost Summary

| Phase | Monthly Cost | What You Get |
|-------|-------------|--------------|
| **Testing** | $0 | Render Free + Atlas Free + Groq Free |
| **Reliable Testing** | $7 | Render Starter + Atlas Free + Groq Free |
| **Production** | $15-25 | Cloud Run/ECS + Atlas M10 + Groq Paid |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | ✅ | — | Groq API key for LLM |
| `MONGODB_URI` | ✅ | `mongodb://localhost:27017/observeai` | MongoDB connection string |
| `MONGODB_DB_NAME` | ❌ | `observeai` | Database name |
| `LLM_MODEL` | ❌ | `llama-3.3-70b-versatile` | Groq model name |
| `LLM_TEMPERATURE` | ❌ | `0.3` | LLM temperature |
| `LLM_MAX_TOKENS` | ❌ | `2048` | Max response tokens |
| `HOST` | ❌ | `0.0.0.0` | Server bind host |
| `PORT` | ❌ | `8000` | Server bind port |
| `DEBUG` | ❌ | `true` | Enable debug mode / auto-reload |

---

## Troubleshooting

### "Application failed to respond" on Render
- Check logs in Render dashboard
- Ensure `GROQ_API_KEY` is set correctly
- Ensure `MONGODB_URI` is correct and Atlas allows connections from `0.0.0.0/0`

### Cold start taking too long
- Free tier limitation — upgrade to Starter plan ($7/month)
- Or use a cron job to ping your health endpoint every 14 minutes

### Knowledge not loading
- Check `/api/knowledge/stats` endpoint
- Ensure `knowledge/` directory is committed to Git and deployed

### MongoDB connection refused
- Verify Atlas network access allows `0.0.0.0/0`
- Check the connection string format (use `mongodb+srv://` for Atlas)
- Ensure database user password has no special URL characters (encode them)

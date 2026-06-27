# Dockerfile — RoleRadar full container (includes Chromium for Playwright).
#
# We start from Microsoft's official Playwright Python image, which already
# ships Chromium + every Linux system library it needs. This is the "bring your
# own kitchen" approach: instead of fighting App Service's locked-down runtime,
# we define the whole environment ourselves so Playwright works in the cloud.
#
# The image tag (v1.60.0) is pinned to match playwright==1.60.0 in our deps, and
# Ubuntu 22.04 "jammy" ships Python 3.10 — compatible with pyautogen==0.2.35
# (which requires Python < 3.13).
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

# Install Python dependencies first (this layer is cached unless requirements
# change, so rebuilds are fast).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Belt-and-suspenders: ensure the Chromium build is present (already in the base
# image, but this guarantees the exact version our scraper expects).
RUN python -m playwright install chromium

# Copy the rest of the app (code + seed.db dataset). .dockerignore keeps secrets
# (.env) and junk out of the image.
COPY . .

# App Service maps its public port to whatever the container exposes; we use 8000.
EXPOSE 8000

# Launch the FastAPI app. APScheduler starts inside this same process and runs
# the scheduled full scrape (interval set by SCRAPE_INTERVAL_HOURS).
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

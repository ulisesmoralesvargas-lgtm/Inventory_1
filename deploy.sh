#!/bin/bash
# Quick deployment script for Google Cloud Run
# Usage: bash deploy.sh

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Google Cloud Run Deployment Script${NC}"
echo "===================================="

# Check prerequisites
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}ERROR: gcloud CLI not found. Please install Google Cloud SDK.${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}ERROR: Docker not found. Please install Docker.${NC}"
    exit 1
fi

# Get configuration
read -p "Enter GCP Project ID: " PROJECT_ID
read -p "Enter Cloud Run Service Name (default: inventory-frontend): " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-inventory-frontend}
read -p "Enter region (default: us-central1): " REGION
REGION=${REGION:-us-central1}
read -p "Enter API URL (e.g., https://inventory-api-xxx.run.app): " API_URL

# Set gcloud project
echo -e "${YELLOW}Setting GCP project...${NC}"
gcloud config set project $PROJECT_ID

# Build Docker image
echo -e "${YELLOW}Building Docker image...${NC}"
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

# Deploy to Cloud Run
echo -e "${YELLOW}Deploying to Cloud Run...${NC}"
gcloud run deploy $SERVICE_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,CLOUD_RUN_API_URL=$API_URL" \
  --cpu 1 \
  --memory 512Mi \
  --timeout 300

# Get service account
SERVICE_ACCOUNT=$(gcloud run services describe $SERVICE_NAME \
  --region $REGION \
  --format='value(spec.template.spec.serviceAccountName)')

echo -e "${YELLOW}Granting IAM permissions...${NC}"

# Grant Secret Manager access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SERVICE_ACCOUNT \
  --role=roles/secretmanager.secretAccessor \
  --quiet

# Grant Cloud SQL Client role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SERVICE_ACCOUNT \
  --role=roles/cloudsql.client \
  --quiet

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
  --region $REGION \
  --format='value(status.url)')

echo -e "${GREEN}✅ Deployment successful!${NC}"
echo "Service URL: $SERVICE_URL"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Set up Firebase authentication in your GCP project"
echo "2. Create secrets in Secret Manager"
echo "3. Update backend to use Cloud SQL"
echo ""
echo "For more details, see DEPLOYMENT.md"

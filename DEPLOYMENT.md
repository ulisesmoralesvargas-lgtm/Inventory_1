# Google Cloud Run Deployment Guide

## Prerequisites

1. **Google Cloud Project**: Create a GCP project
2. **gcloud CLI**: Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
3. **Docker**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop)
4. **Firebase Project**: Create Firebase project in same GCP project
5. **Cloud SQL**: Create PostgreSQL instance in Cloud SQL

## Step 1: Set Environment Variables

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
export SERVICE_NAME="inventory-frontend"
export API_SERVICE_NAME="inventory-api"
```

## Step 2: Authenticate with Google Cloud

```bash
gcloud auth login
gcloud config set project $PROJECT_ID
```

## Step 3: Create Cloud SQL Instance

```bash
gcloud sql instances create inventory-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=$REGION \
  --no-backup

# Create database
gcloud sql databases create inventory --instance=inventory-db

# Create user
gcloud sql users create postgres --instance=inventory-db --password
```

## Step 4: Set Up Firebase Authentication

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Create new project (linked to your GCP project)
3. Enable Authentication (Email/Password)
4. Create service account and download JSON key

## Step 5: Create Google Cloud Secret Manager Secrets

```bash
# Firebase config
echo '{"type":"service_account",...}' | gcloud secrets create firebase-key --data-file=-

# Database credentials
echo "postgresql://postgres:PASSWORD@INSTANCE_IP:5432/inventory" | \
  gcloud secrets create database-url --data-file=-

# API URL (after deploying backend)
echo "https://inventory-api-xxx.run.app" | \
  gcloud secrets create cloud-run-api-url --data-file=-
```

## Step 6: Build and Deploy Frontend

```bash
# Build image
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

# Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,CLOUD_RUN_API_URL=https://inventory-api-xxx.run.app" \
  --add-cloudsql-instances $PROJECT_ID:$REGION:inventory-db \
  --cpu 1 \
  --memory 512Mi \
  --timeout 300
```

## Step 7: Grant Cloud Run Service Account Permissions

```bash
# Get service account email
SERVICE_ACCOUNT=$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(spec.template.spec.serviceAccountName)')

# Grant Secret Manager access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SERVICE_ACCOUNT \
  --role=roles/secretmanager.secretAccessor

# Grant Cloud SQL Client role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SERVICE_ACCOUNT \
  --role=roles/cloudsql.client
```

## Step 8: Configure Firebase Service Account in Cloud Run

```bash
# Upload service account key to Secret Manager
gcloud secrets create firebase-credentials --data-file=firebase-key.json

# Update Cloud Run to use it
gcloud run deploy $SERVICE_NAME \
  --update-secrets GOOGLE_APPLICATION_CREDENTIALS=firebase-credentials:latest \
  --region $REGION
```

## Step 9: Environment Variables for Cloud Run

Set these in Cloud Run → Edit & Deploy → Runtime settings:

```
GOOGLE_CLOUD_PROJECT=your-project-id
CLOUD_RUN_API_URL=https://inventory-api-xxxxx.run.app
CLOUD_SQL_HOST=INSTANCE_IP
CLOUD_SQL_USER=postgres
CLOUD_SQL_PASSWORD=your_password
CLOUD_SQL_DATABASE=inventory
```

## Monitoring

### View logs
```bash
gcloud run logs read $SERVICE_NAME --region $REGION --limit 50
```

### Monitor performance
```bash
gcloud monitoring time-series list --filter 'resource.type="cloud_run_revision"'
```

## Troubleshooting

### Connection to Cloud SQL fails
- Verify Cloud Run service account has `roles/cloudsql.client`
- Check Cloud SQL instance is in same region or has public IP
- Test connection: `psql -h INSTANCE_IP -U postgres -d inventory`

### Firebase authentication fails
- Verify Firebase service account JSON is correct
- Check `GOOGLE_APPLICATION_CREDENTIALS` env var points to correct secret
- Review Firebase Console for user creation

### Secrets not accessible
- Run: `gcloud secrets get-iam-policy SECRET_NAME`
- Ensure service account has `roles/secretmanager.secretAccessor`

## Deployment via GitHub Actions (Optional)

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Cloud Run

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - uses: google-github-actions/setup-gcloud@v1
        with:
          service_account_key: ${{ secrets.GCP_SA_KEY }}
          project_id: ${{ secrets.GCP_PROJECT_ID }}
      
      - run: gcloud builds submit --tag gcr.io/${{ secrets.GCP_PROJECT_ID }}/inventory-frontend
      
      - run: |
          gcloud run deploy inventory-frontend \
            --image gcr.io/${{ secrets.GCP_PROJECT_ID }}/inventory-frontend \
            --platform managed \
            --region us-central1
```

## Security Best Practices

1. **Always use secrets**: Never commit credentials
2. **Limit permissions**: Use IAM roles principle of least privilege
3. **Enable audit logging**: Monitor who accesses what
4. **Use VPC Connector**: For private Cloud SQL connections
5. **Enable HTTPS**: Cloud Run provides free SSL/TLS certificates

# Local Development Guide

## Prerequisites
1.  **Python Environment**: Activate `venv`.
    ```powershell
    .\venv\Scripts\activate
    ```
2.  **Environment Variables**: Ensure `.env` exists with:
    ```
    GOOGLE_CLOUD_PROJECT=agentic-hackathon-v4
    GCS_BUCKET_NAME=receipt-deca-history-agentic-hackathon-v4
    ```
3.  **Authentication**: Ensure you are logged in with Application Default Credentials.
    ```powershell
    gcloud auth application-default login
    ```
    *(Note: verified as working on your machine)*

## Running the App
Execute the following command in the project directory:

```powershell
streamlit run app.py
```

The application will open in your browser at `http://localhost:8501`.
Changes to `app.py` will be automatically detected, and you can simply refresh the browser to see updates.

## Deploying
Only deploy when you are satisfied with your local changes:
```powershell
gcloud run deploy receipt-deca --source . --region asia-northeast1 --allow-unauthenticated --set-env-vars GCS_BUCKET_NAME=receipt-deca-history-agentic-hackathon-v4
```

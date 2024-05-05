
# Steps

1. Start the Codespace or Dev Container (which contains a local PostgreSQL container).

1. Install the FastAPI app in editable mode:

```bash
python3 -m pip install -e src
```

1. Copy either `.env.azure` or `.env.devcontainer` to `.env` and adjust env variables to your setup.

1. Run the FastAPI app

```bash
python3 -m uvicorn fastapi_app:app --reload --port=8000
```

1. Run the frontend

```bash
cd src/frontend
npm install
npm run dev
```

1. Open the browser at `http://localhost:5173/` and you will see the frontend.

## Setup permissions for Azure OpenAI endpoint

If the permisions have not yet been setup, you can configure them using the following script:

```
export AZURE_RESOURCE_GROUP=REPLACE_ME
export AZURE_PRINCIPAL_ID=$(az ad signed-in-user show --output tsv --query "id")
export AZURE_SUBSCRIPTION_ID=$(az account show --query "name" --out tsv)

roles=(
    "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" # Cognitive Services OpenAI User
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1" # Storage Blob Data Reader
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe" # Storage Blob Data Contributor
    "1407120a-92aa-4202-b7e9-c0e197c71c8f" # Search Index Data Reader
    "8ebe5a00-799e-43f5-93ac-243d3dce84a7" # Search Index Data Contributor
)

for role in "${roles[@]}"; do
    az role assignment create \
        --role "$role" \
        --assignee-object-id "$AZURE_PRINCIPAL_ID" \
        --scope /subscriptions/"$AZURE_SUBSCRIPTION_ID"/resourceGroups/"$AZURE_RESOURCE_GROUP" \
        --assignee-principal-type User
done
```

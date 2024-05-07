
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

If the permisions have not yet been setup, you can configure them using the following script. It will display the commands and ask for confirmation before executing, verify that everything is correct before confirming.

Specifically, verify that the Azure OpenAI resource you want to use is in the the resource group since permissions are applied at the resource group level.

```
export AZURE_RESOURCE_GROUP=<REPLACE_ME>
./scripts/roles.sh
```

The script will figure out the `AZURE_PRINCIPAL_ID` and `AZURE_SUBSCRIPTION_ID` from the signed in user and currently selected subscription but you also specify them before running the script.

```
export AZURE_PRINCIPAL_ID=<REPLACE_ME>
export AZURE_SUBSCRIPTION_ID=<REPLACE_ME>
export AZURE_RESOURCE_GROUP=<REPLACE_ME>
./scripts/roles.sh
```

if [[ -z "${AZURE_RESOURCE_GROUP}" ]]; then
    echo "Please set the AZURE_RESOURCE_GROUP environment variable"
    exit 1
fi

# Input
AZURE_PRINCIPAL_ID=${AZURE_PRINCIPAL_ID:-$(az ad signed-in-user show --output tsv --query "id")}
AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID:-$(az account show --query "name" --out tsv)}

# For display only
AZURE_PRINCIPAL_MAIL=$(az ad signed-in-user show --output tsv --query "mail")

echo "Assigning roles to principal ${AZURE_PRINCIPAL_MAIL} in resource-group ${AZURE_RESOURCE_GROUP} in subscription ${AZURE_SUBSCRIPTION_ID}"
echo

roles=(
    "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" # Cognitive Services OpenAI User
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1" # Storage Blob Data Reader
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe" # Storage Blob Data Contributor
    "1407120a-92aa-4202-b7e9-c0e197c71c8f" # Search Index Data Reader
    "8ebe5a00-799e-43f5-93ac-243d3dce84a7" # Search Index Data Contributor
)
function roles_commands() {
    for role in "${roles[@]}"; do
        echo az role assignment create \
            --role "$role" \
            --assignee-object-id "$AZURE_PRINCIPAL_ID" \
            --scope /subscriptions/"$AZURE_SUBSCRIPTION_ID"/resourceGroups/"$AZURE_RESOURCE_GROUP" \
            --assignee-principal-type User
    done
}

CMD=$(roles_commands)

echo "${CMD}"
echo

# Do we proceed?
read -p "Do you want to execute the commands? [y|N] " -n 1 -r PROCEED
echo

if [[ ${PROCEED} != 'y'  ]]
then
    echo "Bailing"
    exit
fi

eval "${CMD}"

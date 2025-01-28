import asyncio
import requests
import json
import os
from azure.identity import DeviceCodeCredential
from graph import Graph
import sys
from datetime import datetime

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../config.json")

def print_device_code_flow(stage, verification_uri, user_code, expires_on):
    """Stampa il device code in un formato JSON per essere catturato da Flask."""
    print(json.dumps({
        "stage": stage,
        "verification_uri": verification_uri,
        "user_code": user_code,
        "expires_at": expires_on.isoformat(),
        "message": f"Vai su {verification_uri}"
    }))
    sys.stdout.flush()

def load_config():
    """Carica la configurazione da un file JSON."""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Il file {CONFIG_FILE} non esiste.")
    with open(CONFIG_FILE, "r") as file:
        return json.load(file)

async def get_all_file_versions(graph, token, folder_id=None, folder_path=""):
    """Recupera il versioning di tutti i file su OneDrive, inclusi quelli nelle sottocartelle, con autore."""
    headers = {'Authorization': f'Bearer {token}'}

    try:
        # Imposta l'endpoint per la cartella corrente
        url = f'https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children' if folder_id else 'https://graph.microsoft.com/v1.0/me/drive/root/children'
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        items = response.json()

        files = []
        for item in items.get('value', []):
            item_id = item.get('id')
            item_name = item.get('name', 'N/A')
            is_folder = 'folder' in item

            # Percorso completo del file o della cartella
            current_path = f"{folder_path}/{item_name}".strip("/")

            if is_folder:
                # Ricorsione per esplorare le sottocartelle
                subfolder_files = await get_all_file_versions(graph, token, folder_id=item_id, folder_path=current_path)
                files.extend(subfolder_files)
            else:
                # Recupera le versioni del file e l'autore
                url_versions = f'https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/versions'
                response_versions = requests.get(url_versions, headers=headers)
                response_versions.raise_for_status()
                versions = response_versions.json()

                last_modified_by = item.get('lastModifiedBy', {}).get('user', {}).get('displayName', 'N/A')

                files.append({
                    "path": current_path,
                    "name": item_name,
                    "author": last_modified_by,
                    "versions": [
                        {
                            "id": version.get('id'),
                            "lastModified": version.get('lastModifiedDateTime'),
                            "size": version.get('size'),
                            "author": version.get('lastModifiedBy', {}).get('user', {}).get('displayName', 'N/A')
                        } for version in versions.get('value', [])
                    ]
                })
        return files
    except Exception as e:
        print(json.dumps({"stage": "error", "message": str(e)}))
        sys.stdout.flush()
        return []

async def main():
    try:
        config = load_config()
        azure_settings = config['azure']
        scopes = azure_settings.get("graphUserScopes", "").split()

        # Primo e unico step di autenticazione
        credential = DeviceCodeCredential(
            client_id=azure_settings['clientId'],
            tenant_id=azure_settings['tenantId'],
            prompt_callback=lambda uri, code, exp: print_device_code_flow(1, uri, code, exp)
        )
        credential.get_token(*scopes)

        # Recupera e stampa le versioni dei file
        graph = Graph(azure_settings, credential=credential)
        token = await graph.get_user_token()
        print("DEBUG: Token generato:", token)

        files = await get_all_file_versions(graph, token)
        print(json.dumps({
            "stage": 2,
            "files": files
        }))
        sys.stdout.flush()
    except Exception as e:  # Clausola except necessaria
        print(json.dumps({"stage": "error", "message": str(e)}))
        sys.stdout.flush()


# Esegui il programma
asyncio.run(main())

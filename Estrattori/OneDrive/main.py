import asyncio
import requests
import json
import os
import pandas as pd
from azure.identity import DeviceCodeCredential
from graph import Graph
import sys
from datetime import datetime, timedelta, timezone

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../config.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "onedrive_versions.xlsx")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
ONEDRIVE_USER_FILE = os.path.abspath("./Estrattori/OneDrive/onedrive_user.json")

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

def save_token(token_data):
    """Salva il token in un file JSON."""
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

def load_token():
    """Carica il token dal file JSON, se esiste e non è scaduto."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)

        # Controlliamo se il token è scaduto
        expires_on = datetime.fromisoformat(token_data["expires_on"])
        if expires_on > datetime.now(timezone.utc):
            print(f"Token ricaricato da file, valido fino a {expires_on}")
            return token_data["access_token"]

    return None  # Il token è scaduto o non esiste

async def authenticate():
    """Gestisce l'autenticazione, memorizzando il token per riutilizzi futuri."""
    config = load_config()
    azure_settings = config['azure']
    scopes = azure_settings.get("graphUserScopes", "").split()

    # Verifica se il token esiste e non è scaduto
    token = load_token()
    if token:
        return token  # Se il token è ancora valido, lo restituiamo subito

    # Se il token non è valido, procediamo con l'autenticazione
    credential = DeviceCodeCredential(
        client_id=azure_settings['clientId'],
        tenant_id=azure_settings['tenantId'],
        prompt_callback=lambda uri, code, exp: print_device_code_flow(1, uri, code, exp)
    )
    access_token = credential.get_token(*scopes).token

    # Salviamo il nuovo token con la data di scadenza
    expires_on = datetime.now(timezone.utc) + timedelta(hours=1)  # Il token scade dopo 1 ora
    save_token({
        "access_token": access_token,
        "expires_on": expires_on.isoformat()
    })

    print(f"Nuovo token generato, valido fino a {expires_on}")
    return access_token

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

                for version in versions.get('value', []):
                    files.append({
                        "ID File": item_id, 
                        "Percorso": current_path,
                        "Nome File": item_name,
                        "Autore Ultima Modifica": last_modified_by,
                        "ID Versione": version.get('id'),
                        "Ultima Modifica": version.get('lastModifiedDateTime'),
                        "Dimensione (byte)": version.get('size', 'N/A'),
                        "Autore Versione": version.get('lastModifiedBy', {}).get('user', {}).get('displayName', 'N/A')
                    })
        return files
    except Exception as e:
        print(json.dumps({"stage": "error", "message": str(e)}))
        sys.stdout.flush()
        return []

def get_onedrive_user(token):
    """Recupera e salva il nome dell'utente autenticato su OneDrive."""
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://graph.microsoft.com/v1.0/me"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        user_info = response.json()
        user_name = user_info.get("displayName", "Utente sconosciuto")
        user_email = user_info.get("mail", user_info.get("userPrincipalName", "Email sconosciuta"))

        user_data = {
            "name": user_name,
            "email": user_email
        }
        # Salva i dati nel file JSON
        with open(ONEDRIVE_USER_FILE, "w") as file:
            json.dump(user_data, file)

        print(f"Utente OneDrive salvato: {user_name} ({user_email})")
        return f"{user_name} ({user_email})"

    except Exception as e:
        print(f"Errore nel recupero dell'utente OneDrive: {e}")
        return "Utente sconosciuto"

async def save_to_excel(data):
    """Salva i dati in un file Excel nella cartella Estrattori/OneDrive."""
    df = pd.DataFrame(data)
    df.to_excel(OUTPUT_FILE, index=False, engine='openpyxl')
    print(f"File Excel salvato in: {OUTPUT_FILE}")

async def main():
     try:
        token = await authenticate()  # Usa il token salvato o autentica di nuovo

        config = load_config()
        graph = Graph(config['azure'], credential=None) 
        get_onedrive_user(token)
        files = await get_all_file_versions(graph, token)
        await save_to_excel(files)
     except Exception as e:
        print(json.dumps({"stage": "error", "message": str(e)}))
        sys.stdout.flush()

# Esegui il programma
asyncio.run(main())

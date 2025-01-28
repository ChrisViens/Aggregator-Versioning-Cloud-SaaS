import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import sys

SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']
# Calcola il percorso assoluto del file "secret.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../../"))
CONFIG_FILE = os.path.join(MAIN_DIR, "config.json")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
REDIRECT_URI = "http://localhost:8080/"

def load_config():
    """Carica le informazioni da config.json."""
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    return config.get('gdrive', {})

def authenticate():
    """Autentica l'utente e restituisce le credenziali."""
    creds = None
    try:
        # Caricamento del token dal file
        if os.path.exists(TOKEN_FILE):
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
                print("DEBUG: Credenziali caricate da token.json")
            except Exception as e:
                print(f"ERRORE: Impossibile caricare il file token.json: {e}")
                creds = None

        # Verifica se il token è valido
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    print("DEBUG: Il token è scaduto. Tentativo di aggiornamento...")
                    creds.refresh(Request())
                    print("DEBUG: Token aggiornato con successo.")
                except Exception as e:
                    print(f"ERRORE: Impossibile aggiornare il token: {e}")
                    creds = None

            # Avvio di una nuova autenticazione se il refresh fallisce o non è possibile
            if not creds or not creds.valid:
                print("DEBUG: Nessun token valido trovato. Avvio di una nuova autenticazione...")
                gdrive_config = load_config()
                secret_path = 'temp_secret.json'
                with open(secret_path, 'w') as secret_file:
                    json.dump(gdrive_config, secret_file)
                try:
                    # Avvia il flusso OAuth
                    flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
                    creds = flow.run_local_server(
                        port=8080,
                        authorization_prompt_message="Visita questo URL per autenticarti: {url}",
                        success_message="Autenticazione completata! Puoi chiudere questa finestra.",
                        open_browser=True
                    )
                    print("DEBUG: Autenticazione completata con successo.")
                except Exception as e:
                    print(f"ERRORE: Problema durante la nuova autenticazione: {e}")
                    creds = None
                finally:
                    os.remove(secret_path)  # Rimuove il file temporaneo

                # Salva il nuovo token
                if creds:
                    with open(TOKEN_FILE, 'w') as token:
                        token.write(creds.to_json())
                        print("DEBUG: Nuove credenziali salvate in token.json")
    except Exception as e:
        print(f"ERRORE: Problema durante il processo di autenticazione: {e}")
        creds = None

    # Interrompe l'esecuzione se l'autenticazione fallisce
    if not creds:
        print("ERRORE: Autenticazione fallita. Verifica le credenziali e riprova.")
        sys.exit(1)

    return creds

def format_versions(revisions):
    """Aggiunge un indice leggibile alle revisioni."""
    for i, revision in enumerate(revisions, start=1):
        revision['readableVersion'] = f"Versione {i}"
    return revisions

def get_file_revisions(service, file_id):
    """Recupera le versioni di un file, includendo la dimensione (se disponibile)."""
    try:
        revisions = service.revisions().list(
            fileId=file_id, fields="revisions(id, modifiedTime, lastModifyingUser(displayName), size)"
        ).execute()

        # Formatta le revisioni con numeri leggibili
        formatted_revisions = format_versions(revisions.get('revisions', []))

        # Aggiungi una dimensione predefinita "N/A" se non disponibile
        for revision in formatted_revisions:
            revision['size'] = revision.get('size', 'N/A')

        return formatted_revisions
    except Exception as e:
        print(f"Errore nel recupero delle versioni per il file {file_id}: {e}")
        return []

def get_files_and_revisions(service, folder_id='root'):
    """Recupera i file e le loro versioni, inclusi quelli nelle sottocartelle, con gli autori."""
    files_info = []
    query = f"'{folder_id}' in parents and trashed = false"
    response = service.files().list(q=query, fields="files(id, name, mimeType, owners(displayName))").execute()

    for file in response.get('files', []):
        file_id = file['id']
        file_name = file['name']
        mime_type = file['mimeType']
        file_owner = file.get('owners', [{}])[0].get('displayName', 'N/A')

        if mime_type == 'application/vnd.google-apps.folder':
            # Esplora ricorsivamente le sottocartelle
            subfolder_files = get_files_and_revisions(service, folder_id=file_id)
            files_info.extend(subfolder_files)
        else:
            # Recupera le versioni del file
            revisions = get_file_revisions(service, file_id)
            files_info.append({
                "file_name": file_name,
                "file_id": file_id,
                "owner": file_owner,
                "revisions": revisions
            })

    return files_info

if __name__ == '__main__':
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)

    folder_id = sys.argv[1] if len(sys.argv) > 1 else 'root'
    files_and_revisions = get_files_and_revisions(service, folder_id)

    # Salva i risultati in un file JSON
    with open('./Estrattori/GDrive/drive_revisions.json', 'w', encoding='utf-8') as f:
        json.dump(files_and_revisions, f, indent=2)
    print(json.dumps(files_and_revisions, indent=2))

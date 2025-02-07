import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import sys
from openpyxl import Workbook
import pandas as pd

SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']
# Calcola il percorso assoluto del file "secret.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../../"))
CONFIG_FILE = os.path.join(MAIN_DIR, "config.json")
TOKEN_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "token.json"))
REDIRECT_URI = "http://localhost:8080/"
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "output.xlsx")
GOOGLE_DRIVE_USER_FILE = os.path.abspath("./Estrattori/GDrive/google_drive_user.json")

def load_config():
    """Carica le informazioni da config.json."""
    if not os.path.exists(CONFIG_FILE):
        print("DEBUG: Il file di configurazione {CONFIG_FILE} non esiste.")
        sys.exit(1)
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    return config.get('gdrive', {})

def authenticate():
    """Autentica l'utente e restituisce le credenziali."""
    creds = None
    try:
        # Controllo se il file token.json esiste
        if os.path.exists(TOKEN_FILE):
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
                print(f"Token caricato correttamente da {TOKEN_FILE}")
            except Exception as e:
                print(f"ERRORE: Problema nel caricamento del token.json: {e}")
                creds = None

        # Se il token è scaduto, aggiornamento
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Il token è scaduto. Tentativo di aggiornamento...")
                creds.refresh(Request())
                print("Token aggiornato con successo!")

                # Salvataggio del token aggiornato
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
                    print(f"Token aggiornato salvato correttamente in {TOKEN_FILE}")
            except Exception as e:
                print(f"ERRORE: Impossibile aggiornare il token: {e}")
                creds = None

        # Nuova autenticazione
        if not creds or not creds.valid:
            print("Nessun token valido trovato. Avvio di una nuova autenticazione...")

            gdrive_config = load_config()
            if not gdrive_config:
                print("ERRORE: Configurazione Google Drive mancante in config.json.")
                sys.exit(1)

            secret_path = os.path.join(SCRIPT_DIR, 'temp_secret.json')
            try:
                 with open(secret_path, 'w') as secret_file:
                    json.dump(gdrive_config, secret_file)
                
                 # Avvia il flusso OAuth
                 flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
                 creds = flow.run_local_server(
                 port=8080,
                 authorization_prompt_message="Visita questo URL per autenticarti: {url}",
                 success_message="Autenticazione completata! Puoi chiudere questa finestra.",
                 prompt="consent", 
                 access_type="offline",
                 open_browser=True
                 )
                 print("DEBUG: Autenticazione completata con successo.")
                    
                    # Salva il nuovo token
                 with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
                    print("DEBUG: Nuove credenziali salvate in token.json")
            except Exception as e:
                    print(f"ERRORE: Problema durante la nuova autenticazione: {e}")
                    creds = None
            finally:
                    if os.path.exists(secret_path):
                        os.remove(secret_path)  # Rimuove il file temporaneo
    except Exception as e:
        print(f"ERRORE: Problema durante il processo di autenticazione: {e}")
        creds = None

    if not creds:
        print("ERRORE: Autenticazione fallita. Verifica le credenziali e riprova.")
        sys.exit(1)

    return creds

def get_file_path(service, file_id, drive_service):
    """Ricostruisce il percorso completo del file risalendo le cartelle."""
    path_segments = []
    
    while file_id:
        file_metadata = drive_service.files().get(fileId=file_id, fields="id, name, parents").execute()
        path_segments.insert(0, file_metadata.get("name", "Unknown"))

        parents = file_metadata.get("parents", [])
        file_id = parents[0] if parents else None 
    
    return "/".join(path_segments) 

def format_versions(revisions):
    """Aggiunge un indice leggibile alle revisioni."""
    for i, revision in enumerate(revisions, start=1):
        revision['readableVersion'] = float(i+1)
    return revisions

def get_file_revisions(service, file_id):
    """Recupera le versioni di un file con dettagli."""
    try:
        revisions = service.revisions().list(
            fileId=file_id, 
            fields="revisions(id, modifiedTime, lastModifyingUser(displayName), size)"
        ).execute()

        revisions_list = revisions.get('revisions', [])
        return [
            {
                "Versione": float(i+1),
                "Ultima Modifica": rev.get('modifiedTime', 'N/A'),
                "Autore Modifica": rev.get('lastModifyingUser', {}).get('displayName', 'N/A'),
                "Dimensione (byte)": rev.get('size', 'N/A')
            }
            for i, rev in enumerate(revisions_list)
        ]
    except Exception as e:
        print(f"Errore nel recupero delle versioni per il file {file_id}: {e}")
        return []

def get_files_and_revisions(service, folder_id='root', folder_path="Il Mio Drive"):
    """Recupera i file e le loro versioni, esplorando tutte le sottocartelle."""
    files_info = []
    query = f"'{folder_id}' in parents and trashed = false"
    
    response = service.files().list(q=query, fields="files(id, name, mimeType, owners(displayName))").execute()

    for file in response.get('files', []):
        file_id = file['id']
        file_name = file['name']
        file_owner = file.get('owners', [{}])[0].get('displayName', 'N/A')
        
        # Costruisce il percorso completo del file
        if folder_id == 'root':
            current_folder_path = "Il Mio Drive"
        else:
            current_folder_path = folder_path

        if file['mimeType'] == 'application/vnd.google-apps.folder':
            # Ricorsione: esplora la sottocartella
            subfolder_path = f"{current_folder_path}/{file_name}".strip("/")
            subfolder_files = get_files_and_revisions(service, file_id, subfolder_path)
            files_info.extend(subfolder_files)
        else:
            # Recupera le versioni del file
            revisions = get_file_revisions(service, file_id)
            for rev in revisions:
                files_info.append({
                    "Percorso": f"{current_folder_path}/{file_name}".strip("/"),
                    "Nome File": file_name,
                    "ID File": file_id,
                    "Proprietario": file_owner,
                    "Versione": float(rev["Versione"]),
                    "Ultima Modifica": rev["Ultima Modifica"],
                    "Autore Ultima Modifica": rev["Autore Modifica"],
                    "Dimensione (byte)": rev["Dimensione (byte)"]
                })

    return files_info

def save_to_excel(data, output_file=OUTPUT_FILE):
    """Salva i dati in un file Excel con colonne separate nella cartella Estrattori/GDrive."""
    df = pd.DataFrame(data)
    df["Versione"] = df["Versione"].astype(str)
    df.to_excel(output_file, index=False, engine='openpyxl')
    print(f"File Excel salvato correttamente in: {output_file}")

def get_google_drive_user(service):
    """Recupera e salva l'email dell'utente autenticato su Google Drive."""
    try:
        user_info = service.about().get(fields="user(emailAddress,displayName)").execute()
        user_email = user_info.get("user", {}).get("emailAddress", "Utente sconosciuto")
        user_name = user_info.get("user", {}).get("displayName", "Utente sconosciuto")

        user_data = {
            "name": user_name,
            "email": user_email
        }

        # Salva i dati nel file JSON
        with open(GOOGLE_DRIVE_USER_FILE, "w") as file:
            json.dump(user_data, file)

        print(f"Utente Google Drive salvato: {user_name} ({user_email})")
        return f"{user_name} ({user_email})"

    except Exception as e:
        print(f"Errore nel recupero dell'utente Google Drive: {e}")
        return "Utente sconosciuto"

if __name__ == '__main__':
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)
    get_google_drive_user(service)
    folder_id = sys.argv[1] if len(sys.argv) > 1 else 'root'
    files_and_revisions = get_files_and_revisions(service, folder_id)
    save_to_excel(files_and_revisions)


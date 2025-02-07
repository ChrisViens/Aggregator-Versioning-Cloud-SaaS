import os
import json
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# Configurazione Service Account
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
SERVICE_ACCOUNT_FILE = "service-account.json"  
OUTPUT_FILE = "output.xlsx"

def authenticate_with_service_account():
    """Autentica un Service Account per Google Drive Business"""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def list_team_drive_files(service, drive_id):
    """Recupera file da un Drive Condiviso"""
    results = service.files().list(
        corpora="drive",
        driveId=drive_id,
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="files(id, name, mimeType, owners(displayName), parents)"
    ).execute()
    return results.get("files", [])

def get_file_revisions(service, file_id):
    """Recupera le versioni di un file anche nei Drive Condivisi"""
    try:
        revisions = service.revisions().list(
            fileId=file_id,
            fields="revisions(id, modifiedTime, lastModifyingUser(displayName), size)",
            supportsAllDrives=True
        ).execute()

        return [
            {
                "Versione": float(i+1),
                "Ultima Modifica": rev.get('modifiedTime', 'N/A'),
                "Autore Modifica": rev.get('lastModifyingUser', {}).get('displayName', 'N/A'),
                "Dimensione (byte)": rev.get('size', 'N/A')
            }
            for i, rev in enumerate(revisions.get('revisions', []))
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
        
        current_folder_path = folder_path if folder_id != 'root' else "Il Mio Drive"
        
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
    """Salva i dati in un file Excel con colonne separate."""
    df = pd.DataFrame(data)
    df["Versione"] = df["Versione"].astype(str)
    df.to_excel(output_file, index=False, engine='openpyxl')
    print(f"File Excel salvato correttamente in: {output_file}")

if __name__ == '__main__':
    service = authenticate_with_service_account()
    drive_id = "YOUR_DRIVE_ID"  # Modificare il valore con l'ID del Drive
    folder_id = 'root'  
    files_and_revisions = get_files_and_revisions(service, folder_id)
    save_to_excel(files_and_revisions)

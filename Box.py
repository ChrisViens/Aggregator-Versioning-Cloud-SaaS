import os
import json
import pandas as pd
from boxsdk import OAuth2, Client

# Configurazione Box
CONFIG_FILE = "box_config.json"  # Inserire il percorso del file JSON con le credenziali
OUTPUT_FILE = "box_output.xlsx"

def authenticate_box():
    """Autentica l'utente su Box utilizzando OAuth2 con Refresh Token."""
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
    
    auth = OAuth2(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        access_token=config["access_token"],
        refresh_token=config["refresh_token"]
    )
    client = Client(auth)
    try:
        user = client.user().get()
        print(f"Autenticato come: {user.name}")
    except Exception as e:
        print(f"Errore autenticazione: {e}")
    return client

def get_file_revisions(client, file_id):
    """Recupera le versioni di un file su Box, se disponibili."""
    try:
        file = client.file(file_id)
        if hasattr(file, 'get_previous_versions'):
            versions = file.get_previous_versions()
            version_data = []
            
            for i, version in enumerate(versions, start=1):
                version_data.append({
                    "Versione": float(i),
                    "Ultima Modifica": version.modified_at,
                    "Autore Modifica": version.modified_by["name"] if version.modified_by else "N/A",
                    "Dimensione (byte)": version.size
                })
            
            return version_data
        return []
    except Exception as e:
        print(f"Errore nel recupero delle versioni per il file {file_id}: {e}")
        return []

def get_files_and_revisions(client, folder_id="0"):
    """Recupera i file e le loro versioni, esplorando tutte le sottocartelle."""
    files_info = []
    try:
        folder = client.folder(folder_id).get_items()
    except Exception as e:
        print(f"Errore nel recupero della cartella {folder_id}: {e}")
        return []
    
    for item in folder:
        if item.type == "folder":
            subfolder_files = get_files_and_revisions(client, item.id)
            files_info.extend(subfolder_files)
        else:
            revisions = get_file_revisions(client, item.id)
            for rev in revisions:
                files_info.append({
                    "Percorso": f"{item.path_collection['entries'][-1]['name']}/{item.name}" if item.path_collection["entries"] else item.name,
                    "Nome File": item.name,
                    "ID File": item.id,
                    "Proprietario": item.owned_by["name"] if item.owned_by else "N/A",
                    "Versione": rev["Versione"],
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

if __name__ == "__main__":
    client = authenticate_box()
    folder_id = "0"  # ID della cartella root o altra cartella specifica
    files_and_revisions = get_files_and_revisions(client, folder_id)
    save_to_excel(files_and_revisions)

import dropbox
import os
import csv
import json
from datetime import datetime
from dropbox.exceptions import AuthError

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../config.json')
# Carica configurazioni da config.json
with open(CONFIG_FILE, 'r') as file:
    config = json.load(file)

APP_KEY = config['dropbox'].get('APP_KEY', '')
APP_SECRET = config['dropbox'].get('APP_SECRET', '')
ACCESS_TOKEN = config['dropbox'].get('ACCESS_TOKEN', '')

if not APP_KEY or not APP_SECRET or not ACCESS_TOKEN:
    raise ValueError("APP_KEY, APP_SECRET o ACCESS_TOKEN non configurati correttamente.")

now = datetime.now()

def get_dropbox_client():
    try:
        dbx = dropbox.Dropbox(ACCESS_TOKEN)
        return dbx
    except AuthError as e:
        print(f"Errore di autenticazione: {e}")
        return None
    
#Funzione che restituisce il nome del profilo Dropbox
def get_dropbox_profile_name(access_token):
    try:
        dbx = dropbox.Dropbox(access_token)
        account_info = dbx.users_get_current_account()
        profile_name = account_info.name.display_name
        return profile_name
    except dropbox.exceptions.AuthError as e:
        print(f"Errore di autenticazione: {e}")
        return None
    except dropbox.exceptions.DropboxException as e:
        print(f"Errore generico di Dropbox API: {e}")
        return None



#Funzione per il download di tutte le versioni riferite ad un determinato file
def download_all_versions(dbx, entry_path, local_file_path):
    versions = dbx.files_list_revisions(entry_path).entries
    versions_folder = os.path.join(local_file_path, "_versions")
    if not os.path.exists(versions_folder):
        os.makedirs(versions_folder)

    for version in versions:
        revision_id = version.rev
        version_folder = os.path.join(versions_folder, f"v{revision_id}")

        if not os.path.exists(version_folder):
            os.makedirs(version_folder)

        file_name, file_extension = os.path.splitext(os.path.basename(local_file_path))

        new_local_version_file_path = os.path.join(version_folder, f"{file_name}_v{revision_id}{file_extension}")

        with open(new_local_version_file_path, 'wb') as local_version_file:
            metadata, response = dbx.files_download(entry_path, rev=revision_id)
            local_version_file.write(response.content)

#Funzione per il download delle cartelle da Dropbox
def download_folder(dbx, folder_path, local_path):
    entries = dbx.files_list_folder(folder_path).entries

    if not os.path.exists(local_path):
        os.makedirs(local_path)

    for entry in entries:
        entry_path = entry.path_display
        local_file_path = os.path.join(local_path, entry.name)

        if isinstance(entry, dropbox.files.FileMetadata):
            download_all_versions(dbx, entry_path, local_file_path)
        elif isinstance(entry, dropbox.files.FolderMetadata):
            download_folder(dbx, entry_path, local_file_path)


#Funzione per ottenere i metadati riferiti a tutti i files presenti in una determinata cartella di Dropbox
def get_all_files_metadata(dropbox_client, folder_path='', output_file='output.csv', username="User"):
    try:
        folder_path = folder_path.strip()

        # Usa la modalità 'w' per sovrascrivere il file ad ogni chiamata
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Percorso', 'Nome', 'Dimensione (byte)', 'Ultima modifica (UTC +0)', 'Versione', 'Autore']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()  # Scrive l'intestazione una sola volta

            result = dropbox_client.files_list_folder(folder_path, include_deleted=True)

            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    file_path = entry.path_display
                    revisions = dropbox_client.files_list_revisions(file_path)
                    for revision in revisions.entries:
                        writer.writerow({
                            'Percorso': file_path,
                            'Nome': entry.name,
                            'Dimensione (byte)': revision.size,
                            'Ultima modifica (UTC +0)': revision.client_modified,
                            'Versione': revision.rev,
                            'Autore': username
                        })
            
            # Sezione ricorsiva per ottenere i metadati delle sottocartelle
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FolderMetadata):
                    subfolder_path = entry.path_display
                    get_all_files_metadata(dropbox_client, subfolder_path, output_file, username)

    except dropbox.exceptions.DropboxException as e:
        print(f"Errore durante il recupero dei metadati della cartella: {e}")

def main():
    print(f"DEBUG: accesso")
    folder_path = ''
    account_name = get_dropbox_profile_name(ACCESS_TOKEN)
    
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../Estrattori/DBox")
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)  # Crea la directory se non esiste
    output_file = os.path.join(base_dir, now.strftime("DropBoxLogs_" + account_name + "_%d-%m-%Y_%H-%M.csv"))
    local = os.path.join(base_dir, now.strftime(account_name))

    dbx = get_dropbox_client()

    print(">   Analisi del seguente profilo Dropbox: " + account_name)
    
    print("->  Download dei file...")
    download_folder(dbx, folder_path, local)
    print("->  Estrazione Metadati in corso...")
    if dbx:
        get_all_files_metadata(dbx, folder_path, output_file, account_name)
    print("->  Metadati estratti con sucesso...")

if __name__ == "__main__":
    main()
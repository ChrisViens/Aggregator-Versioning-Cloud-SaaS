import dropbox
import os
import csv
import json
from datetime import datetime
from dropbox.exceptions import AuthError

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../config.json')
# Carica configurazioni da config.json
with open(CONFIG_FILE, 'r') as file:
    config = json.load(file)

APP_KEY = config['dropbox'].get('APP_KEY', '')
APP_SECRET = config['dropbox'].get('APP_SECRET', '')
ACCESS_TOKEN = config['dropbox'].get('ACCESS_TOKEN', '')
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dropbox_config.json")

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

def get_file_owner(dropbox_client, file_path):
    """Recupera il proprietario di un file su Dropbox."""
    try:
        metadata = dropbox_client.files_get_metadata(file_path)

        # Verifica se il file è di tipo condiviso e ha membri
        if hasattr(metadata, 'sharing_info') and metadata.sharing_info:
            return metadata.sharing_info.owner_team['name'] if 'owner_team' in metadata.sharing_info else "Proprietario sconosciuto"
        
        # Se il file non è condiviso, tenta di prendere il nome dell'utente autenticato
        account_info = dropbox_client.users_get_current_account()
        return account_info.name.display_name

    except dropbox.exceptions.DropboxException:
        return "Errore durante il recupero"

def get_last_modifier(dropbox_client, file_path):
    """Recupera il nome dell'ultimo utente che ha modificato un file su Dropbox"""
    try:
        # Tenta di recuperare l'autore dalla revisione più recente
        revisions = dropbox_client.files_list_revisions(file_path, limit=1)
        if revisions.entries:
            last_revision = revisions.entries[0]  # L'ultima revisione è la più recente

            # Se la revisione contiene un `last_editor`, recupera il nome dell'utente
            if hasattr(last_revision, 'last_editor') and last_revision.last_editor:
                user_id = last_revision.last_editor.account_id
                try:
                    user_info = dropbox_client.users_get_account(user_id)
                    return user_info.name.display_name  # Restituisce il nome dell'utente
                except dropbox.exceptions.DropboxException:
                    pass  

        # Se il file è condiviso, tenta di recuperare il modificatore dall'API di condivisione
        try:
            sharing_metadata = dropbox_client.sharing_get_file_metadata(file_path)
            if hasattr(sharing_metadata, 'owner_display_names') and sharing_metadata.owner_display_names:
                return sharing_metadata.owner_display_names[0]  # Restituisce il nome del proprietario/modificatore
        except dropbox.exceptions.DropboxException:
            pass 

        # Se non ha trovato l'ultimo modificatore, usa il proprietario del file
        file_owner = get_file_owner(dropbox_client, file_path)
        return file_owner if file_owner else "Sconosciuto"

    except dropbox.exceptions.ApiError as e:
        print(f"Errore API nel recupero dell'ultimo modificatore per {file_path}: {e}")
        return "Errore API"
    except dropbox.exceptions.DropboxException as e:
        print(f"Errore generale di Dropbox: {e}")
        return "Errore Dropbox"

#Funzione per ottenere i metadati riferiti a tutti i files presenti in una determinata cartella di Dropbox
def get_all_files_metadata(dropbox_client, folder_path='', output_file='output.csv', username="User"):
    try:
        folder_path = folder_path.strip()

        # Apri il file in modalità scrittura e specifica il delimitatore
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Percorso', 'Nome', 'Dimensione (byte)', 'Ultima modifica (UTC +0)', 'ID File', 'ID Versione', 'Autore Ultima Modifica', 'Proprietario']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')  
            writer.writeheader()

            result = dropbox_client.files_list_folder(folder_path, include_deleted=True)

            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    file_path = entry.path_display
                    file_owner = get_file_owner(dropbox_client, entry.id) 
                    last_modifier = get_last_modifier(dropbox_client, file_path)  
                    revisions = dropbox_client.files_list_revisions(file_path)
                    
                    for i, revision in enumerate(revisions.entries, start=1):
                        writer.writerow({
                            'Percorso': file_path,
                            'Nome': entry.name,
                            'Dimensione (byte)': revision.size,
                            'Ultima modifica (UTC +0)': revision.client_modified.strftime('%Y-%m-%d %H:%M:%S') + "Z",
                            'ID File': revision.rev,
                            'ID Versione': float(i), 
                            'Autore Ultima Modifica': last_modifier,
                            'Proprietario': file_owner,
                        })
            
            # Ricorsione per le sottocartelle
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FolderMetadata):
                    subfolder_path = entry.path_display
                    get_all_files_metadata(dropbox_client, subfolder_path, output_file, username)

    except dropbox.exceptions.DropboxException as e:
        print(f"Errore durante il recupero dei metadati della cartella: {e}")

def save_dropbox_user(dbx):
    """Salva l'utente autenticato di Dropbox in un file JSON."""
    try:
        account_info = dbx.users_get_current_account()
        user_data = {
            "name": account_info.name.display_name,
            "email": account_info.email
        }

        user_file = os.path.abspath("./Estrattori/DBox/dropbox_user.json")
        with open(user_file, "w") as file:
            json.dump(user_data, file)
        
        print(f"Utente Dropbox salvato: {user_data['name']} ({user_data['email']})")
    except Exception as e:
        print(f"Errore nel recupero dell'utente Dropbox: {e}")

def main():
    print(f"DEBUG: accesso")
    folder_path = ''
    account_name = get_dropbox_profile_name(ACCESS_TOKEN)
    
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../Estrattori/DBox")
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)  
    output_file = os.path.join(base_dir, now.strftime("DropBoxLogs_" + account_name + "_%d-%m-%Y_%H-%M.csv"))
    local = os.path.join(base_dir, now.strftime(account_name))

    dbx = get_dropbox_client()
    dbx = dropbox.Dropbox(ACCESS_TOKEN)
    save_dropbox_user(dbx)

    print(">   Analisi del seguente profilo Dropbox: " + account_name)
    
    print("->  Download dei file...")
    download_folder(dbx, folder_path, local)
    print("->  Estrazione Metadati in corso...")
    if dbx:
        get_all_files_metadata(dbx, folder_path, output_file, account_name)
    print("->  Metadati estratti con sucesso...")

if __name__ == "__main__":
    main()
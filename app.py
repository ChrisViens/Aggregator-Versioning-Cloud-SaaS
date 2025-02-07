import os
import json
import glob
from flask import Flask, request, jsonify, render_template, send_file
import subprocess
import sys
import threading
import socketio
from flask_socketio import SocketIO
from openpyxl import Workbook
import pandas as pd


app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
CHUNK_SIZE = 100  # Numero di elementi per blocco da inviare
EXCEL_REPORT_PATH = os.path.abspath("./Estrattori/report_completo.xlsx")

CONFIG_FILE = "config.json"
GOOGLE_DRIVE_TOKEN = os.path.abspath("./Estrattori/GDrive/google_drive_user.json")
ONEDRIVE_TOKEN = os.path.abspath("./Estrattori/OneDrive/onedrive_user.json")
DROPBOX_TOKEN = os.path.abspath("./Estrattori/DBox/dropbox_user.json")

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print("Client connesso")

def load_configurations():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as file:
                return json.load(file)
        except json.JSONDecodeError:
            # Ripristina il file se è malformato
            default_config = {"gdrive": {}, "dropbox": {}, "onedrive": {}}
            save_configurations(default_config)
            return default_config
    # Crea un file nuovo se non esiste
    default_config = {"gdrive": {}, "dropbox": {}, "onedrive": {}}
    save_configurations(default_config)
    return default_config

def save_configurations(configurations):
    with open(CONFIG_FILE, "w") as file:
        json.dump(configurations, file, indent=4)

configurations = load_configurations()

def run_extractor(script_path, args=None):
    try:
        python_path = sys.executable
        command = [python_path, script_path]
        if args:
            command.extend(args)

        result = subprocess.run(command, capture_output=True, text=True)
        print(f"DEBUG: Subprocess stderr: {result.stderr}")

        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        return {"success": True, "output": result.stdout}
    except Exception as e:
        print(f"DEBUG: Eccezione in subprocess: {str(e)}")
        return {"success": False, "error": str(e)}

def clean_json_data(data):
    """Rimuove NaN e uniforma i dati per il WebSocket."""
    for item in data:
        for key, value in item.items():
            if isinstance(value, float) and pd.isna(value):
                item[key] = 0  # Converte NaN in 0
            elif value is None:
                item[key] = "N/A"  # Evita valori null che potrebbero creare errori nel frontend
            elif isinstance(value, str) and value.lower() == "nan":
                item[key] = "N/A"
    return data

def send_large_payload(data):
    """Divide i dati in blocchi più piccoli e li invia via WebSocket."""
    data = clean_json_data(data)  # Pulizia dei dati prima dell'invio
    total_chunks = (len(data) // CHUNK_SIZE) + 1
    for i in range(0, len(data), CHUNK_SIZE):
        chunk = data[i:i + CHUNK_SIZE]
        payload = {"stage": 3, "data": chunk, "chunk": i // CHUNK_SIZE + 1, "total_chunks": total_chunks}
        try:
            print(f"DEBUG: Sending chunk {payload['chunk']} of {payload['total_chunks']}")
            socketio.emit('output', payload)  # Invia direttamente l'oggetto JSON
        except Exception as e:
            print(f"Errore nella serializzazione JSON: {e}")

def extract_and_combine_data():
    # Percorsi degli script di estrazione
    gdrive_script = os.path.abspath("./Estrattori/GDrive/Extractor.py")
    dropbox_script = os.path.abspath("./Estrattori/DBox/DBoxMetadataExtractor.py")
    onedrive_script = os.path.abspath("./Estrattori/OneDrive/main.py")
    python_path = sys.executable

    # Esegui ogni script in parallelo
    processes = {
        "DropBox": subprocess.Popen([python_path, dropbox_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
        "GoogleDrive": subprocess.Popen([python_path, gdrive_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
        "OneDrive": subprocess.Popen([python_path, onedrive_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
    }

    def read_output(process, service_name):
        """Legge e invia l'output dei processi in tempo reale."""
        try:
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                try:
                    json_data = json.loads(line)
                    socketio.emit('output', json_data)  # Invia aggiornamenti al frontend
                    print(f"DEBUG [{service_name}]: Dati ricevuti e inviati al client: {json_data}")
                except json.JSONDecodeError:
                    print(f"DEBUG [{service_name}]: Riga non JSON ignorata: {line}")
        except Exception as e:
            print(f"Errore nel processo {service_name}: {e}")
        finally:
            process.stdout.close()
            process.wait()
            print(f"Processo {service_name} terminato.")

    # Creazione e gestione dei thread per la lettura dell'output
    threads = []
    for name, process in processes.items():
        thread = threading.Thread(target=read_output, args=(process, name))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()
    
    for service, process in processes.items():
        process.wait()
        if process.returncode != 0:
            print(f"Errore nell'estrazione da {service}: {process.stderr.read()}")
        else:
            print(f"{service} completato con successo.")

    # Recupero dei file generati
    logs_dir = os.path.abspath("./Estrattori/DBox")
    csv_files = glob.glob(os.path.join(logs_dir, "*.csv"))
    latest_csv = max(csv_files, key=os.path.getmtime) if csv_files else None

    files = {
        "OneDrive": "./Estrattori/OneDrive/onedrive_versions.xlsx",
        "GoogleDrive": "./Estrattori/GDrive/output.xlsx",
        "Dropbox": latest_csv
    }

    # Lettura e combinazione dei dati
    combined_data = []
    for service, file_path in files.items():
        if file_path and os.path.exists(file_path):
            try:
                if file_path.endswith(".csv"):
                    df = pd.read_csv(file_path, delimiter=';', engine='python')  # Correzione delimitatore Dropbox
                else:
                    df = pd.read_excel(file_path, engine='openpyxl')

                # Uniforma le colonne tra le fonti
                if "Nome" in df.columns and service == "Dropbox":
                    df.rename(columns={"Nome": "Nome File"}, inplace=True)
                if "Versione" in df.columns and service in ["GoogleDrive"]:
                    df.rename(columns={"Versione": "ID Versione"}, inplace=True)
                if "Ultima modifica (UTC +0)" in df.columns and service == "Dropbox":
                    df.rename(columns={"Ultima modifica (UTC +0)": "Ultima Modifica"}, inplace=True)
                if "Autore Versione" in df.columns and service == "OneDrive":
                    df.rename(columns={"Autore Versione": "Proprietario"}, inplace=True)
                if "Autore" in df.columns and service == "Dropbox":
                    df.rename(columns={"Autore": "Proprietario"}, inplace=True)
                if "Autore Modifica" in df.columns and service == "GoogleDrive":
                    df.rename(columns={"Autore Modifica": "Autore Ultima Modifica"}, inplace=True)

                # Forza il formato della colonna "ID Versione" come stringa
                if "ID Versione" in df.columns:
                    df["ID Versione"] = df["ID Versione"].astype(str)

                df["Fonte"] = service
                combined_data.append(df)
            except Exception as e:
                print(f"Errore nella lettura del file {file_path}: {e}")

    if combined_data:
        final_df = pd.concat(combined_data, ignore_index=True)
        final_df = final_df.where(pd.notna(final_df), "N/A")  # Sostituisce NaN e None con "N/A"

    # Forza nuovamente il formato della colonna "ID Versione" come stringa nel DataFrame finale
        if "ID Versione" in final_df.columns:
            final_df["ID Versione"] = final_df["ID Versione"].astype(str)

    # Scrittura finale su Excel
        final_df.to_excel(EXCEL_REPORT_PATH, index=False, engine='openpyxl')

    # Conversione in dizionario e invio dati
        data_list = final_df.to_dict(orient='records')
        send_large_payload(data_list)
        print("Report Excel combinato e inviato in blocchi!")

@app.route('/extract/all', methods=['POST'])
def extract_all():
    socketio.start_background_task(extract_and_combine_data)
    return jsonify({"success": True, "message": "Estrazione in corso..."}), 200

@app.route('/download/<service>', methods=['GET'])
def download_report(service):
    """Permette di scaricare il report Excel per un servizio specifico o per tutti"""
    report_paths = {
        "tutti": EXCEL_REPORT_PATH,
        "onedrive": "./Estrattori/OneDrive/onedrive_versions.xlsx",
        "google drive": "./Estrattori/GDrive/output.xlsx",
    }
    if service.lower() == "dropbox":
        dropbox_logs_path = "./Estrattori/DBox/"
        dropbox_files = glob.glob(os.path.join(dropbox_logs_path, "DropBoxLogs_*.csv"))
        if dropbox_files:
            latest_dropbox_file = max(dropbox_files, key=os.path.getmtime)
            return send_file(latest_dropbox_file, as_attachment=True)
        else:
            return jsonify({"success": False, "error": "Nessun file DropBox trovato"}), 404
    
    file_path = report_paths.get(service.lower())
    
    if file_path and os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return jsonify({"success": False, "error": "File non trovato per il servizio richiesto"}), 404

@app.route('/upload/secret', methods=['POST'])
def upload_secret():
    try:
        # Recupera il file caricato
        secret_file = request.files['secret']
        secret_data = json.load(secret_file)

        # Aggiorna config.json con i dati di Google Drive
        with open('config.json', 'r+') as config_file:
            config = json.load(config_file)
            config['gdrive'] = secret_data
            config_file.seek(0)
            json.dump(config, config_file, indent=4)
            config_file.truncate()

        return jsonify({"success": True, "message": "Configurazione aggiornata con successo"}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/configure/<extractor>', methods=['POST'])
def configure_extractor(extractor):
    if extractor not in configurations:
        return jsonify({"message": "Estrattore non valido"}), 400

    data = request.json
    configurations[extractor] = data
    save_configurations(configurations)
    return jsonify({"message": f"Configurazione salvata per {extractor}"}), 200

@app.route('/get-configurations', methods=['GET'])
def get_configurations():
    try:
        with open('config.json', 'r') as file:
            configurations = json.load(file)
        return jsonify(configurations)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/extract/dropbox', methods=['POST'])
def extract_dropbox():
    print("DEBUG: Funzione extract_dropbox chiamata")

    script_path = os.path.abspath("./Estrattori/DBox/DBoxMetadataExtractor.py")
    logs_dir = os.path.abspath("./Estrattori/DBox")

    if not os.path.exists(script_path):
        print(f"DEBUG: Il file {script_path} non esiste.")
        return jsonify({"success": False, "error": "Script non trovato"}), 404

    # Esegui lo script per estrarre i metadati
    response = run_extractor(script_path)
    print(f"DEBUG: Risultato subprocess: {response}")

    if not response['success']:
        print(f"DEBUG: Errore subprocess: {response['error']}")
        return jsonify({"success": False, "error": response['error']}), 500

    # Trova l'ultimo file CSV nella directory dei log
    try:
        csv_files = glob.glob(os.path.join(logs_dir, "*.csv"))
        if not csv_files:
            return jsonify({"success": False, "error": "Nessun file CSV trovato"}), 404

        latest_csv = max(csv_files, key=os.path.getmtime)

        # Leggi il file CSV e convertilo in JSON
        structured_data = []
        with open(latest_csv, mode='r', encoding='utf-8') as csvfile:
            for line_number, line in enumerate(csvfile):
                if line_number == 0:
                    headers = line.strip().split(';')
                    continue
                values = line.strip().split(';')
                structured_data.append(dict(zip(headers, values)))

        return jsonify({"success": True, "data": structured_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/extract/gdrive', methods=['POST'])
def extract_gdrive():
    try:
        folder_id = request.json.get('folder_id', 'root')
        script_path = os.path.abspath('./Estrattori/GDrive/Extractor.py')
        python_path = sys.executable

        # Esegue il processo e cattura output ed errori
        process = subprocess.run(
            [python_path, script_path, folder_id],
            capture_output=True, text=True
        )

        if process.returncode != 0:
            print(f"Errore esecuzione script: {process.stderr.strip()}")
            return jsonify({"success": False, "error": process.stderr.strip()}), 500

        # Percorso del file Excel generato
        excel_path = './Estrattori/GDrive/output.xlsx'

        # Controlla se il file esiste
        if not os.path.exists(excel_path):
            print("ERRORE: File Excel non trovato!")
            return jsonify({"success": False, "error": "File Excel non trovato."}), 500

        # Leggi i dati da Excel
        try:
            df = pd.read_excel(excel_path, engine='openpyxl', dtype={"Versione": str})
            df["Versione"] = df["Versione"].astype(str)
            print("File Excel caricato con successo.")
        except Exception as e:
            print(f"ERRORE: Problema nella lettura del file Excel: {e}")
            return jsonify({"success": False, "error": f"Errore nella lettura del file Excel: {e}"}), 500

        # Gestisci i valori NaN:
        for column in df.columns:
            if df[column].dtype == 'float64':  # Per colonne numeriche
                df[column] = df[column].fillna(0)  # Sostituisci con 0
            else:  # Per colonne testuali o categoriche
                df[column] = df[column].fillna("")  # Sostituisci con stringa vuota

        # Converti i dati in formato JSON
        revisions = df.to_dict(orient='records')

        print(f"Estrazione completata, inviando {len(revisions)} record.")
        return jsonify({"success": True, "data": revisions}), 200
    except Exception as e:
        print(f"ERRORE GENERALE: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/extract/onedrive', methods=['POST'])
def extract_onedrive():
    script_path = os.path.abspath("./Estrattori/OneDrive/main.py")
    python_path = sys.executable
    output_file = os.path.abspath("./Estrattori/OneDrive/onedrive_versions.xlsx")

    def read_output():
        process = subprocess.Popen(
            [python_path, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            try:
                json_data = json.loads(line)
                socketio.emit('output', {'data': json_data})  # Invia aggiornamenti al frontend
                print(f"DEBUG: Dati ricevuti e inviati al client: {json_data}")

            # Se il processo ha completato l'autenticazione, avvia il fetch dei dati
                if json_data.get("stage") == 2:
                    with app.app_context(): 
                        fetch_onedrive_data()

            except json.JSONDecodeError:
                print(f"DEBUG: Riga non JSON ignorata: {line}")

        process.stdout.close()
        process.wait()

    # Controllo finale se il file è stato creato
        if os.path.exists(output_file):
            print("DEBUG: File Excel generato correttamente. Avvio del fetch automatico...")
            with app.app_context():  
                fetch_onedrive_data()
        else:
            print("ERROR: File Excel non trovato dopo il processo.")


    # Avvia il processo di autenticazione e generazione del file in background
    socketio.start_background_task(read_output)

    return jsonify({"success": True, "message": "Processo di autenticazione avviato"}), 200

@app.route('/fetch/onedrive-data', methods=['GET'])
def fetch_onedrive_data():
    output_file = os.path.abspath("./Estrattori/OneDrive/onedrive_versions.xlsx")

    # Controlla se il file Excel è stato generato
    if not os.path.exists(output_file):
        return jsonify({"success": False, "error": "File Excel non trovato. Esegui prima l'estrazione."}), 404

    try:
        df = pd.read_excel(output_file, engine='openpyxl', dtype={"ID Versione": str})
        df["ID Versione"] = df["ID Versione"].astype(str)
        df.fillna("", inplace=True)    
        data = df.to_dict(orient='records')

        print(f"DEBUG: Dati estratti e inviati al client: {len(data)} record trovati.")

        # Invia i dati al client tramite Socket.IO
        socketio.emit('output', {'stage': 2, 'data': data} )

        return jsonify({"success": True, "message": "Dati inviati al client", "data": data}), 200
    except Exception as e:
        print(f"ERROR: Errore nella lettura del file Excel: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def load_user(file_path, key_email, key_name=None):
    """Carica l'utente autenticato dai file token di ogni servizio."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as file:
                data = json.load(file)
                user_email = data.get(key_email, "Email sconosciuta")
                user_name = data.get(key_name, "") if key_name else ""
                
                return f"{user_name} ({user_email})" if user_name else user_email
        except Exception as e:
            print(f"Errore nel caricamento del file {file_path}: {e}")
    return "Utente sconosciuto"

@app.route('/get-user', methods=['GET'])
def get_user():
    users = {
    "Google Drive": load_user(GOOGLE_DRIVE_TOKEN, "email", "name"),
    "OneDrive": load_user(ONEDRIVE_TOKEN, "email", "name"),
    "Dropbox": load_user(DROPBOX_TOKEN, "email", "name")
    }
    """Restituisce l'utente autenticato per ogni servizio."""
    return jsonify({"success": True, "users": users})
    
if __name__ == '__main__':
    app.run(debug=True)
if __name__ == '__main__':
      socketio.run(app, debug=True, allow_unsafe_werkzeug=True)


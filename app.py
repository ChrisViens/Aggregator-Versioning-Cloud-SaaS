
import os
import json
import csv
import glob
from flask import Flask, request, jsonify, render_template
import subprocess
import sys
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    return render_template('index.html')

CONFIG_FILE = "config.json"

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
        print(f"DEBUG: Python Path: {python_path}")
        print(f"DEBUG: Script Path: {script_path}")

        command = [python_path, script_path]
        if args:
            command.extend(args)
        print(f"DEBUG: Command: {' '.join(command)}")

        result = subprocess.run(command, capture_output=True, text=True)
        print(f"DEBUG: Subprocess stdout: {result.stdout}")
        print(f"DEBUG: Subprocess stderr: {result.stderr}")

        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        return {"success": True, "output": result.stdout}
    except Exception as e:
        print(f"DEBUG: Eccezione in subprocess: {str(e)}")
        return {"success": False, "error": str(e)}

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

    script_path = os.path.abspath("./Estrattori/DBoxMetadataExtractor.py")
    logs_dir = os.path.abspath("./Estrattori/DBox")

    print(f"DEBUG: Percorso script: {script_path}")
    print(f"DEBUG: Percorso directory log: {logs_dir}")

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
        print(f"DEBUG: File CSV trovato: {latest_csv}")

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
        print(f"DEBUG: Errore durante la lettura del file CSV: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/extract/gdrive', methods=['POST'])
def extract_gdrive():
    try:
        folder_id = request.json.get('folder_id', 'root')
        script_path = os.path.abspath('./Estrattori/GDrive/Extractor.py')
        python_path = sys.executable

        process = subprocess.run(
            [python_path, script_path, folder_id],
            capture_output=True, text=True
        )

        if process.returncode != 0:
            return jsonify({"success": False, "error": process.stderr.strip()}), 500

        # Leggi il risultato dal file JSON generato
        with open('./Estrattori/GDrive/drive_revisions.json', 'r', encoding='utf-8') as f:
            revisions = json.load(f)

        return jsonify({"success": True, "data": revisions}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/extract/onedrive', methods=['POST'])
def extract_onedrive():
    script_path = os.path.abspath("./Estrattori/OneDrive/main.py")
    python_path = sys.executable

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
                # Invia solo JSON valido
                json_data = json.loads(line)
                socketio.emit('output', {'data': json_data})
            except json.JSONDecodeError:
                # Ignora le righe non JSON
                print(f"DEBUG: Riga non JSON ignorata: {line}")
        process.stdout.close()

    socketio.start_background_task(read_output)
    return jsonify({"success": True, "message": "Processo avviato"}), 200

@app.route('/configure/onedrive', methods=['POST'])
def configure_azure_onedrive():
    """Configura la sezione Azure per OneDrive e aggiorna config.json."""
    data = request.json

    # Verifica che il clientId sia fornito
    client_id = data.get('clientId')
    if not client_id:
        return jsonify({"success": False, "error": "Il clientId è obbligatorio."}), 400

    # Aggiorna la configurazione della sezione 'azure'
    configurations['azure'] = {
        "clientId": client_id,
        "tenantId": "consumers",  # Valore fisso
        "graphUserScopes": "User.Read Files.Read Files.ReadWrite"  # Valore fisso
    }

    save_configurations(configurations)

    return jsonify({"success": True, "message": "Configurazione aggiornata con successo."}), 200


if __name__ == '__main__':
    app.run(debug=True)
if __name__ == '__main__':
    socketio.run(app, debug=True)


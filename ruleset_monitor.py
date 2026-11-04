#!/usr/bin/env python3
import json
import os
import sys
import argparse
import getpass
import shutil
import subprocess
import time
from db_manager import DatabaseManager
from delphix_client import DelphixMaskingClient
from email_notifier import EmailNotifier

DEFAULT_CONFIG_PATH = "/etc/delphix-ruleset-monitor/config.json"
AGE_KEY_PATH = "/etc/delphix-ruleset-monitor/age.key"

# Campos de la configuración que se almacenan cifrados con age
SECRET_FIELDS = ("username", "password", "smtp_user", "smtp_password")
AGE_ARMOR_HEADER = "-----BEGIN AGE ENCRYPTED FILE-----"
# sudo suele reemplazar PATH por un secure_path sin /usr/local/bin, donde se instala age
AGE_SEARCH_PATH = os.pathsep.join([os.environ.get("PATH", ""), "/usr/local/bin"])

# Código de salida para ejecuciones parciales (algún Ruleset no pudo procesarse).
# El servicio systemd lo declara en SuccessExitStatus para no quedar en estado 'failed'.
EXIT_PARTIAL = 75

def run_age(args, input_text=None):
    """Ejecuta un binario de age y retorna su salida estándar."""
    binary = shutil.which(args[0], path=AGE_SEARCH_PATH)
    if binary is None:
        raise RuntimeError(f"No se encontró el binario '{args[0]}'. Instale age (ej. 'dnf install age' desde EPEL).")
    result = subprocess.run([binary] + args[1:], input=input_text, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"'{args[0]}' finalizó con error: {result.stderr.strip()}")
    return result.stdout

def ensure_age_identity():
    """Crea la identidad age si no existe y retorna su clave pública (recipient)."""
    if not os.path.exists(AGE_KEY_PATH):
        run_age(["age-keygen", "-o", AGE_KEY_PATH])
        print(f"[INFO] Identidad age generada en '{AGE_KEY_PATH}'. Respáldela por separado: sin ella no es posible descifrar la configuración.")
    os.chmod(AGE_KEY_PATH, 0o600)
    return run_age(["age-keygen", "-y", AGE_KEY_PATH]).strip()

def encrypt_secret(val, recipient):
    """Cifra un secreto con age en formato ASCII armor."""
    if not val:
        return ""
    return run_age(["age", "-e", "-a", "-r", recipient], input_text=val)

def decrypt_secret(val):
    """Descifra un secreto cifrado con age. Los valores vacíos se retornan sin cambios."""
    if not val:
        return val
    if not val.startswith(AGE_ARMOR_HEADER):
        raise RuntimeError("el valor no está cifrado con age. Ejecute 'sudo ruleset_monitor.py --configure' para cifrarlo.")
    return run_age(["age", "-d", "-i", AGE_KEY_PATH], input_text=val)

def print_boxed_table(title, headers, rows, col_widths, empty_message="No hay registros para mostrar."):
    """Renderiza una tabla con marcos ASCII/Unicode limpios si hay datos"""
    if not rows:
        print(f"\nℹ️  {empty_message}\n")
        return

    total_content_width = sum(col_widths) + 3 * (len(headers) - 1)
    line_top = "┌" + "─" * (total_content_width + 2) + "┐"
    line_header_top = "├" + "┬".join(["─" * (w + 2) for w in col_widths]) + "┤"
    line_mid = "├" + "┼".join(["─" * (w + 2) for w in col_widths]) + "┤"
    line_bot = "└" + "┴".join(["─" * (w + 2) for w in col_widths]) + "┘"

    print(f"\n{line_top}")
    print(f"│ {title:^{total_content_width}} │")
    print(line_header_top)

    formatted_headers = [f" {h:<{col_widths[i]}} " for i, h in enumerate(headers)]
    print("│" + "│".join(formatted_headers) + "│")
    print(line_mid)

    for row in rows:
        formatted_cells = []
        for i, cell in enumerate(row):
            val_str = str(cell) if cell is not None else ""
            if len(val_str) > col_widths[i]:
                val_str = val_str[:col_widths[i] - 3] + "..."
            formatted_cells.append(f" {val_str:<{col_widths[i]}} ")
        print("│" + "│".join(formatted_cells) + "│")

    print(line_bot + "\n")

def interactive_setup():
    """Asistente interactivo para configurar credenciales seguras"""
    config_path = DEFAULT_CONFIG_PATH

    print("=" * 140)
    print(f"{'ASISTENTE INTERACTIVO DE CONFIGURACIÓN SEGURA (DELPHIX DRIFT MONITOR)':^140}")
    print("=" * 140)

    existing_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
        except Exception:
            pass

    recipient = ensure_age_identity()

    # Los secretos existentes se descifran solo para ofrecerlos como valores por defecto
    existing_secrets = {}
    for field in SECRET_FIELDS:
        try:
            existing_secrets[field] = decrypt_secret(existing_config.get(field, ""))
        except RuntimeError:
            existing_secrets[field] = ""

    def prompt(msg, default=""):
        val = input(f"{msg} [{default}]: ").strip()
        return val if val else default

    def prompt_secret(msg, default=""):
        val = getpass.getpass(f"{msg} (Entrada oculta) [{ '********' if default else '' }]: ").strip()
        return val if val else default

    def prompt_bool(msg, default):
        val = prompt(f"{msg} (true/false)", "true" if default else "false")
        return val.lower() in ['true', '1', 'si', 'yes']

    delphix_host = prompt("Host de Delphix Engine (URL)", existing_config.get("delphix_host", "https://delphix.example.com"))
    username = prompt("Usuario de Delphix Engine", existing_secrets["username"])
    password = prompt_secret("Contraseña de Delphix Engine", existing_secrets["password"])

    print("\n--- Configuración de Notificaciones por Correo (SMTP) ---")
    email_enabled = prompt_bool("¿Habilitar notificaciones por correo?", existing_config.get("email_enabled", True))

    smtp_host = prompt("Servidor SMTP", existing_config.get("smtp_host", "smtp.example.com"))
    smtp_port = int(prompt("Puerto SMTP", str(existing_config.get("smtp_port", 587))))
    smtp_user = prompt("Usuario SMTP", existing_secrets["smtp_user"])
    smtp_password = prompt_secret("Contraseña SMTP", existing_secrets["smtp_password"])
    use_tls = prompt_bool("¿Utilizar TLS?", existing_config.get("use_tls", True))

    email_from = prompt("Remitente (From)", existing_config.get("email_from", "Delphix Ruleset Monitor <delphix-monitor@example.com>"))
    email_to_raw = prompt("Destinatarios separados por coma", ", ".join(existing_config.get("email_to", ["operations@example.com"])))
    email_to = [e.strip() for e in email_to_raw.split(",") if e.strip()]

    # Se parte de la configuración existente para conservar claves que el asistente no pregunta (ej. mock_mode)
    new_config = dict(existing_config)
    new_config.update({
        "delphix_host": delphix_host,
        "username": encrypt_secret(username, recipient),
        "password": encrypt_secret(password, recipient),
        "api_prefix": existing_config.get("api_prefix", "/masking/api"),
        "email_enabled": email_enabled,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": encrypt_secret(smtp_user, recipient),
        "smtp_password": encrypt_secret(smtp_password, recipient),
        "use_tls": use_tls,
        "email_from": email_from,
        "email_to": email_to
    })

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(new_config, f, indent=2)

    os.chmod(config_path, 0o600)
    print(f"\n✅ Configuración guardada en '{config_path}' con permisos chmod 600 y credenciales cifradas con age.")

def load_config():
    config_path = DEFAULT_CONFIG_PATH

    if not os.path.exists(config_path):
        print(f"[ERROR] No existe el archivo de configuración: {config_path}")
        print("        Ejecute 'sudo ruleset_monitor.py --configure' para crearlo.")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        raw_cfg = json.load(f)

    for field in SECRET_FIELDS:
        try:
            raw_cfg[field] = decrypt_secret(raw_cfg.get(field, ""))
        except RuntimeError as e:
            print(f"[ERROR] No se pudo descifrar '{field}' de {config_path}: {e}")
            sys.exit(1)

    return raw_cfg

def build_client(config):
    """Crea y autentica el cliente de la API de Delphix a partir de la configuración"""
    client = DelphixMaskingClient(
        host=config['delphix_host'], username=config['username'], password=config['password'],
        api_prefix=config.get('api_prefix', '/masking/api'), mock_mode=config.get('mock_mode', False)
    )
    client.login()
    return client

def refresh_probe(client, config, dummy_id):
    """
    Refresca la Sonda de Descubrimiento reintentando ante fallos o timeouts.
    Lanza RuntimeError si ningún intento finaliza correctamente.
    """
    retries = int(config.get('refresh_retries', 2))
    delay = int(config.get('refresh_retry_delay_seconds', 60))
    timeout = int(config.get('refresh_timeout_seconds', 300))
    attempts = retries + 1

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            async_task_id = client.refresh_ruleset(dummy_id)
            if client.poll_async_task(async_task_id, timeout=timeout):
                return
            last_error = "la tarea asíncrona de refresh finalizó con estado FAILED o CANCELLED"
        except Exception as e:
            last_error = str(e)

        if attempt < attempts:
            print(f"[WARN] Intento {attempt}/{attempts} de refresh de la Sonda (Ruleset {dummy_id}) fallido: {last_error}. Reintentando en {delay}s...")
            time.sleep(delay)

    raise RuntimeError(f"El refresh de la Sonda (Ruleset {dummy_id}) falló tras {attempts} intento(s): {last_error}")

def collect_ruleset_state(client, config, db, prod_id, dummy_id):
    """
    Sincroniza el inventario productivo, refresca la Sonda y consulta el catálogo del origen.
    Retorna (dummy_items, source_table_names). Falla si el refresh de la Sonda no termina bien,
    para no comparar contra datos desactualizados.
    """
    print(f" -> Sincronizando Inventario Productivo (Ruleset {prod_id})...")
    prod_items = client.get_ruleset_tables_and_columns(prod_id)
    db.sync_prod_inventory(prod_id, prod_items)

    print(f" -> Refrescando Sonda de Descubrimiento (Ruleset {dummy_id})...")
    refresh_probe(client, config, dummy_id)

    dummy_items = client.get_ruleset_tables_and_columns(dummy_id)
    connector_id = client.get_ruleset_connector_id(dummy_id)
    source_table_names = client.get_connector_table_names(connector_id)
    print(f" -> Catálogo del origen consultado mediante conector {connector_id}: {len(source_table_names)} tabla(s).")
    return dummy_items, source_table_names

def print_failures_table(failures):
    rows = [[f["ruleset_name"], f["prod_ruleset_id"], f["dummy_ruleset_id"], f["error"]] for f in failures]
    print_boxed_table(
        title=f"❌ RULESETS NO PROCESADOS ({len(failures)})",
        headers=["RULESET", "ID PROD", "ID SONDA", "MOTIVO"],
        rows=rows,
        col_widths=[30, 10, 10, 70]
    )

def run_audit_cycle(config, db, client):
    """Audita los Rulesets activos. Retorna la lista de Rulesets que no pudieron auditarse."""
    print("=" * 140)
    print(f"{'AUDITORÍA DE RULESETS Y DETECCIÓN DE CAMBIOS EN ORIGEN (DELPHIX)':^140}")
    print("=" * 140)

    # Obtener Rulesets activos en la configuración de la BD
    active_rulesets = db.get_active_rulesets()
    if not active_rulesets:
        print("\nℹ️  No hay Rulesets activos marcados con evaluación (is_active = YES) para auditar.\n")
        return []

    print(f"\n[INFO] Procesando {len(active_rulesets)} Ruleset(s) activo(s)...")

    all_new_structures = []
    all_deleted_structures = []
    all_data_type_drifts = []
    failures = []
    notifier = EmailNotifier(config)

    for idx, rs in enumerate(active_rulesets, 1):
        prod_id = rs['prod_ruleset_id']
        dummy_id = rs['dummy_ruleset_id']
        prod_name = rs['ruleset_alias']

        print(f"\n--- Ruleset [{idx}/{len(active_rulesets)}]: Productivo ID {prod_id} ('{prod_name}') <-> Sonda ID {dummy_id} ---")

        # Un fallo en un Ruleset no debe impedir auditar el resto
        try:
            # Pasos 1 y 2: Sincronización del Inventario Productivo y Refresco de la Sonda
            dummy_items, source_table_names = collect_ruleset_state(client, config, db, prod_id, dummy_id)

            # Paso 3: Análisis de Deltas
            analysis = db.analyze_drift(prod_id, dummy_items, source_table_names)
        except Exception as e:
            print(f"[ERROR] No se pudo auditar el Ruleset '{prod_name}' (Prod ID {prod_id} <-> Sonda ID {dummy_id}): {e}")
            failures.append({
                'ruleset_name': prod_name,
                'prod_ruleset_id': prod_id,
                'dummy_ruleset_id': dummy_id,
                'error': str(e)
            })
            continue

        new_structs = analysis['new_structures']
        deleted_structs = analysis['deleted_structures']
        drifts = analysis['data_type_drifts']

        for item in new_structs:
            item['ruleset_name'] = prod_name
            all_new_structures.append(item)

        for item in deleted_structs:
            item['ruleset_name'] = prod_name
            all_deleted_structures.append(item)

        for item in drifts:
            item['ruleset_name'] = prod_name
            all_data_type_drifts.append(item)

        # Enviar correo individual por cada Ruleset si existen deltas
        if new_structs or deleted_structs or drifts:
            notifier.send_audit_alert(prod_name, prod_id, dummy_id, new_structs, deleted_structs, drifts)

    # Renderizar tablas consolidadas en consola
    new_rows = [[
        s['ruleset_name'],
        s['table_name'],
        'Tabla completa' if s['column_name'] == '*' else s['column_name'],
        s['data_type']
    ] for s in all_new_structures]
    print_boxed_table(
        title=f"⚠️ ALERTA: ESTRUCTURAS NUEVAS DETECTADAS EN ORIGEN ({len(all_new_structures)} estructuras)",
        headers=["RULESET", "TABLA ORIGEN", "COLUMNA / ESTRUCTURA", "TIPO DE DATO"],
        rows=new_rows,
        col_widths=[30, 28, 28, 20],
        empty_message="Consulta A: No se detectaron estructuras nuevas en el origen sin registrar."
    )

    del_rows = [[s['ruleset_name'], s['table_name'], s['column_name'], s['algorithm_name']] for s in all_deleted_structures]
    print_boxed_table(
        title=f"🚫 ALERTA: ESTRUCTURAS ELIMINADAS EN ORIGEN ({len(all_deleted_structures)} columnas)",
        headers=["RULESET", "TABLA PRODUCTIVA", "COLUMNA CONFIGURADA", "ALGORITMO AFECTADO"],
        rows=del_rows,
        col_widths=[30, 28, 28, 24],
        empty_message="Consulta B: Todas las estructuras del Ruleset Productivo siguen existiendo en el Origen."
    )

    drift_rows = [[s['ruleset_name'], s['table_name'], s['column_name'], s['old_data_type'], s['new_data_type']] for s in all_data_type_drifts]
    print_boxed_table(
        title=f"⚡ ALERTA: CAMBIOS EN TIPO DE DATO DETECTADOS EN ORIGEN ({len(all_data_type_drifts)} columnas)",
        headers=["RULESET", "TABLA", "COLUMNA", "TIPO EN RULESET", "TIPO EN ORIGEN"],
        rows=drift_rows,
        col_widths=[28, 22, 22, 18, 18],
        empty_message="Consulta C: No se detectaron cambios en los tipos de datos de las columnas existentes."
    )

    if failures:
        print_failures_table(failures)
        notifier.send_failure_alert(failures)

    return failures

def list_orphan_exclusions(config, db):
    """Muestra exclusiones cuya tabla ya no aparece en el catálogo del origen."""
    client = build_client(config)

    orphan_rows = []
    for ruleset in db.list_all_rulesets():
        exclusions = db.list_exclusions(ruleset_filter=ruleset['prod_ruleset_id'])
        if not exclusions:
            continue

        try:
            connector_id = client.get_ruleset_connector_id(ruleset['dummy_ruleset_id'])
            source_tables = {
                str(table_name).strip().upper()
                for table_name in client.get_connector_table_names(connector_id)
            }
        except Exception as e:
            print(
                f"[WARN] No se pudo consultar el catálogo del origen para la dupla "
                f"{ruleset['prod_ruleset_id']} <-> {ruleset['dummy_ruleset_id']}: {e}"
            )
            continue

        for exclusion in exclusions:
            if exclusion['table_name'].strip().upper() not in source_tables:
                orphan_rows.append([
                    f"{ruleset['ruleset_alias']} (ID: {ruleset['prod_ruleset_id']})",
                    ruleset['dummy_ruleset_id'],
                    exclusion['table_name'],
                    exclusion['column_name'],
                    exclusion['created_at'],
                    "NO EXISTE EN ORIGEN"
                ])

    print_boxed_table(
        title="EXCLUSIONES HUÉRFANAS (TABLA AUSENTE EN EL ORIGEN)",
        headers=["RULESET", "ID SONDA", "TABLA", "COLUMNA", "FECHA", "ESTADO"],
        rows=orphan_rows,
        col_widths=[30, 12, 24, 24, 22, 22],
        empty_message="No se encontraron exclusiones huérfanas."
    )

def main():
    examples = """Ejemplos de uso del CLI:
  1. Ejecutar ciclo de auditoría estándar:
     sudo ruleset_monitor.py --audit

  2. Reconstruir e inferir Línea Base (pisar delta entre Sonda y Prod):
     sudo ruleset_monitor.py --init-baseline
     sudo ruleset_monitor.py --init-baseline --ruleset-id 6 7

  3. Registrar/Alta de un nuevo par de Rulesets:
     sudo ruleset_monitor.py --add-ruleset 4 5

  4. Eliminar/Baja limpia de un par de Rulesets:
     sudo ruleset_monitor.py --remove-ruleset 4 5

  5. Listar Rulesets registrados en la herramienta (is_active YES/NO):
     sudo ruleset_monitor.py --list-config

  6. Consulta dinámica a Delphix Engine API para listar todos los Rulesets:
     sudo ruleset_monitor.py --list-engine-rulesets

  7. Listar inventario productivo:
     sudo ruleset_monitor.py --list-prod
     sudo ruleset_monitor.py --list-prod --ruleset-id 4 5

  8. Listar exclusiones registradas en la línea base:
     sudo ruleset_monitor.py --list-exclusions
     sudo ruleset_monitor.py --list-exclusions --ruleset-id 6 7
     sudo ruleset_monitor.py --list-exclusions --filter-table CLIENTES

  9. Listar exclusiones huérfanas cuyo objeto ya no existe en el origen:
     sudo ruleset_monitor.py --list-orphan-exclusions

  10. Cambiar estado de evaluación de un Ruleset (YES / NO):
     sudo ruleset_monitor.py --set-active 6 7 NO
     sudo ruleset_monitor.py --set-active 6 7 YES

  11. Purgar la base de datos de la herramienta en cero:
     sudo ruleset_monitor.py --purge
     sudo ruleset_monitor.py --purge -y
"""
    parser = argparse.ArgumentParser(
        description="Delphix Continuous Compliance - Monitor de Deriva de Esquemas (Ruleset Drift Monitor)",
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--audit", action="store_true", help="Ejecuta la auditoría sobre los Rulesets activos")
    parser.add_argument("--configure", action="store_true", help="Asistente interactivo para generar credenciales en /etc/delphix-ruleset-monitor/config.json")
    parser.add_argument("--init-baseline", action="store_true", help="Inferencia Día Cero: Reconstruye e inserta la línea base pisando el delta anterior")
    parser.add_argument("--ruleset-id", nargs=2, type=int, metavar=('PROD_ID', 'SONDA_ID'), help="ID opcional de la dupla de Rulesets (Productivo y Sonda) al ejecutar línea base o listar (ej. --ruleset-id 6 7)")
    parser.add_argument("--add-ruleset", nargs=2, type=int, metavar=('PROD_ID', 'SONDA_ID'), help="Registra un nuevo par de Rulesets por sus IDs (ej. --add-ruleset 4 5)")
    parser.add_argument("--remove-ruleset", nargs=2, type=int, metavar=('PROD_ID', 'SONDA_ID'), help="Elimina un par de Rulesets por sus IDs y limpia su inventario y exclusiones de SQLite (ej. --remove-ruleset 4 5)")
    parser.add_argument("--list-config", action="store_true", help="Muestra los Rulesets registrados en la herramienta y su estado activo (YES/NO)")
    parser.add_argument("--list-engine-rulesets", action="store_true", help="Consulta dinámica a la API de Delphix Engine para listar la totalidad de los Rulesets existentes")
    parser.add_argument("--list-prod", action="store_true", help="Muestra el inventario productivo de tablas, columnas y algoritmos")
    parser.add_argument("--list-exclusions", action="store_true", help="Muestra las exclusiones del delta de línea base")
    parser.add_argument("--list-orphan-exclusions", action="store_true", help="Muestra exclusiones cuya tabla ya no existe en el origen")
    parser.add_argument("--filter-table", metavar='TABLA', help="Filtra el listado de exclusiones por el nombre de la tabla")
    parser.add_argument("--set-active", nargs=3, metavar=('PROD_ID', 'SONDA_ID', 'ESTADO'), help="Establece la marca de evaluación de una dupla de Rulesets (ej. --set-active 6 7 NO)")
    parser.add_argument("--purge", action="store_true", help="Purga la totalidad de la base de datos SQLite (ruleset_config, prod_inventory, exclusions) dejando la herramienta en cero")
    parser.add_argument("--yes", "-y", action="store_true", help="Confirma automáticamente operaciones destructivas (ej. --purge -y)")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.configure:
        interactive_setup()
        return

    config = load_config()
    db = DatabaseManager()

    if args.add_ruleset:
        p_id, d_id = args.add_ruleset
        if p_id == d_id:
            print(f"⚠️ Error de validación: El Ruleset Productivo (ID {p_id}) y la Sonda (ID {d_id}) deben ser dos Rulesets distintos.")
            return

        try:
            client = build_client(config)

            p_alias = client.get_ruleset_name(p_id)
            d_alias = client.get_ruleset_name(d_id)
            
            print(f"[INFO] Ruleset Productivo detectado (ID {p_id}): '{p_alias}'")
            print(f"[INFO] Ruleset Sonda detectado (ID {d_id}): '{d_alias}'")

            db.add_ruleset(p_id, d_id, p_alias)
            print(f"✅ Dupla validada y registrada exitosamente: Productivo '{p_alias}' (ID {p_id}) <-> Sonda '{d_alias}' (ID {d_id}).")
        except Exception as e:
            print(f"[ERROR] Error al registrar y validar el par de Rulesets: {e}")
        return

    if args.remove_ruleset:
        p_id, d_id = args.remove_ruleset
        try:
            success, msg = db.remove_ruleset(p_id, d_id)
            if success:
                print(f"✅ {msg}")
            else:
                print(f"⚠️ {msg}")
        except Exception as e:
            print(f"[ERROR] Error al dar de baja el par de Rulesets: {e}")
        return

    if args.purge:
        if not args.yes:
            confirm = input("⚠️ ¿Está seguro de purgar la totalidad de la base de datos de la herramienta? (Se eliminarán todos los Rulesets registrados, inventarios y exclusiones) [s/N]: ").strip().lower()
            if confirm not in ['s', 'si', 'y', 'yes']:
                print("Operación de purga cancelada.")
                return
        db.purge_database()
        print("✅ Base de datos SQLite purgada exitosamente. Todas las tablas de la herramienta se encuentran en cero.")
        return

    if args.list_engine_rulesets:
        client = build_client(config)
        engine_rulesets = client.get_all_engine_rulesets()
        rows = [[r['ruleset_id'], r['ruleset_name'], r['type']] for r in engine_rulesets]
        print_boxed_table(
            title="RULESETS REGISTRADOS EN DELPHIX ENGINE (CONSULTA DINÁMICA VÍA API)",
            headers=["RULESET ID (ENGINE)", "NOMBRE OFICIAL EN DELPHIX", "TIPO / CONTENEDOR"],
            rows=rows,
            col_widths=[24, 38, 24],
            empty_message="No se encontraron Rulesets en Delphix Engine."
        )
        return

    if args.set_active:
        try:
            p_id = int(args.set_active[0])
            d_id = int(args.set_active[1])
            estado_raw = args.set_active[2].strip().upper()
            if estado_raw not in ['YES', 'NO', 'SI', 'S', 'N', '1', '0']:
                print("⚠️ Estado no válido. Utilice YES o NO (ej. --set-active 6 7 NO).")
                return
            is_active = estado_raw in ['YES', 'SI', 'S', '1']
            success, msg = db.set_ruleset_active(p_id, d_id, is_active)
            if success:
                print(f"✅ {msg}")
            else:
                print(f"⚠️ {msg}")
        except ValueError:
            print("⚠️ Error de sintaxis: PROD_ID y SONDA_ID deben ser números enteros. Ejemplo: --set-active 6 7 NO")
        except Exception as e:
            print(f"[ERROR] Error al actualizar estado activo de la dupla: {e}")
        return

    if args.list_config:
        rulesets = db.list_all_rulesets()
        rows = [[r['prod_ruleset_id'], r['dummy_ruleset_id'], r['ruleset_alias'], 'YES' if r['is_active'] else 'NO'] for r in rulesets]
        print_boxed_table(
            title="CONFIGURACIÓN Y GOBIERNO DE RULESETS REGISTRADOS",
            headers=["RULESET ID PROD", "RULESET ID SONDA", "ALIAS / NOMBRE DE RULESET", "AUDITORÍA ACTIVA"],
            rows=rows,
            col_widths=[20, 20, 32, 20],
            empty_message="No hay Rulesets registrados en la base de datos."
        )
        return

    if args.list_prod:
        target_prod_id = args.ruleset_id[0] if args.ruleset_id else None
        prod_items = db.list_prod_inventory(ruleset_filter=target_prod_id)
        rows = [[f"{p['ruleset_alias']} (ID: {p['prod_ruleset_id']})", p['table_name'], p['column_name'], p['algorithm_name'] or 'Sin Algoritmo', p['data_type'] or 'VARCHAR'] for p in prod_items]
        filter_str = f" (Ruleset Prod ID: {target_prod_id})" if target_prod_id else ""
        print_boxed_table(
            title=f"INVENTARIO DEL RULESET PRODUCTIVO EN DELPHIX{filter_str}",
            headers=["RULESET", "TABLA", "COLUMNA", "ALGORITMO CONFIGURADO", "TIPO DE DATO"],
            rows=rows,
            col_widths=[28, 28, 28, 24, 20],
            empty_message=f"No hay registros de inventario productivo para mostrar{filter_str}."
        )
        return

    if args.list_exclusions:
        target_prod_id = args.ruleset_id[0] if args.ruleset_id else None
        exclusions = db.list_exclusions(ruleset_filter=target_prod_id, table_filter=args.filter_table)
        rows = [[f"{e['ruleset_alias']} (ID: {e['prod_ruleset_id']})", e['table_name'], e['column_name'], e['created_at']] for e in exclusions]
        filter_str = f" ({args.filter_table})" if args.filter_table else ""
        print_boxed_table(
            title=f"CATÁLOGO DE EXCLUSIONES Y DELTA DE LÍNEA BASE{filter_str}",
            headers=["RULESET", "TABLA EXCLUIDA", "COLUMNA EXCLUIDA", "FECHA DE REGISTRO"],
            rows=rows,
            col_widths=[30, 30, 30, 24],
            empty_message=f"No hay exclusiones registradas para mostrar{filter_str}."
        )
        return

    if args.list_orphan_exclusions:
        try:
            list_orphan_exclusions(config, db)
        except Exception as e:
            print(f"[ERROR] No se pudieron consultar las exclusiones huérfanas: {e}")
        return

    # Para comandos que requieren API de Delphix (init-baseline y audit)
    client = build_client(config)

    if args.init_baseline:
        r_msg = f" para la dupla (Prod ID {args.ruleset_id[0]} <-> Sonda ID {args.ruleset_id[1]})" if args.ruleset_id else " para todos los Rulesets activos"
        print(f"\n[LÍNEA BASE] Reconstruyendo inventario e infiriendo deltas{r_msg}...")

        rulesets = db.get_active_rulesets(ruleset_filter=args.ruleset_id)
        if not rulesets:
            print("⚠️ No se encontraron Rulesets activos para procesar la línea base.")
            return

        total_exclusions = 0
        failures = []
        for rs in rulesets:
            p_id = rs['prod_ruleset_id']
            d_id = rs['dummy_ruleset_id']
            alias = rs['ruleset_alias']

            print(f" -> Procesando línea base para Ruleset '{alias}' (Prod ID: {p_id} <-> Sonda ID: {d_id})...")

            try:
                # 1 y 2. Sincronizar Inventario Productivo y Refrescar Sonda de Descubrimiento
                dummy_items, source_table_names = collect_ruleset_state(client, config, db, p_id, d_id)
            except Exception as e:
                # La línea base anterior de este Ruleset se conserva intacta
                print(f"[ERROR] No se pudo reconstruir la línea base del Ruleset '{alias}': {e}")
                failures.append({
                    'ruleset_name': alias,
                    'prod_ruleset_id': p_id,
                    'dummy_ruleset_id': d_id,
                    'error': str(e)
                })
                continue

            # 3. Pisar y recalcular delta en exclusions
            c = db.reset_baseline_exclusions(p_id, dummy_items, source_table_names)
            total_exclusions += c

        processed = len(rulesets) - len(failures)
        print(f"✅ Línea Base nivelada para {processed}/{len(rulesets)} Ruleset(s). Se registraron {total_exclusions} elementos en el delta de exclusiones.")
        if failures:
            print_failures_table(failures)
            print("⚠️ Los Rulesets no procesados conservan su línea base anterior.")
            sys.exit(EXIT_PARTIAL)
        return

    if args.audit:
        failures = run_audit_cycle(config, db, client)
        if failures:
            sys.exit(EXIT_PARTIAL)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

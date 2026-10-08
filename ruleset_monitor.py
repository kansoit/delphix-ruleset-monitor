#!/usr/bin/env python3
import json
import os
import sys
import argparse
import base64
import getpass
from db_manager import DatabaseManager
from delphix_client import DelphixMaskingClient
from email_notifier import EmailNotifier

DEFAULT_CONFIG_PATH = "/etc/delphix-ruleset-monitor/config.json"

def decode_secret(val):
    """Desofusca un secreto Base64 con prefijo 'b64:'"""
    if not val or not isinstance(val, str):
        return val
    if val.startswith("b64:"):
        encoded_part = val[4:]
        try:
            return base64.b64decode(encoded_part.encode('utf-8')).decode('utf-8')
        except Exception as e:
            print(f"[WARN] Error al decodificar Base64 de '{val}': {e}")
            return val
    return val

def encode_secret(val):
    """Ofusca un texto plano en Base64 con prefijo 'b64:'"""
    if not val:
        return ""
    if val.startswith("b64:"):
        return val
    b64_str = base64.b64encode(val.encode('utf-8')).decode('utf-8')
    return f"b64:{b64_str}"

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

def interactive_setup(config_path=None):
    """Asistente interactivo para configurar credenciales seguras"""
    if config_path is None:
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

    def prompt(msg, default=""):
        val = input(f"{msg} [{default}]: ").strip()
        return val if val else default

    def prompt_secret(msg, default=""):
        val = getpass.getpass(f"{msg} (Entrada oculta) [{ '********' if default else '' }]: ").strip()
        return val if val else decode_secret(default)

    delphix_host = prompt("Host de Delphix Engine (URL)", existing_config.get("delphix_host", "https://delphix.example.com"))
    username = prompt("Usuario de Delphix Engine", decode_secret(existing_config.get("username", "")))
    password = prompt_secret("Contraseña de Delphix Engine", existing_config.get("password", ""))

    print("\n--- Configuración de Notificaciones por Correo (SMTP) ---")
    email_enabled_str = prompt("¿Habilitar notificaciones por correo? (true/false)", "true" if existing_config.get("email_enabled", True) else "false")
    email_enabled = email_enabled_str.lower() in ['true', '1', 'si', 'yes']

    smtp_host = prompt("Servidor SMTP", existing_config.get("smtp_host", "smtp.example.com"))
    smtp_port = int(prompt("Puerto SMTP", str(existing_config.get("smtp_port", 587))))
    smtp_user = prompt("Usuario SMTP", decode_secret(existing_config.get("smtp_user", "")))
    smtp_password = prompt_secret("Contraseña SMTP", existing_config.get("smtp_password", ""))
    use_tls_str = prompt("¿Utilizar TLS? (true/false)", "true" if existing_config.get("use_tls", True) else "false")
    use_tls = use_tls_str.lower() in ['true', '1', 'si', 'yes']

    email_from = prompt("Remitente (From)", existing_config.get("email_from", "Delphix Ruleset Monitor <delphix-monitor@example.com>"))
    email_to_raw = prompt("Destinatarios separados por coma", ", ".join(existing_config.get("email_to", ["operations@example.com"])))
    email_to = [e.strip() for e in email_to_raw.split(",") if e.strip()]

    new_config = {
        "delphix_host": delphix_host,
        "username": encode_secret(username),
        "password": encode_secret(password),
        "api_prefix": existing_config.get("api_prefix", "/masking/api"),
        "email_enabled": email_enabled,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": encode_secret(smtp_user),
        "smtp_password": encode_secret(smtp_password),
        "use_tls": use_tls,
        "email_from": email_from,
        "email_to": email_to
    }

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(new_config, f, indent=2)

    os.chmod(config_path, 0o600)
    print(f"\n✅ Configuración guardada en '{config_path}' con permisos chmod 600.")

def load_config(config_path=None):
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    if not os.path.exists(config_path):
        print(f"[ERROR] No existe el archivo de configuración: {config_path}")
        print("        Ejecute 'sudo ruleset_monitor.py --configure' para crearlo.")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        raw_cfg = json.load(f)

    for k, v in raw_cfg.items():
        if isinstance(v, str):
            raw_cfg[k] = decode_secret(v)

    return raw_cfg

def run_audit_cycle(config, db, client):
    print("=" * 140)
    print(f"{'AUDITORÍA DE RULESETS Y DETECCIÓN DE CAMBIOS EN ORIGEN (DELPHIX)':^140}")
    print("=" * 140)

    # Obtener Rulesets activos en la configuración de la BD
    active_rulesets = db.get_active_rulesets()
    if not active_rulesets:
        print("\nℹ️  No hay Rulesets activos marcados con evaluación (is_active = YES) para auditar.\n")
        return

    print(f"\n[INFO] Procesando {len(active_rulesets)} Ruleset(s) activo(s)...")

    all_new_structures = []
    all_deleted_structures = []
    all_data_type_drifts = []

    for idx, rs in enumerate(active_rulesets, 1):
        prod_id = rs['prod_ruleset_id']
        dummy_id = rs['dummy_ruleset_id']
        prod_name = rs['ruleset_alias']

        print(f"\n--- Ruleset [{idx}/{len(active_rulesets)}]: Productivo ID {prod_id} ('{prod_name}') <-> Sonda ID {dummy_id} ---")

        # Paso 1: Sincronización del Inventario Productivo
        print(f" -> Sincronizando Inventario Productivo (Ruleset {prod_id})...")
        prod_items = client.get_ruleset_tables_and_columns(prod_id)
        db.sync_prod_inventory(prod_id, prod_items)

        # Paso 2: Refresco de la Sonda de Descubrimiento
        print(f" -> Refrescando Sonda de Descubrimiento (Ruleset {dummy_id})...")
        async_task_id = client.refresh_ruleset(dummy_id)
        client.poll_async_task(async_task_id)

        dummy_items = client.get_ruleset_tables_and_columns(dummy_id)
        connector_id = client.get_ruleset_connector_id(dummy_id)
        source_table_names = client.get_connector_table_names(connector_id)
        print(f" -> Catálogo del origen consultado mediante conector {connector_id}: {len(source_table_names)} tabla(s).")

        # Paso 3: Análisis de Deltas
        analysis = db.analyze_drift(prod_id, dummy_items, source_table_names)
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
            notifier = EmailNotifier(config)
            notifier.send_audit_alert(prod_name, prod_id, dummy_id, new_structs, deleted_structs, drifts)

    # Renderizar tablas consolidadas en consola
    new_rows = [[
        s.get('ruleset_name', 'Default'),
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

    del_rows = [[s.get('ruleset_name', 'Default'), s['table_name'], s['column_name'], s['algorithm_name']] for s in all_deleted_structures]
    print_boxed_table(
        title=f"🚫 ALERTA: ESTRUCTURAS ELIMINADAS EN ORIGEN ({len(all_deleted_structures)} columnas)",
        headers=["RULESET", "TABLA PRODUCTIVA", "COLUMNA CONFIGURADA", "ALGORITMO AFECTADO"],
        rows=del_rows,
        col_widths=[30, 28, 28, 24],
        empty_message="Consulta B: Todas las estructuras del Ruleset Productivo siguen existiendo en el Origen."
    )

    drift_rows = [[s.get('ruleset_name', 'Default'), s['table_name'], s['column_name'], s['old_data_type'], s['new_data_type']] for s in all_data_type_drifts]
    print_boxed_table(
        title=f"⚡ ALERTA: CAMBIOS EN TIPO DE DATO DETECTADOS EN ORIGEN ({len(all_data_type_drifts)} columnas)",
        headers=["RULESET", "TABLA", "COLUMNA", "TIPO EN RULESET", "TIPO EN ORIGEN"],
        rows=drift_rows,
        col_widths=[28, 22, 22, 18, 18],
        empty_message="Consulta C: No se detectaron cambios en los tipos de datos de las columnas existentes."
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

  9. Cambiar estado de evaluación de un Ruleset (YES / NO):
     sudo ruleset_monitor.py --set-active 6 7 NO
     sudo ruleset_monitor.py --set-active 6 7 YES

  10. Purgar la base de datos de la herramienta en cero:
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
            client = DelphixMaskingClient(
                host=config['delphix_host'], username=config['username'], password=config['password'],
                api_prefix=config.get('api_prefix', '/masking/api'), mock_mode=config.get('mock_mode', False)
            )
            client.login()
            
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
        client = DelphixMaskingClient(
            host=config['delphix_host'], username=config['username'], password=config['password'],
            api_prefix=config.get('api_prefix', '/masking/api'), mock_mode=config.get('mock_mode', False)
        )
        client.login()
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

    # Para comandos que requieren API de Delphix (init-baseline y audit)
    client = DelphixMaskingClient(
        host=config['delphix_host'], username=config['username'], password=config['password'],
        api_prefix=config.get('api_prefix', '/masking/api'), mock_mode=config.get('mock_mode', False)
    )
    client.login()

    if args.init_baseline:
        r_msg = f" para la dupla (Prod ID {args.ruleset_id[0]} <-> Sonda ID {args.ruleset_id[1]})" if args.ruleset_id else " para todos los Rulesets activos"
        print(f"\n[LÍNEA BASE] Reconstruyendo inventario e infiriendo deltas{r_msg}...")

        rulesets = db.get_active_rulesets(ruleset_filter=args.ruleset_id)
        if not rulesets:
            print(f"⚠️ No se encontraron Rulesets activos para procesar la línea base.")
            return

        total_exclusions = 0
        for rs in rulesets:
            p_id = rs['prod_ruleset_id']
            d_id = rs['dummy_ruleset_id']
            alias = rs['ruleset_alias']

            print(f" -> Procesando línea base para Ruleset '{alias}' (Prod ID: {p_id} <-> Sonda ID: {d_id})...")
            
            # 1. Sincronizar Inventario Productivo
            prod_items = client.get_ruleset_tables_and_columns(p_id)
            db.sync_prod_inventory(p_id, prod_items)

            # 2. Refrescar Sonda de Descubrimiento
            async_task_id = client.refresh_ruleset(d_id)
            client.poll_async_task(async_task_id)

            dummy_items = client.get_ruleset_tables_and_columns(d_id)
            connector_id = client.get_ruleset_connector_id(d_id)
            source_table_names = client.get_connector_table_names(connector_id)

            # 3. Pisar y recalcular delta en exclusions
            c = db.reset_baseline_exclusions(p_id, dummy_items, source_table_names)
            total_exclusions += c

        print(f"✅ Línea Base nivelada exitosamente. Se registraron {total_exclusions} elementos en el delta de exclusiones{r_msg}.")
        return

    if args.audit:
        run_audit_cycle(config, db, client)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

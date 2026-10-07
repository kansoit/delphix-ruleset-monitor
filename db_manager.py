#!/usr/bin/env python3
import sqlite3
import os

DEFAULT_DATA_DIR = "/var/lib/delphix-ruleset-monitor"
DATA_DIR_ENV = "DELPHIX_RULESET_MONITOR_DATA_DIR"

class DatabaseManager:
    def __init__(self, db_path=None):
        if db_path is None:
            data_dir = os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR)
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "delphix_compliance_monitor.db")
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Inicializa las 3 tablas SQLite limpias: ruleset_config, prod_inventory, exclusions"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Tabla 1: Configuración y Gobierno de Rulesets
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ruleset_config (
                    prod_ruleset_id INTEGER PRIMARY KEY,
                    dummy_ruleset_id INTEGER NOT NULL,
                    ruleset_alias TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # Tabla 2: Inventario Espejo de Delphix Productivo
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prod_inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prod_ruleset_id INTEGER NOT NULL,
                    table_name TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    algorithm_name TEXT,
                    data_type TEXT,
                    UNIQUE(prod_ruleset_id, table_name, column_name)
                )
            """)

            # Tabla 3: Delta de Línea Base y Exclusiones (Sonda vs Prod)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS exclusions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prod_ruleset_id INTEGER NOT NULL,
                    table_name TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(prod_ruleset_id, table_name, column_name)
                )
            """)

            conn.commit()

    def get_active_rulesets(self, ruleset_filter=None):
        """Obtiene la lista de Rulesets configurados activos (is_active = 1), o filtrado por dupla/id"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if ruleset_filter:
                if isinstance(ruleset_filter, (tuple, list)) and len(ruleset_filter) == 2:
                    p_id, d_id = ruleset_filter
                    cursor.execute("SELECT * FROM ruleset_config WHERE is_active = 1 AND prod_ruleset_id = ? AND dummy_ruleset_id = ?", (p_id, d_id))
                else:
                    cursor.execute("SELECT * FROM ruleset_config WHERE is_active = 1 AND prod_ruleset_id = ?", (ruleset_filter,))
            else:
                cursor.execute("SELECT * FROM ruleset_config WHERE is_active = 1 ORDER BY prod_ruleset_id")
            return [dict(row) for row in cursor.fetchall()]

    def list_all_rulesets(self):
        """Lista la totalidad de Rulesets registrados en ruleset_config"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ruleset_config ORDER BY prod_ruleset_id")
            return [dict(row) for row in cursor.fetchall()]

    def set_ruleset_active(self, prod_ruleset_id, dummy_ruleset_id, is_active):
        """Cambia el estado de evaluación YES/NO de un par de Rulesets si coincide la dupla registrada"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ruleset_alias FROM ruleset_config WHERE prod_ruleset_id = ? AND dummy_ruleset_id = ?", (prod_ruleset_id, dummy_ruleset_id))
            row = cursor.fetchone()
            if not row:
                return False, f"No se encontró el par de Rulesets registrado (Prod ID: {prod_ruleset_id} <-> Sonda ID: {dummy_ruleset_id})."
            
            alias = row['ruleset_alias']
            val = 1 if is_active else 0
            cursor.execute("UPDATE ruleset_config SET is_active = ? WHERE prod_ruleset_id = ?", (val, prod_ruleset_id))
            conn.commit()
            estado_str = "YES (Activo)" if is_active else "NO (Pausado)"
            return True, f"Estado de evaluación para el Ruleset '{alias}' (Prod ID: {prod_ruleset_id} <-> Sonda ID: {dummy_ruleset_id}) actualizado exitosamente a: {estado_str}."

    def add_ruleset(self, prod_ruleset_id, dummy_ruleset_id, alias):
        """Registra un nuevo par de Rulesets en ruleset_config"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO ruleset_config (prod_ruleset_id, dummy_ruleset_id, ruleset_alias, is_active)
                VALUES (?, ?, ?, 1)
            """, (prod_ruleset_id, dummy_ruleset_id, alias))
            conn.commit()

    def remove_ruleset(self, prod_ruleset_id, dummy_ruleset_id):
        """Elimina un par de Rulesets de ruleset_config si coinciden los IDs, y limpia prod_inventory y exclusions asociadas"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ruleset_alias FROM ruleset_config WHERE prod_ruleset_id = ? AND dummy_ruleset_id = ?", (prod_ruleset_id, dummy_ruleset_id))
            row = cursor.fetchone()
            if not row:
                return False, f"No se encontró el par de Rulesets registrado (Prod ID: {prod_ruleset_id} <-> Sonda ID: {dummy_ruleset_id})."
            
            alias = row['ruleset_alias']
            cursor.execute("DELETE FROM ruleset_config WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            cursor.execute("DELETE FROM prod_inventory WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            cursor.execute("DELETE FROM exclusions WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            conn.commit()
            return True, f"Ruleset '{alias}' (Prod ID: {prod_ruleset_id} <-> Sonda ID: {dummy_ruleset_id}) eliminado exitosamente de la base de datos."

    def purge_database(self):
        """Purga la totalidad de los datos registrados en SQLite (ruleset_config, prod_inventory, exclusions) dejando la base en cero"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ruleset_config;")
            cursor.execute("DELETE FROM prod_inventory;")
            cursor.execute("DELETE FROM exclusions;")
            conn.commit()

    # --- Métodos de Inventario Productivo ---
    def sync_prod_inventory(self, prod_ruleset_id, items):
        """Reconstruye e inserta la foto actual del Ruleset Productivo"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM prod_inventory WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            for item in items:
                cursor.execute("""
                    INSERT OR REPLACE INTO prod_inventory (prod_ruleset_id, table_name, column_name, algorithm_name, data_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (prod_ruleset_id, item['table_name'], item['column_name'], item.get('algorithm_name'), item.get('data_type')))
            conn.commit()

    def list_prod_inventory(self, ruleset_filter=None):
        """Lista el inventario productivo filtrado opcionalmente por Ruleset"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT p.*, r.ruleset_alias FROM prod_inventory p JOIN ruleset_config r ON p.prod_ruleset_id = r.prod_ruleset_id WHERE 1=1"
            params = []
            if ruleset_filter:
                query += " AND p.prod_ruleset_id = ?"
                params.append(ruleset_filter)
            query += " ORDER BY p.prod_ruleset_id, p.table_name, p.column_name;"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # --- Métodos de Exclusiones / Línea Base ---
    def reset_baseline_exclusions(self, prod_ruleset_id, dummy_items):
        """
        Pisa y recalcula la Línea Base para un prod_ruleset_id específico:
        Calcula Delta = (Sonda - Productivo) e inserta en exclusions.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Borrar exclusiones anteriores de este Ruleset
            cursor.execute("DELETE FROM exclusions WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            
            # Obtener inventario productivo actual
            cursor.execute("SELECT table_name, column_name FROM prod_inventory WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            prod_set = {(row['table_name'].upper(), row['column_name'].upper()) for row in cursor.fetchall()}

            inserted_count = 0
            for item in dummy_items:
                tbl = item['table_name'].upper()
                col = item['column_name'].upper()
                if (tbl, col) not in prod_set:
                    cursor.execute("""
                        INSERT OR IGNORE INTO exclusions (prod_ruleset_id, table_name, column_name)
                        VALUES (?, ?, ?)
                    """, (prod_ruleset_id, item['table_name'], item['column_name']))
                    inserted_count += 1
            conn.commit()
            return inserted_count

    def list_exclusions(self, ruleset_filter=None, table_filter=None):
        """Lista las exclusiones de línea base registradas"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT e.*, r.ruleset_alias FROM exclusions e JOIN ruleset_config r ON e.prod_ruleset_id = r.prod_ruleset_id WHERE 1=1"
            params = []
            if ruleset_filter:
                query += " AND e.prod_ruleset_id = ?"
                params.append(ruleset_filter)
            if table_filter:
                query += " AND UPPER(e.table_name) = ?"
                params.append(table_filter.upper())
            query += " ORDER BY e.prod_ruleset_id, e.table_name, e.column_name;"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # --- Consultas de Deriva para Auditoría ---
    def analyze_drift(self, prod_ruleset_id, dummy_items):
        """
        Compara los ítems descubiertos en la Sonda (dummy_items) contra prod_inventory y exclusions
        para un prod_ruleset_id específico. Retorna dict con (new_structures, deleted_structures, data_type_drifts).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Obtener Prod
            cursor.execute("SELECT table_name, column_name, algorithm_name, data_type FROM prod_inventory WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            prod_dict = {(row['table_name'].upper(), row['column_name'].upper()): dict(row) for row in cursor.fetchall()}

            # 2. Obtener Exclusiones
            cursor.execute("SELECT table_name, column_name FROM exclusions WHERE prod_ruleset_id = ?", (prod_ruleset_id,))
            excl_set = {(row['table_name'].upper(), row['column_name'].upper()) for row in cursor.fetchall()}

            dummy_dict = {(item['table_name'].upper(), item['column_name'].upper()): item for item in dummy_items}

            new_structures = []
            deleted_structures = []
            data_type_drifts = []

            # Consulta A: Estructuras Nuevas (En Origen/Sonda pero NO en Prod ni en Exclusiones)
            for key, dummy_item in dummy_dict.items():
                if key not in prod_dict and key not in excl_set:
                    new_structures.append({
                        'prod_ruleset_id': prod_ruleset_id,
                        'table_name': dummy_item['table_name'],
                        'column_name': dummy_item['column_name'],
                        'data_type': dummy_item.get('data_type', 'VARCHAR')
                    })

            # Consulta B: Estructuras Eliminadas (En Prod pero NO en Origen/Sonda)
            for key, prod_item in prod_dict.items():
                if key not in dummy_dict:
                    deleted_structures.append({
                        'prod_ruleset_id': prod_ruleset_id,
                        'table_name': prod_item['table_name'],
                        'column_name': prod_item['column_name'],
                        'algorithm_name': prod_item.get('algorithm_name') or 'Sin Algoritmo'
                    })

            # Consulta C: Cambios de Tipo de Dato (En Prod y Origen con tipos diferentes)
            for key, prod_item in prod_dict.items():
                if key in dummy_dict:
                    dummy_item = dummy_dict[key]
                    p_dt = (prod_item.get('data_type') or '').strip().lower()
                    d_dt = (dummy_item.get('data_type') or '').strip().lower()
                    if p_dt and d_dt and p_dt != d_dt:
                        data_type_drifts.append({
                            'prod_ruleset_id': prod_ruleset_id,
                            'table_name': prod_item['table_name'],
                            'column_name': prod_item['column_name'],
                            'old_data_type': prod_item.get('data_type'),
                            'new_data_type': dummy_item.get('data_type')
                        })

            return {
                'new_structures': new_structures,
                'deleted_structures': deleted_structures,
                'data_type_drifts': data_type_drifts
            }

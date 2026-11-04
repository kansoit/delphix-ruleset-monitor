#!/usr/bin/env python3
import json
import urllib.request
import ssl
import time

# IDs que el modo mock trata como Sondas de Descubrimiento (ver get_all_engine_rulesets)
MOCK_PROBE_RULESET_IDS = {5, 7}

class DelphixMaskingClient:
    """
    Cliente de API REST para Delphix Continuous Compliance (Masking Engine).
    Maneja autenticación por token, refresco asíncrono de Rulesets y
    paginación sobre metadatos de tablas y columnas.
    """
    def __init__(self, host, username, password, api_prefix="/masking/api", mock_mode=False):
        self.host = host.rstrip('/')
        self.username = username
        self.password = password
        self.api_prefix = api_prefix
        self.mock_mode = mock_mode
        self.token = None
        self._ruleset_names_cache = None

        # Deshabilitar verificación SSL para entornos corporativos con certificados autofirmados
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def _request_json(self, path, method='GET', payload=None):
        """Ejecuta una petición autenticada contra la API y retorna el JSON de respuesta."""
        url = f"{self.host}{self.api_prefix}{path}"
        headers = {'Authorization': self.token}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, context=self.ctx) as response:
            return json.loads(response.read().decode('utf-8'))

    def login(self):
        """Autentica contra la API REST de Delphix Engine y obtiene el token Authorization."""
        if self.mock_mode:
            print("[MOCK] Autenticado exitosamente con Delphix Engine.")
            self.token = "MOCK-AUTH-TOKEN-12345"
            return

        url = f"{self.host}{self.api_prefix}/login"
        payload = json.dumps({
            "username": self.username,
            "password": self.password
        }).encode('utf-8')

        headers = {'Content-Type': 'application/json'}
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')

        try:
            with urllib.request.urlopen(req, context=self.ctx) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                # Delphix Masking Engine retorna {"Authorization": "token-guid"}
                self.token = res_data.get("Authorization") or res_data.get("token") or res_data.get("authorization")

                if not self.token and "responseList" in res_data:
                    self.token = res_data["responseList"][0].get("token")

                print(f"[SUCCESS] Login exitoso en Delphix Engine: {self.host}")
        except Exception as e:
            print(f"[ERROR] Error al autenticar en Delphix: {e}")
            raise

    def get_ruleset_name(self, ruleset_id):
        """Obtiene el nombre oficial de un Ruleset en Delphix Engine vía API"""
        if self.mock_mode:
            return f"Mock_Ruleset_{ruleset_id}"

        if self._ruleset_names_cache is None:
            self._ruleset_names_cache = {
                r["ruleset_id"]: r["ruleset_name"] for r in self.get_all_engine_rulesets()
            }

        return self._ruleset_names_cache.get(int(ruleset_id), f"Ruleset_{ruleset_id}")

    def get_all_engine_rulesets(self):
        """Consulta y retorna todos los Rulesets existentes en Delphix Engine con sus ID, nombres y tipo"""
        if self.mock_mode:
            return [
                {"ruleset_id": 4, "ruleset_name": "SQLSRV-TST", "type": "DATABASE"},
                {"ruleset_id": 5, "ruleset_name": "SQLSRV-TST-SONDA", "type": "DATABASE"},
                {"ruleset_id": 6, "ruleset_name": "SQLSRV-TST2", "type": "DATABASE"},
                {"ruleset_id": 7, "ruleset_name": "SQLSRV-TST2-SONDA", "type": "DATABASE"}
            ]

        try:
            res_data = self._request_json("/database-rulesets?page_size=1000")
            items = res_data.get("responseList", res_data.get("results", []))
            rulesets = []
            for item in items:
                r_id = item.get("databaseRulesetId") or item.get("rulesetId") or item.get("id")
                r_name = item.get("rulesetName") or item.get("name") or f"Ruleset_{r_id}"
                r_type = item.get("rulesetType") or item.get("type") or "DATABASE"
                if r_id:
                    rulesets.append({
                        "ruleset_id": int(r_id),
                        "ruleset_name": r_name,
                        "type": r_type
                    })
            return sorted(rulesets, key=lambda x: x["ruleset_id"])
        except Exception as e:
            print(f"[ERROR] Error al consultar la lista completa de Rulesets en Delphix Engine: {e}")
            return []

    def get_ruleset_details(self, ruleset_id):
        """Obtiene el detalle de un Ruleset, incluido el conector asociado."""
        if self.mock_mode:
            return {
                "databaseRulesetId": ruleset_id,
                "databaseConnectorId": 1,
                "rulesetName": f"Mock_Ruleset_{ruleset_id}"
            }

        try:
            data = self._request_json(f"/database-rulesets/{ruleset_id}")
            if isinstance(data, dict) and data.get('responseList'):
                return data['responseList'][0]
            return data
        except Exception as e:
            raise RuntimeError(f"No se pudo obtener el detalle del Ruleset {ruleset_id}: {e}") from e

    def get_ruleset_connector_id(self, ruleset_id):
        """Obtiene el ID del conector de base de datos asociado a un Ruleset."""
        details = self.get_ruleset_details(ruleset_id)
        connector_id = (
            details.get('databaseConnectorId')
            or details.get('connectorId')
            or details.get('database_connector_id')
        )
        if not connector_id:
            raise RuntimeError(f"El Ruleset {ruleset_id} no informa un databaseConnectorId.")
        return int(connector_id)

    def get_connector_table_names(self, connector_id):
        """Obtiene del conector las tablas actualmente visibles en la base de datos origen."""
        if self.mock_mode:
            return ["CUSTOMERS", "ORDERS", "AUDIT_LOGS", "TMP_STAGING", "NEW_SOURCE_TABLE"]

        try:
            data = self._request_json(f"/database-connectors/{connector_id}/fetch")
            if isinstance(data, list):
                raw_names = data
            elif isinstance(data, dict):
                raw_names = data.get('responseList', data.get('results', data.get('tables', [])))
            else:
                raw_names = []

            names = []
            for item in raw_names:
                if isinstance(item, str):
                    name = item
                elif isinstance(item, dict):
                    name = item.get('tableName') or item.get('table_name') or item.get('name')
                else:
                    name = None
                if name:
                    names.append(str(name))
            return sorted(set(names), key=str.upper)
        except Exception as e:
            raise RuntimeError(
                f"No se pudo consultar el catálogo de tablas del conector {connector_id}: {e}"
            ) from e

    def ensure_refresh_drops_tables(self, ruleset_id):
        """Asegura que el Ruleset en Delphix Engine tenga refreshDropsTables=True para tolerar bajas de tablas en la sonda de descubrimiento"""
        try:
            data = self.get_ruleset_details(ruleset_id)
            if not data.get('refreshDropsTables'):
                data['refreshDropsTables'] = True
                self._request_json(f"/database-rulesets/{ruleset_id}", method='PUT', payload=data)
        except Exception as e:
            print(f"[WARN] No se pudo asegurar refreshDropsTables=True en el Ruleset {ruleset_id}: {e}")

    def refresh_ruleset(self, ruleset_id):
        """
        Dispara la tarea asíncrona de refresh sobre un Ruleset especificado.
        Endpoint: PUT /masking/api/database-rulesets/{id}/refresh
        Retorna el async_task_id.
        """
        if self.mock_mode:
            print(f"[MOCK] Disparado refresh PUT /database-rulesets/{ruleset_id}/refresh...")
            return "mock-async-task-999"

        self.ensure_refresh_drops_tables(ruleset_id)

        try:
            res_data = self._request_json(f"/database-rulesets/{ruleset_id}/refresh", method='PUT')
            async_task_id = res_data.get("asyncTaskId") or res_data.get("id") or res_data.get("responseList", [{}])[0].get("asyncTaskId")
            print(f"[SUCCESS] Refresh disparado para Ruleset ID {ruleset_id}. Async Task ID: {async_task_id}")
            return async_task_id
        except Exception as e:
            print(f"[ERROR] Error al disparar refresh para Ruleset {ruleset_id}: {e}")
            raise

    def poll_async_task(self, async_task_id, timeout=300, poll_interval=5):
        """
        Realiza sondeo (polling) sobre GET /masking/api/async-tasks/{id} hasta que el estado
        sea 'SUCCEEDED' o 'FAILED', saliendo inmediatamente sin loops infinitos.
        """
        if self.mock_mode:
            print(f"[MOCK] Polling GET /async-tasks/{async_task_id} -> SUCCEEDED")
            return True

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                res_data = self._request_json(f"/async-tasks/{async_task_id}")
                status = res_data.get("status") or res_data.get("responseList", [{}])[0].get("status")

                print(f" -> Estado de tarea asíncrona ({async_task_id}): {status}")
                if status in ['SUCCEEDED', 'COMPLETED']:
                    return True
                elif status in ['FAILED', 'CANCELLED']:
                    print(f"[WARN] La tarea asíncrona {async_task_id} finalizó con estado '{status}' en Delphix Engine.")
                    return False
            except Exception as e:
                print(f"[WARN] Error de comunicación durante polling de async-task {async_task_id}: {e}")

            time.sleep(poll_interval)

        raise TimeoutError(f"Tiempo de espera agotado ({timeout}s) durante el refresh de la tarea {async_task_id}")

    def _get_column_metadata(self, table_metadata_id):
        """Obtiene las columnas asociadas a una tabla mediante GET /masking/api/column-metadata?table_metadata_id={id}"""
        try:
            res_data = self._request_json(f"/column-metadata?table_metadata_id={table_metadata_id}&page_size=1000")
            return res_data.get("responseList", res_data.get("results", []))
        except Exception as e:
            # Reintentar con camelCase si snake_case no matchea
            try:
                res_alt = self._request_json(f"/column-metadata?tableMetadataId={table_metadata_id}&page_size=1000")
                return res_alt.get("responseList", res_alt.get("results", []))
            except Exception:
                print(f"[WARN] Error al obtener columnas para tableMetadataId={table_metadata_id}: {e}")
                return []

    def get_ruleset_tables_and_columns(self, ruleset_id):
        """
        Obtiene el inventario completo de tablas y columnas asociadas a un Ruleset mediante
        GET /masking/api/table-metadata?ruleset_id={id} y GET /masking/api/column-metadata?table_metadata_id={id}.
        """
        if self.mock_mode:
            if ruleset_id in MOCK_PROBE_RULESET_IDS: # Sonda de Descubrimiento del origen
                return [
                    {"table_name": "CUSTOMERS", "column_name": "CUSTOMER_ID", "data_type": "INTEGER"},
                    {"table_name": "CUSTOMERS", "column_name": "FULL_NAME", "data_type": "VARCHAR"},
                    {"table_name": "CUSTOMERS", "column_name": "EMAIL_ADDR", "data_type": "VARCHAR"},
                    {"table_name": "ORDERS", "column_name": "ORDER_ID", "data_type": "INTEGER"},
                    {"table_name": "ORDERS", "column_name": "TOTAL_AMOUNT", "data_type": "DECIMAL"},
                    {"table_name": "ORDERS", "column_name": "TAX_IDENTIFIER", "data_type": "VARCHAR"},
                    {"table_name": "AUDIT_LOGS", "column_name": "LOG_ID", "data_type": "INTEGER"},
                    {"table_name": "AUDIT_LOGS", "column_name": "ACTION_TEXT", "data_type": "VARCHAR"},
                    {"table_name": "TMP_STAGING", "column_name": "SESSION_ID", "data_type": "VARCHAR"}
                ]
            else: # Inventario del Ruleset Productivo
                return [
                    {"table_name": "CUSTOMERS", "column_name": "CUSTOMER_ID", "algorithm_name": None, "data_type": "INTEGER"},
                    {"table_name": "CUSTOMERS", "column_name": "FULL_NAME", "algorithm_name": "FirstNameLookup", "data_type": "VARCHAR"},
                    {"table_name": "CUSTOMERS", "column_name": "EMAIL_ADDR", "algorithm_name": "EmailRedact", "data_type": "VARCHAR"},
                    {"table_name": "ORDERS", "column_name": "ORDER_ID", "algorithm_name": None, "data_type": "INTEGER"},
                    {"table_name": "ORDERS", "column_name": "TOTAL_AMOUNT", "algorithm_name": None, "data_type": "NUMERIC"},
                    {"table_name": "LEGACY_ACCOUNTS", "column_name": "ACCOUNT_NO", "algorithm_name": "AccountNumberMask", "data_type": "VARCHAR"}
                ]

        # Paginación sobre GET /masking/api/table-metadata?ruleset_id={id}
        page = 1
        page_size = 1000
        items = []

        while True:
            try:
                res_data = self._request_json(
                    f"/table-metadata?ruleset_id={ruleset_id}&page_number={page}&page_size={page_size}"
                )
                response_list = res_data.get("responseList", res_data.get("results", []))

                if not response_list:
                    break

                for tbl in response_list:
                    table_id = tbl.get("tableMetadataId") or tbl.get("databaseTableId") or tbl.get("id")
                    table_name = tbl.get("tableName") or tbl.get("table_name")

                    # Obtener columnas de cada tabla mediante GET /column-metadata
                    columns = self._get_column_metadata(table_id)
                    if not columns:
                        items.append({
                            "table_name": table_name,
                            "column_name": tbl.get("columnName", "*"),
                            "algorithm_name": tbl.get("algorithmName"),
                            "data_type": tbl.get("dataType", "VARCHAR")
                        })
                    else:
                        for col in columns:
                            items.append({
                                "table_name": table_name,
                                "column_name": col.get("columnName") or col.get("column_name"),
                                "algorithm_name": col.get("algorithmName") or col.get("algorithm_name"),
                                "data_type": col.get("dataType") or col.get("data_type") or "VARCHAR"
                            })

                page_info = res_data.get("_pageInfo", {})
                total_items = page_info.get("total", len(response_list))
                if page * page_size >= total_items or len(response_list) < page_size:
                    break
                page += 1

            except Exception as e:
                print(f"[ERROR] Error al consultar tablas para Ruleset {ruleset_id}: {e}")
                raise

        return items

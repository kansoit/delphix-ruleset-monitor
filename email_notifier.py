#!/usr/bin/env python3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from html import escape

REPORT_STYLE = """<style>
                body { font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 20px; }
                .header { background-color: #003366; color: #ffffff; padding: 15px; text-align: center; border-radius: 5px; }
                .ruleset-banner { background-color: #e9ecef; color: #1b1e21; padding: 10px; border-left: 5px solid #003366; margin: 15px 0; border-radius: 3px; }
                .alert-box { background-color: #fff3cd; color: #856404; padding: 10px; border: 1px solid #ffeeba; border-radius: 5px; margin-bottom: 20px; }
                table { width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 25px; }
                th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
                th { background-color: #f2f2f2; color: #333; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .badge-new { background-color: #d4edda; color: #155724; padding: 3px 8px; border-radius: 3px; font-weight: bold; }
                .badge-del { background-color: #f8d7da; color: #721c24; padding: 3px 8px; border-radius: 3px; font-weight: bold; }
                .badge-drift { background-color: #cce5ff; color: #004085; padding: 3px 8px; border-radius: 3px; font-weight: bold; }
                .badge-fail { background-color: #f8d7da; color: #721c24; padding: 3px 8px; border-radius: 3px; font-weight: bold; }
                .footer { font-size: 12px; color: #777; margin-top: 30px; text-align: center; border-top: 1px solid #eee; padding-top: 10px; }
            </style>"""

class EmailNotifier:
    def __init__(self, config):
        self.enabled = config.get("email_enabled", False)
        self.smtp_host = config.get("smtp_host", "localhost")
        self.smtp_port = config.get("smtp_port", 587)
        self.smtp_user = config.get("smtp_user", "")
        self.smtp_password = config.get("smtp_password", "")
        self.use_tls = config.get("use_tls", True)
        self.email_from = config.get("email_from", "delphix-monitor@company.com")
        self.email_to = config.get("email_to", [])

    def send_audit_alert(self, ruleset_name, ruleset_id, dummy_ruleset_id, new_structures, deleted_structures, data_type_drifts):
        """Envia un correo en formato HTML con las diferencias detectadas en un Ruleset"""
        subject = f"⚠️ [ALERTA DELPHIX] Deriva de Esquema en Ruleset: {ruleset_name} (ID: {ruleset_id}) - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        # Construir cuerpo HTML profesional enfocado en el Ruleset
        html_content = self._build_html_report(ruleset_name, ruleset_id, dummy_ruleset_id, new_structures, deleted_structures, data_type_drifts)
        self._send(subject, html_content, f"Ruleset '{ruleset_name}'")

    def send_failure_alert(self, failures):
        """Envia un correo operativo con los Rulesets que no pudieron auditarse en la ejecución actual"""
        subject = f"❌ [ALERTA DELPHIX] Auditoría incompleta: {len(failures)} Ruleset(s) sin auditar - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        html_content = self._build_failure_report(failures)
        self._send(subject, html_content, "auditoría incompleta")

    def _send(self, subject, html_content, description):
        if not self.enabled:
            print("[INFO] Notificación por correo deshabilitada en la configuración (email_enabled = false).")
            return

        if not self.email_to:
            print("[WARN] No se especificaron destinatarios en 'email_to'. No se enviará correo.")
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = ", ".join(self.email_to) if isinstance(self.email_to, list) else self.email_to

        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            print(f"[INFO] Conectando al servidor SMTP {self.smtp_host}:{self.smtp_port}...")
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)

                destinarios = self.email_to if isinstance(self.email_to, list) else [self.email_to]
                server.sendmail(self.email_from, destinarios, msg.as_string())
            print(f"✅ Correo de alerta enviado exitosamente ({description}) a: {', '.join(destinarios)}")
        except Exception as e:
            print(f"[ERROR] Falló el envío del correo de alerta por SMTP ({description}): {e}")

    def _build_failure_report(self, failures):
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            {REPORT_STYLE}
        </head>
        <body>
            <div class="header">
                <h2>Delphix Continuous Compliance - Auditoría de Esquema</h2>
            </div>

            <p>Estimado Operador,</p>
            <p>La auditoría quedó <strong>incompleta</strong>: los siguientes Rulesets no pudieron auditarse porque no fue posible obtener una foto actualizada del origen. <strong>Para estos Rulesets no se evaluaron diferencias</strong>, por lo que la ausencia de alertas de deriva no implica que el esquema esté sin cambios.</p>
            <table>
                <thead>
                    <tr>
                        <th>Ruleset</th>
                        <th>ID Productivo</th>
                        <th>ID Sonda</th>
                        <th>Motivo</th>
                        <th>Estado</th>
                    </tr>
                </thead>
                <tbody>
        """
        for item in failures:
            html += f"""
                    <tr>
                        <td><code>{escape(item['ruleset_name'])}</code></td>
                        <td>{item['prod_ruleset_id']}</td>
                        <td>{item['dummy_ruleset_id']}</td>
                        <td>{escape(item['error'])}</td>
                        <td><span class="badge-fail">NO AUDITADO</span></td>
                    </tr>
            """
        html += f"""
                </tbody>
            </table>

            <div class="alert-box">
                <strong>Acciones sugeridas:</strong>
                <ul>
                    <li>Verifique en Delphix Engine el estado de las tareas de refresh de las Sondas indicadas y el conector de base de datos asociado (credenciales, conectividad y permisos sobre el origen).</li>
                    <li>Una vez corregida la causa, ejecute manualmente la auditoría: <code>ruleset_monitor.py --audit</code></li>
                    <li>Este aviso se repetirá en cada ejecución mientras la falla persista.</li>
                </ul>
            </div>

            <div class="footer">
                <p>Reporte generado automáticamente por Delphix Ruleset Drift Monitor | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </body>
        </html>
        """
        return html

    def _build_html_report(self, ruleset_name, ruleset_id, dummy_ruleset_id, new_structures, deleted_structures, data_type_drifts):
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            {REPORT_STYLE}
        </head>
        <body>
            <div class="header">
                <h2>Delphix Continuous Compliance - Auditoría de Esquema</h2>
            </div>
            
            <div class="ruleset-banner">
                <h3>📌 Ruleset Evaluado: <strong>{ruleset_name}</strong> (ID Productivo: {ruleset_id} <-> Sonda ID: {dummy_ruleset_id})</h3>
            </div>

            <p>Estimado Operador,</p>
            <p>Se han detectado <strong>diferencias estructurales (schema drift)</strong> entre el inventario del Ruleset Productivo <strong>{ruleset_name}</strong> (ID: {ruleset_id}) y la estructura observada en la base de datos de origen.</p>
        """

        if new_structures:
            html += f"""
            <h4 style="color: #155724;">⚠️ Estructuras Nuevas Detectadas en Origen ({len(new_structures)} estructuras)</h4>
            <p>Las siguientes tablas/columnas existen en el origen pero <strong>NO están configuradas en el Ruleset Productivo ni registradas en la línea base de exclusiones</strong>:</p>
            <table>
                <thead>
                    <tr>
                        <th>Ruleset</th>
                        <th>Tabla</th>
                        <th>Columna / Estructura</th>
                        <th>Tipo de Dato</th>
                        <th>Estado</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in new_structures:
                r_name = item['ruleset_name']
                column_name = 'Tabla completa' if item['column_name'] == '*' else item['column_name']
                html += f"""
                    <tr>
                        <td><code>{r_name}</code></td>
                        <td><strong>{item['table_name']}</strong></td>
                        <td>{column_name}</td>
                        <td><code>{item['data_type']}</code></td>
                        <td><span class="badge-new">NUEVO EN ORIGEN</span></td>
                    </tr>
                """
            html += """
                </tbody>
            </table>
            """

        if deleted_structures:
            html += f"""
            <h4 style="color: #721c24;">🚫 Estructuras Eliminadas en Origen ({len(deleted_structures)} columnas)</h4>
            <p>Las siguientes estructuras están configuradas en el Ruleset Productivo pero <strong>YA NO existen en la base de datos origen</strong>:</p>
            <table>
                <thead>
                    <tr>
                        <th>Ruleset</th>
                        <th>Tabla</th>
                        <th>Columna</th>
                        <th>Algoritmo Configurado</th>
                        <th>Estado</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in deleted_structures:
                algo = item['algorithm_name']
                r_name = item['ruleset_name']
                html += f"""
                    <tr>
                        <td><code>{r_name}</code></td>
                        <td><strong>{item['table_name']}</strong></td>
                        <td>{item['column_name']}</td>
                        <td><code>{algo}</code></td>
                        <td><span class="badge-del">ELIMINADO EN ORIGEN</span></td>
                    </tr>
                """
            html += """
                </tbody>
            </table>
            """

        if data_type_drifts:
            html += f"""
            <h4 style="color: #004085;">⚡ Cambios en Tipo de Dato Detectados ({len(data_type_drifts)} columnas)</h4>
            <p>Las siguientes columnas en la base de datos origen han cambiado su tipo de dato respecto a la configuración del Ruleset Productivo:</p>
            <table>
                <thead>
                    <tr>
                        <th>Ruleset</th>
                        <th>Tabla</th>
                        <th>Columna</th>
                        <th>Tipo en Ruleset</th>
                        <th>Tipo en Origen</th>
                        <th>Estado</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in data_type_drifts:
                r_name = item['ruleset_name']
                html += f"""
                    <tr>
                        <td><code>{r_name}</code></td>
                        <td><strong>{item['table_name']}</strong></td>
                        <td>{item['column_name']}</td>
                        <td><code>{item['old_data_type']}</code></td>
                        <td><code>{item['new_data_type']}</code></td>
                        <td><span class="badge-drift">CAMBIO DE TIPO</span></td>
                    </tr>
                """
            html += """
                </tbody>
            </table>
            """

        html += f"""
            <div class="alert-box">
                <strong>Acciones sugeridas:</strong>
                <ul>
                    <li>Revise cada diferencia y determine si corresponde a una modificación esperada, a un ajuste requerido en el Ruleset Productivo o a un problema de acceso o descubrimiento en la base de datos de origen.</li>
                    <li>Después de aplicar las correcciones o aceptar explícitamente las diferencias, reconstruya la línea base ejecutando: <code>ruleset_monitor.py --init-baseline --ruleset-id {ruleset_id} {dummy_ruleset_id}</code></li>
                </ul>
            </div>

            <div class="footer">
                <p>Reporte generado automáticamente por Delphix Ruleset Drift Monitor | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </body>
        </html>
        """
        return html

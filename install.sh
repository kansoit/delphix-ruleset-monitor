#!/usr/bin/env bash
# Script unificado de instalación para Delphix Ruleset Drift Monitor
set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/usr/local/bin/delphix-ruleset-monitor"
DATA_DIR="/var/lib/delphix-ruleset-monitor"
CONFIG_DIR="/etc/delphix-ruleset-monitor"

echo "================================================================================"
echo "    INSTALADOR UNIFICADO - DELPHIX CONTINUOUS COMPLIANCE RULESET MONITOR       "
echo "================================================================================"

# Verificar privilegios de superusuario (sudo)
if [ "$EUID" -ne 0 ]; then
  echo "❌ Error: Este script debe ejecutarse como root o con sudo."
  echo "   Ejemplo: sudo ./install.sh"
  exit 1
fi

echo "1. Creando directorios de instalación y datos..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${DATA_DIR}"
mkdir -p "${CONFIG_DIR}"

echo "2. Eliminando base SQLite preexistente en ${DATA_DIR}..."
if [ -f "${DATA_DIR}/delphix_compliance_monitor.db" ]; then
    rm -f "${DATA_DIR}/delphix_compliance_monitor.db"
    echo " -> Base SQLite preexistente eliminada."
else
    echo " -> No se encontró una base SQLite preexistente."
fi

echo "3. Copiando scripts de aplicación Python..."
cp "${SCRIPT_DIR}/db_manager.py" "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/delphix_client.py" "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/email_notifier.py" "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/ruleset_monitor.py" "${INSTALL_DIR}/"

echo " -> La configuración se administra en ${CONFIG_DIR}/config.json."

echo "4. Asignando propietario root:root al directorio y archivos de aplicación..."
chown -R root:root "${INSTALL_DIR}"
chown root:root "${DATA_DIR}"
chmod 755 "${DATA_DIR}"
chown root:root "${CONFIG_DIR}"
chmod 755 "${CONFIG_DIR}"
if [ -f "${CONFIG_DIR}/config.json" ]; then
    chown root:root "${CONFIG_DIR}/config.json"
    chmod 600 "${CONFIG_DIR}/config.json"
fi

echo "5. Asignando permisos de ejecución a scripts Python..."
chmod +x "${INSTALL_DIR}"/*.py

echo "5b. Creando enlace simbólico ejecutable global en /usr/local/bin/ruleset_monitor.py..."
ln -sf "${INSTALL_DIR}/ruleset_monitor.py" /usr/local/bin/ruleset_monitor.py
chown -h root:root /usr/local/bin/ruleset_monitor.py

echo "6. Instalando servicios y timers de Systemd con propietario root:root..."
cp delphix-ruleset-monitor.service /etc/systemd/system/
cp delphix-ruleset-monitor.timer /etc/systemd/system/

chown root:root /etc/systemd/system/delphix-ruleset-monitor.service
chown root:root /etc/systemd/system/delphix-ruleset-monitor.timer
chmod 644 /etc/systemd/system/delphix-ruleset-monitor.service
chmod 644 /etc/systemd/system/delphix-ruleset-monitor.timer

systemctl daemon-reload
systemctl enable --now delphix-ruleset-monitor.timer

echo "================================================================================"
echo "✅ INSTALACIÓN COMPLETADA EXITOSAMENTE"
echo "================================================================================"
echo "Archivos instalados en: ${INSTALL_DIR}"
echo "Estado del Timer Systemd: $(systemctl is-active delphix-ruleset-monitor.timer)"
echo ""
echo "Pasos sugeridos:"
echo " 1) Si aún no configuraste credenciales, ejecuta el asistente seguro:"
echo "    sudo ruleset_monitor.py --configure"
echo ""
echo " 2) Probar ejecución manual:"
echo "    sudo ruleset_monitor.py --audit"
echo "================================================================================"

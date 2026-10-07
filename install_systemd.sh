#!/usr/bin/env bash
# Script de instalación automática de servicio y timer Systemd
set -e

echo "Instalando servicio y timer de Delphix Ruleset Monitor en systemd..."

sudo cp delphix-ruleset-monitor.service /etc/systemd/system/
sudo cp delphix-ruleset-monitor.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now delphix-ruleset-monitor.timer

echo "✅ Servicio y Timer Systemd instalados y activados exitosamente."
echo "Puedes verificar el estado con: sudo systemctl status delphix-ruleset-monitor.timer"

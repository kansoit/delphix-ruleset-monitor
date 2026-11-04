# Guía de Usuario

## Delphix Ruleset Drift Monitor

Esta herramienta controla la deriva estructural entre un Ruleset productivo de Delphix Continuous Compliance y un Ruleset sonda utilizado para descubrir la estructura actual de la base de datos origen.

El objetivo es detectar cambios que puedan dejar tablas o campos fuera de la cobertura de enmascaramiento.

## Flujo de trabajo recomendado

Para incorporar una nueva pareja de Rulesets:

1. Configurar la conexión con Delphix, SMTP y las notificaciones.
2. Crear manualmente el Ruleset sonda en Delphix y alinear inicialmente sus tablas y campos con el Ruleset productivo.
3. Consultar los Rulesets existentes en el motor con `--list-engine-rulesets`.
4. Registrar la pareja productivo/sonda con `--add-ruleset`.
5. Crear la línea base inicial con `--init-baseline`.
6. Ejecutar la auditoría con `--audit`.
7. Revisar las diferencias detectadas y corregir el Ruleset productivo o aceptar explícitamente las diferencias.
8. Repetir `--init-baseline` después de aplicar las correcciones.
9. Ejecutar nuevamente `--audit` para confirmar que no quedan diferencias sin gestionar.
10. Programar las auditorías periódicas mediante el timer de systemd.

La línea base no debe reconstruirse automáticamente al recibir una alerta. Primero se debe determinar si la diferencia requiere cobertura de enmascaramiento o si es un cambio intencional que puede aceptarse.

## Casos controlados

El monitor contempla estos cinco casos:

1. Tablas añadidas en el origen.
2. Tablas eliminadas del origen.
3. Campos añadidos dentro de una tabla.
4. Campos eliminados de una tabla.
5. Cambios de tipo de dato en campos existentes.

Las tablas conocidas se comparan indirectamente mediante sus campos. Además, el monitor consulta el catálogo del conector de la base de datos origen para detectar una tabla que exista en el origen pero no esté presente en ninguno de los dos Rulesets. Si aparece una tabla con columnas nuevas, esas columnas se reportan como nuevas; si desaparecen todas las columnas conocidas de una tabla, se reportan como eliminadas. El objetivo operativo es detectar cualquier cambio estructural relevante.

## Modelos de implementación

La pareja de Rulesets debe prepararse según el método de enmascaramiento:

### Enmascaramiento In-Place

```text
Ruleset productivo → conector de la base origen
Ruleset sonda      → mismo conector de la base origen
```

El Ruleset productivo representa la configuración aprobada de enmascaramiento para la base origen. La sonda se alinea inicialmente con él y se refresca para descubrir cambios en esa misma base.

### Enmascaramiento On-The-Fly

```text
Ruleset productivo/destino → conector de la base destino
Ruleset sonda/origen      → conector de la base origen
```

El trabajo On-The-Fly utiliza el Ruleset productivo/destino y selecciona por separado el conector origen. La sonda se utiliza para que este monitor inspeccione la estructura real del origen. El monitor compara la estructura esperada en destino con la estructura descubierta en origen; las diferencias intencionales deben aceptarse mediante la línea base.

## Conceptos principales

### Ruleset productivo

Es el Ruleset que contiene la configuración aprobada de enmascaramiento: tablas, campos y algoritmos.

### Ruleset sonda

Es un Ruleset auxiliar que se refresca contra la base de datos origen. Su función es descubrir la estructura real existente en ese momento.

### Línea base

Es el conjunto de diferencias conocidas y aceptadas entre el Ruleset productivo y la sonda. Una diferencia incluida en la línea base no vuelve a generar una alerta durante la auditoría.

## Flujo de una auditoría

Para cada pareja activa, el programa:

1. Consulta el inventario actual del Ruleset productivo.
2. Guarda esa fotografía en SQLite.
3. Ejecuta el refresh del Ruleset sonda.
4. Espera la finalización de la tarea asíncrona de Delphix.
5. Consulta las tablas y campos descubiertos por la sonda.
6. Consulta el catálogo del conector para obtener las tablas visibles en la base de datos origen.
7. Compara ambos inventarios, el catálogo del origen y las exclusiones de línea base.
8. Muestra las diferencias en pantalla.
9. Envía un correo HTML por cada Ruleset con diferencias, si el correo está habilitado.

## Instalación

El instalador resuelve su propia ubicación, por lo que puede ejecutarse desde cualquier directorio:

```bash
sudo /ruta/al/repositorio/delphix-ruleset-monitor/install.sh
```

La instalación copia la aplicación en `/usr/local/bin/delphix-ruleset-monitor`, guarda los datos runtime en `/var/lib/delphix-ruleset-monitor`, crea el comando global `/usr/local/bin/ruleset_monitor.py` y habilita un timer de systemd que ejecuta la auditoría de lunes a viernes a las 08:00.

No es necesario ejecutar `install_systemd.sh` después de una instalación completa. `install.sh` ya instala las unidades systemd, recarga systemd y habilita el timer. `install_systemd.sh` debe utilizarse solamente cuando la aplicación ya está instalada y se necesita instalar o actualizar las unidades systemd de forma independiente.

Cada instalación completa elimina `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` si existe. Esto borra las parejas registradas, los inventarios productivos y las exclusiones de línea base, por lo que luego será necesario registrar nuevamente las parejas y crear sus líneas base. La configuración ubicada en `/etc/delphix-ruleset-monitor/config.json` se conserva durante las reinstalaciones.

### Separación entre aplicación y datos

La instalación mantiene separados los scripts ejecutables y los datos modificables:

| Propósito | Ubicación |
|---|---|
| Scripts de la aplicación | `/usr/local/bin/delphix-ruleset-monitor/` |
| Comando global | `/usr/local/bin/ruleset_monitor.py` |
| Configuración local | `/etc/delphix-ruleset-monitor/config.json` |
| Identidad age de las credenciales | `/etc/delphix-ruleset-monitor/age.key` |
| Base SQLite runtime | `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` |

Para desarrollo o pruebas, se puede definir `DELPHIX_RULESET_MONITOR_DATA_DIR` y utilizar otro directorio de datos sin mover los scripts.

## Configuración

Ejecutar el asistente:

```bash
sudo ruleset_monitor.py --configure
```

El asistente solicita URL, usuario y contraseña de Delphix, configuración SMTP, remitente y destinatarios. Escribe `/etc/delphix-ruleset-monitor/config.json`, protegido con permisos `600`.

Los usuarios y contraseñas de Delphix y SMTP se cifran con [age](https://github.com/FiloSottile/age), que debe estar instalado antes de la instalación (en RHEL/Oracle Linux 9: `dnf install age` desde EPEL). En la primera ejecución, el asistente crea la identidad `/etc/delphix-ruleset-monitor/age.key` con permisos `600` y cifra esos campos con su clave pública.

Se debe respaldar `age.key` por separado de `config.json`: sin ella no es posible descifrar las credenciales y habrá que ejecutar nuevamente `--configure`. Si un campo de credenciales contiene un valor sin cifrar, el monitor se detiene con un error.

Como el servicio se ejecuta sin intervención, la identidad reside en el mismo servidor. El cifrado protege las credenciales si `config.json` se copia, se respalda o se comparte, pero no frente a un usuario que ya tiene acceso root al servidor.

## Preparar la pareja de Rulesets en Delphix

Antes de registrar una pareja, consultar los Rulesets existentes en el Engine para identificar los IDs del Ruleset productivo y del Ruleset sonda:

```bash
sudo ruleset_monitor.py --list-engine-rulesets
```

La consulta muestra el ID, el nombre oficial y el tipo de cada Ruleset disponible en Delphix.

Antes de registrar la pareja en la herramienta, se debe preparar el Ruleset sonda directamente en el motor de Delphix Continuous Compliance. En In-Place, ambos Rulesets utilizan el mismo conector de la base origen. En On-The-Fly, el Ruleset productivo pertenece al conector destino y el Ruleset sonda pertenece al conector origen. En ambos casos, la sonda debe representar inicialmente la estructura del Ruleset productivo, salvo que exista una diferencia intencional entre origen y destino:

1. Identificar el Ruleset productivo que se desea monitorear.
2. Crear un nuevo Ruleset para utilizarlo como sonda o discovery Ruleset.
3. Copiar inicialmente al Ruleset sonda el mismo contenido del Ruleset productivo: tablas y campos configurados.
4. Verificar que ambos Rulesets representen la misma estructura inicial.

Este paso es importante porque la primera sincronización debe comenzar sin diferencias accidentales. De esta forma, la línea base se construye sobre una pareja alineada y las diferencias posteriores representan cambios reales en el origen.

La herramienta no crea ni clona Rulesets dentro de Delphix. El Ruleset sonda debe existir previamente en el motor y su ID se utilizará al registrar la pareja.

## Registrar una pareja de Rulesets

```bash
sudo ruleset_monitor.py --add-ruleset PROD_ID SONDA_ID
```

Ejemplo:

```bash
sudo ruleset_monitor.py --add-ruleset 4 5
```

El programa valida los IDs contra Delphix y guarda la pareja en la base SQLite local.

Después de registrar la pareja, crear la línea base inicial:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id PROD_ID SONDA_ID
```

Por ejemplo:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id 4 5
```

La primera línea base debe ejecutarse cuando el Ruleset sonda ya tenga el contenido inicial equivalente al Ruleset productivo.

Consultar las parejas registradas:

```bash
sudo ruleset_monitor.py --list-config
```

## Activar o pausar una pareja

Pausar una pareja:

```bash
sudo ruleset_monitor.py --set-active PROD_ID SONDA_ID NO
```

Reactivarla:

```bash
sudo ruleset_monitor.py --set-active PROD_ID SONDA_ID YES
```

Las parejas pausadas no participan en `--audit`.

## Crear o reconstruir la línea base

Para todos los Rulesets activos:

```bash
sudo ruleset_monitor.py --init-baseline
```

Para una pareja específica:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id PROD_ID SONDA_ID
```

Este comando elimina las exclusiones anteriores de la pareja seleccionada y calcula nuevamente las diferencias aceptadas entre la sonda y el Ruleset productivo. Debe ejecutarse solamente cuando las diferencias hayan sido revisadas y aceptadas.

Si una tabla existe en el origen pero intencionalmente no se incorporará a ninguno de los Rulesets, este comando registra una exclusión para la tabla completa. Los cambios futuros en una tabla excluida no generarán alertas hasta que la exclusión sea reemplazada mediante una nueva línea base después de incorporar la tabla al monitoreo.

## Ejecutar la auditoría

```bash
sudo ruleset_monitor.py --audit
```

El resultado se muestra en tres grupos principales:

- Estructuras nuevas en origen.
- Estructuras eliminadas en origen.
- Cambios de tipo de dato.

Las tablas añadidas o eliminadas aparecen representadas mediante los campos asociados.

## Consultas disponibles

```bash
sudo ruleset_monitor.py --list-prod
sudo ruleset_monitor.py --list-prod --ruleset-id PROD_ID SONDA_ID
sudo ruleset_monitor.py --list-exclusions
sudo ruleset_monitor.py --list-exclusions --ruleset-id PROD_ID SONDA_ID
sudo ruleset_monitor.py --list-exclusions --filter-table CLIENTES
sudo ruleset_monitor.py --list-engine-rulesets
sudo ruleset_monitor.py --list-orphan-exclusions
```

## Operaciones complementarias

Además del flujo inicial, la herramienta permite:

- Consultar las parejas configuradas con `--list-config`.
- Pausar una pareja con `--set-active PROD_ID SONDA_ID NO`.
- Reactivar una pareja con `--set-active PROD_ID SONDA_ID YES`.
- Eliminar una pareja con `--remove-ruleset`.
- Consultar el inventario productivo con `--list-prod`.
- Consultar las exclusiones con `--list-exclusions`.
- Consultar exclusiones huérfanas con `--list-orphan-exclusions`.
- Filtrar exclusiones por Ruleset o tabla.
- Purgar todo el estado local con `--purge`.
- Usar `mock_mode` para pruebas sin conexión con Delphix.

## Eliminar una pareja

```bash
sudo ruleset_monitor.py --remove-ruleset PROD_ID SONDA_ID
```

La baja elimina la configuración local, el inventario productivo y las exclusiones asociadas.

## Purgar el estado local

```bash
sudo ruleset_monitor.py --purge
sudo ruleset_monitor.py --purge -y
```

La base SQLite se crea en `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` en una instalación estándar. Si no existe, el programa crea automáticamente la estructura requerida al iniciarse. Para desarrollo o pruebas puede utilizarse la variable `DELPHIX_RULESET_MONITOR_DATA_DIR`.

## Fallas en el refresh de la sonda

Si el refresh de un Ruleset sonda falla o supera el tiempo de espera, el monitor lo reintenta. Los valores pueden ajustarse en `config.json` (si se omiten, se usan estos):

```json
"refresh_retries": 2,
"refresh_retry_delay_seconds": 60,
"refresh_timeout_seconds": 300
```

Si todos los intentos fallan:

- La pareja se informa como no procesada y la ejecución continúa con las demás. Nunca se compara contra datos desactualizados de la sonda.
- Al final se muestra la tabla de Rulesets no procesados y, si el correo está habilitado, se envía un aviso de auditoría incompleta. El aviso se repite en cada ejecución mientras la falla persista, para que el operador tome acción.
- En `--init-baseline`, la pareja conserva su línea base anterior.
- El proceso termina con código `75`. El servicio systemd declara `SuccessExitStatus=75`, por lo que la unidad no queda en estado `failed`; la falla queda visible en `journalctl` y en el correo.

Los errores generales, como una configuración inexistente o una autenticación fallida contra Delphix, terminan con código `1` y sí dejan la unidad en estado `failed`.

## Ejecución automática con systemd

```bash
systemctl status delphix-ruleset-monitor.timer
systemctl list-timers delphix-ruleset-monitor.timer
journalctl -u delphix-ruleset-monitor.service
```

El servicio ejecuta `ruleset_monitor.py --audit` como una tarea `oneshot`.

También puede ejecutarse desde cron como `root`, utilizando rutas absolutas:

```cron
0 8 * * 1-5 /usr/local/bin/ruleset_monitor.py --audit >> /var/log/delphix-ruleset-monitor-cron.log 2>&1
```

No depende del directorio de trabajo ni del directorio personal del usuario.

## Modo de prueba

Para ejecutar la aplicación sin conectarse a Delphix:

```json
"mock_mode": true
```

El modo mock genera Rulesets, tablas y campos de ejemplo. Sirve para revisar la salida del CLI y el flujo general, pero no valida la configuración real del Engine.

## Recomendación ante una alerta

1. Revisar la tabla y el campo informado en la base de datos origen.
2. Confirmar si el cambio es esperado.
3. Si requiere protección, actualizar el Ruleset productivo y asignar el algoritmo correspondiente.
4. Si el cambio es intencional y no requiere enmascaramiento, reconstruir la línea base.
5. Ejecutar nuevamente la auditoría.

## Consideraciones de seguridad

- Las credenciales están cifradas con age, pero la identidad (`age.key`) reside en el mismo servidor; root puede descifrarlas.
- Se debe proteger y respaldar por separado `/etc/delphix-ruleset-monitor/age.key`.
- El cliente desactiva la validación de certificados TLS de Delphix.
- El servicio systemd suministrado se ejecuta como `root`.
- Se debe proteger `/etc/delphix-ruleset-monitor/config.json` y revisar los destinatarios antes de habilitar el correo.

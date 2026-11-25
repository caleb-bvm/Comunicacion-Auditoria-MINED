# Servidor de pruebas en Windows

Esta guía instala SIGA-MINEDUCYT en una computadora con Windows 10 u 11 para que el
equipo de auditoría lo pruebe desde la red local, antes del despliegue definitivo
en los servidores Linux del Ministerio (`docs/initial-deployment.md`).

Usa la misma configuración de producción que Linux: HTTPS, antivirus obligatorio,
PostgreSQL, correo real y archivos privados fuera de la carpeta pública. Cambian el
servidor web (IIS en lugar de Nginx), el servidor de la aplicación (Waitress en
lugar de Gunicorn) y el certificado, que lo genera el instalador para la red local.

## Antes de empezar

- Windows 10 u 11 de 64 bits con una cuenta de administrador.
- Internet durante la instalación (descarga unos 600 MB entre programas y firmas
  del antivirus).
- Al menos 8 GB de RAM: ClamAV ocupa cerca de 1,5 GB con las firmas cargadas.
- Una cuenta de correo para enviar invitaciones. Con Gmail, active la verificación
  en dos pasos y cree una contraseña de aplicación.
- La carpeta del proyecto copiada al equipo (por USB, ZIP o `git clone`).

No hace falta instalar nada a mano: el instalador descarga Python 3.12,
PostgreSQL 16, ClamAV, IIS, URL Rewrite y Application Request Routing con `winget`.

## Instalación

1. Haga doble clic en `instalar-servidor.cmd` y acepte el aviso de permisos.
2. Responda en la consola:
   - **Dirección de acceso**: la IP del equipo que detecta el instalador o el
     nombre del equipo.
   - **Red privada**: si Windows marcó la red como pública, el instalador ofrece
     cambiarla; sin eso, los demás equipos no podrán conectarse.
   - **Correo saliente**: servidor, puerto, usuario, contraseña y remitente. El
     instalador prueba la conexión antes de guardarlos.
   - **Cuenta de administración técnica**: usuario, nombre, correo y contraseña.
     Desde esa cuenta se crean las de la Dirección y los auditores
     (`/tecnica/usuarios/nuevo/`).
   - **Energía**: evitar que el equipo se suspenda conectado a la corriente.
3. Al terminar, la consola muestra la dirección (por ejemplo
   `https://192.168.1.20`) y la ubicación del certificado.

Si Windows pide reiniciar para habilitar IIS, reinicie y vuelva a ejecutar
`instalar-servidor.cmd`: retoma donde quedó.

## Instalar el certificado en los equipos de prueba

El instalador crea una autoridad de certificación propia del equipo y deja su
certificado en `C:\ProgramData\SIGA-MINEDUCYT\certificado\SIGA-MINEDUCYT-certificado.cer`,
con una copia en el escritorio público. Sin instalarlo, los navegadores muestran
una advertencia de seguridad.

- **Windows**: doble clic en el archivo › *Instalar certificado* › *Equipo local*
  › *Colocar todos los certificados en el siguiente almacén* › *Entidades de
  certificación raíz de confianza*. Reinicie el navegador.
- **Android**: copie el archivo al teléfono › *Ajustes* › *Seguridad* › *Cifrado
  y credenciales* › *Instalar un certificado* › *Certificado de CA*.

Si la IP cambia y se vuelve a ejecutar el instalador, se genera un certificado de
servidor nuevo firmado por la misma autoridad, así que no hay que reinstalarlo.

## Qué queda instalado

| Elemento | Ubicación |
| --- | --- |
| Aplicación y entorno de Python | `C:\Program Files\SIGA-MINEDUCYT` |
| Configuración y secretos (`production.env`) | `C:\ProgramData\SIGA-MINEDUCYT` (solo administradores) |
| Documentos privados | `C:\ProgramData\SIGA-MINEDUCYT\private` |
| Registros | `C:\ProgramData\SIGA-MINEDUCYT\logs` |
| Respaldos de PostgreSQL | `C:\ProgramData\SIGA-MINEDUCYT\backups` |
| Contraseña del usuario `postgres` | `C:\ProgramData\SIGA-MINEDUCYT\secretos` |

Tareas programadas (Programador de tareas):

| Tarea | Cuándo | Qué hace |
| --- | --- | --- |
| `SIGA-MINEDUCYT` | Al iniciar Windows | Espera a PostgreSQL y ClamAV, ejecuta `deployment_preflight` y levanta Waitress en `127.0.0.1:8000`. Si Waitress se detiene, lo reinicia. |
| `SIGA-MINEDUCYT-VENCIMIENTOS` | Diario, 02:00 | `process_overdue_recommendations` |
| `SIGA-MINEDUCYT-VERIFICAR-ARCHIVOS` | Domingos, 03:00 | `verify_private_storage --checksums` |
| `SIGA-MINEDUCYT-RESPALDO` | Diario, 01:30 | `pg_dump` verificado con 14 días de retención |

IIS atiende los puertos 80 y 443, redirige HTTP a HTTPS, sirve `/static/` y
reenvía lo demás a Waitress. El firewall abre 80 y 443 solo para la red local; el
puerto de Waitress no se expone. El instalador elimina el sitio de ejemplo
*Default Web Site* de IIS.

Los respaldos quedan en el mismo disco. Copie con regularidad `backups` y
`private` a un disco externo si los datos de prueba importan.

## Actualizar

Copie la versión nueva del proyecto y vuelva a ejecutar `instalar-servidor.cmd`.
No vuelve a preguntar lo ya configurado: detiene SIGA, copia los archivos, instala
los paquetes nuevos, respalda la base, migra y vuelve a iniciar. Para cambiar la
dirección o el correo, ejecute en PowerShell como administrador:

```powershell
& ".\deploy\windows\instalar-servidor.ps1" -Reconfigurar
```

## Comandos de administración

`siga.ps1` ejecuta `manage.py` con la configuración instalada, como el comando
`siga` de la guía de Linux. Úselo en PowerShell como administrador:

```powershell
& "C:\Program Files\SIGA-MINEDUCYT\deploy\windows\siga.ps1" deployment_preflight
```

```powershell
& "C:\Program Files\SIGA-MINEDUCYT\deploy\windows\siga.ps1" import_center_emails "C:\carga\Listado_Cuentas_Correo_CE.xlsx" --dry-run
```

## Si algo falla

- La consola indica el paso que falló; el registro completo queda en
  `C:\ProgramData\SIGA-MINEDUCYT\logs\instalacion-*.log`. Corrija el problema y
  vuelva a ejecutar el instalador.
- SIGA no abre después de reiniciar el equipo: revise `logs\web.log`. Lo habitual
  es que ClamAV aún esté cargando las firmas; la tarea lo espera hasta 15 minutos.
- Los demás equipos no conectan: confirme que la red sea privada, que estén en la
  misma red y que usen la dirección que mostró el instalador.
- Reserve la IP del equipo en el router para que la dirección no cambie.

# Aplicación Android de SIGA-MINEDUCYT

Contenedor nativo (WebView) que abre el sitio de producción. No duplica lógica ni datos:
la autorización, el análisis antivirus y la bitácora siguen ocurriendo en el servidor.

- Solo navega dentro del dominio configurado (`sigaBaseUrl` en `gradle.properties`); los demás enlaces se abren en el navegador.
- Solo HTTPS; sin contenido mixto, sin acceso a archivos locales y sin copias de seguridad de la sesión.
- Las evidencias se adjuntan con el selector de archivos del teléfono.
- Las descargas pasan por `DownloadManager` con la cookie de sesión y quedan en *Descargas*.
- Sin conexión muestra una pantalla con «Reintentar».

## Compilar (PowerShell)

Requiere Android Studio (su JDK y el SDK en `%LOCALAPPDATA%\Android\Sdk`).

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat assembleDebug                                  # app\build\outputs\apk\debug\app-debug.apk
.\gradlew.bat assembleRelease -PsigaBaseUrl=https://dominio  # otro dominio, sin editar archivos
```

## Firma para distribución

La APK de depuración sirve para pruebas. Para distribuirla se necesita una llave propia del Ministerio,
que **no se versiona** (`*.jks` y `keystore.properties` están en `.gitignore`) y debe respaldarse:
sin ella no se pueden publicar actualizaciones.

```powershell
& "$env:JAVA_HOME\bin\keytool.exe" -genkeypair -v -keystore siga-release.jks -alias siga -keyalg RSA -keysize 4096 -validity 10000
```

Luego crear `android/keystore.properties`:

```
storeFile=siga-release.jks
storePassword=...
keyAlias=siga
keyPassword=...
```

`.\gradlew.bat assembleRelease` genera entonces `app\build\outputs\apk\release\app-release.apk` firmada.
Antes de cada versión nueva, subir `versionCode` y `versionName` en `app/build.gradle`.

#!/usr/bin/env bash
# Genera versiones .gz de los estáticos para que Nginx las sirva con gzip_static.
# Uso: compress-static.sh DIRECTORIO_STATICFILES
# gzip conserva la fecha del original, así que solo se regeneran los archivos
# nuevos o modificados desde la última ejecución.
set -Eeuo pipefail

[[ $# -eq 1 && -d "$1" ]] || { echo "Uso: $0 DIRECTORIO_STATICFILES" >&2; exit 2; }

compressed=0
while IFS= read -r -d '' file; do
    if [[ ! -e "$file.gz" || "$file" -nt "$file.gz" ]]; then
        gzip -9 --keep --force --no-name "$file"
        compressed=$((compressed + 1))
    fi
done < <(find "$1" -type f -size +1k \
    \( -name '*.css' -o -name '*.js' -o -name '*.svg' -o -name '*.json' -o -name '*.map' \) -print0)
echo "Estáticos comprimidos: $compressed"

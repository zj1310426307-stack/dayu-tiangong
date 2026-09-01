#!/bin/sh
set -eu

case_file="${1:-case.xcas}"
case "$case_file" in
  *[!A-Za-z0-9_.-]*|"")
    echo "invalid MASCARET case basename" >&2
    exit 64
    ;;
esac

for resource in Abaques.txt Controle.txt dico_Courlis.txt mascaret-1.0.dtd; do
  cp "/opt/mascaret/data/$resource" "/work/$resource"
done
printf "'%s'\n" "$case_file" > /work/FichierCas.txt

exec /opt/mascaret/bin/mascaret

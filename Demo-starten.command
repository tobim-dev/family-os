#!/bin/zsh
cd -- "${0:A:h}" || exit 1
task_python="../../work/venv/bin/python"
if [[ ! -x "$task_python" ]]; then
  print "Die vorbereitete Python-Umgebung fehlt. Bitte die Anleitung verwenden."
  read "?Enter zum Schließen."
  exit 1
fi
export FOS_DEMO=1
export FOS_DB="${PWD}/../../work/family-os-demo/demo.sqlite"
export FOS_ORIGIN="http://127.0.0.1:8765"
print "Vorschau: http://127.0.0.1:8765 · Beenden mit Ctrl+C"
"$task_python" -m uvicorn app:create_app --factory --host 127.0.0.1 --port 8765
read "?Enter zum Schließen."

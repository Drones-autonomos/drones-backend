#!/bin/bash
# Activa el entorno virtual
source venv/bin/activate

# Coordenadas UAQ Campus Juriquilla (mismas que run_sitl.sh)
UAQ_LAT="20.70428"
UAQ_LON="-100.44358"

echo "Iniciando MAVProxy con mapa centrado en UAQ Juriquilla..."

# --master     : puerto TCP donde escucha el SITL
# --out        : reenvía telemetría por UDP al backend (puerto 14550)
# --map        : abre el mapa interactivo
# --console    : abre consola de estado del dron
# --cmd        : comandos que se ejecutan automáticamente al conectar:
#               - 'map zoom 16'         fuerza zoom sobre el vehículo
#               - 'map center lat lon'  centra el mapa en UAQ
mavproxy.py \
    --master tcp:127.0.0.1:5760 \
    --out udp:127.0.0.1:14550 \
    --map \
    --console \
    --cmd="map zoom 16; map center $UAQ_LAT $UAQ_LON"

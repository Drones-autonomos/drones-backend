#!/bin/bash
# Activa el entorno virtual
source venv/bin/activate

# Coordenadas de la Facultad de Informática UAQ (Campus Juriquilla)
# Latitud, Longitud, Altitud (metros sobre el nivel del mar), Orientación (grados)
HOME_LOCATION="20.70428,-100.44358,1900,0"

echo "Iniciando simulador en Facultad de Informática UAQ, Juriquilla..."
dronekit-sitl copter --home=$HOME_LOCATION --wipe

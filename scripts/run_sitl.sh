#!/bin/bash
# Activa el entorno virtual
source venv/bin/activate

# Coordenadas UAQ Campus Juriquilla, Querétaro
# Formato: lat,lon,altitud_msnm,heading
HOME_LOCATION="20.70428,-100.44358,1800,353"

echo "Iniciando simulador en Facultad de Informática UAQ, Juriquilla..."

# Forzamos el locale a C para que el simulador (C++) entienda el punto decimal
export LC_ALL=C

# Ejecutamos el binario ArduPilot SITL directamente (sin el wrapper Python de dronekit-sitl)
# --wipe  : borra EEPROM para evitar coordenadas cacheadas de sesiones anteriores
# --model : tipo de aeronave simulada
~/.dronekit/sitl/copter-3.3/apm \
    --home=$HOME_LOCATION \
    --model=quad \
    --wipe \
    -I0

# Entorno de Simulación SITL (Software In The Loop)

Para el desarrollo y pruebas de las misiones autónomas del dron sin requerir hardware físico, utilizamos **ArduPilot SITL** en conjunto con **MAVProxy** y `dronekit`.

## Prerrequisitos

Asegúrate de tener instalado Python en tu sistema y **siempre usar un entorno virtual activo** para evitar conflictos con los paquetes del sistema.

### En Ubuntu / Debian / MacOS
```bash
python -m venv venv
source venv/bin/activate
pip install future dronekit-sitl mavproxy
```

### En Arch Linux (Específico)
En Arch Linux, `pip` está bloqueado globalmente por defecto (PEP 668). Debes hacerlo estrictamente dentro de un entorno virtual. Además, si quieres que la consola gráfica de MAVProxy funcione (mapa, gráficos), es recomendable instalar `python-wxpython` y `python-matplotlib` desde los repositorios del sistema.

```bash
# 1. Instalar dependencias del sistema (opcional pero recomendado para MAVProxy)
sudo pacman -S python python-pip tk python-wxpython python-matplotlib opencv

# 2. Crear entorno virtual heredando paquetes del sistema (para poder usar matplotlib/opencv)
python -m venv --system-site-packages venv
source venv/bin/activate

# 3. Instalar los binarios de simulación en el entorno virtual
pip install future dronekit-sitl mavproxy
```

## Ejecución del Entorno

Necesitas **dos terminales** simultáneas.

### Terminal 1 — Iniciar el Simulador SITL

```bash
./run_sitl.sh
```

Este script ejecuta el binario ArduPilot SITL directamente en las coordenadas del Campus Juriquilla UAQ (`20.70428, -100.44358`). Espera hasta ver la línea:

```
Waiting for connection ....
```

> **Nota técnica:** El script usa el binario `~/.dronekit/sitl/copter-3.3/apm` directamente en lugar del wrapper `dronekit-sitl`, porque el wrapper tiene un bug conocido donde redirige el `--home` al simulador pysim legado sin pasarlo al binario ArduPilot real, resultando en que el SITL ignora las coordenadas configuradas y usa su default hardcodeado (Canberra, Australia).

### Terminal 2 — Iniciar MAVProxy con Mapa

```bash
./run_mavproxy.sh
```

Este script lanza MAVProxy con:
- Ruteado de telemetría al backend en `udp:127.0.0.1:14550`
- Mapa interactivo **centrado automáticamente en UAQ Juriquilla**
- Consola de estado del dron

> **Nota sobre el mapa:** MAVProxy por default abre el mapa centrado en Canberra, Australia (la ubicación de pruebas de ArduPilot). El script `run_mavproxy.sh` usa `--cmd="map zoom 16; map center 20.70428 -100.44358"` para forzar el mapa a Juriquilla al arrancar.

### Terminal 3 (Opcional) — Probar la Conexión

Una vez que ambas herramientas estén corriendo:

```bash
source venv/bin/activate
python scripts/drone_backend.py
```

*(Nota técnica: ArduCopter 3.3 simulado por SITL tiene incompatibilidades al aceptar `MAV_CMD_DO_SET_MODE` desde DroneKit, por lo que internamente los scripts utilizan `set_mode_send` en raw MAVLink).*

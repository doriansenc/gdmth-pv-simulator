# Brief del proyecto: Simulador Fotovoltaico GDMTH

## Objetivo

Desarrollar una herramienta computacional funcional en Streamlit que actúe como motor de generación para un análisis fotovoltaico bajo esquema GDMTH. La app debe entregar series quinceminutales de irradiancia POA, generación eléctrica y variables energéticas para evaluar autoconsumo y ahorro económico.

## Requerimientos del reto

### 1. Perfil de demanda

La demanda se genera mediante modelado sintético parametrizable. El usuario define:

- Demanda máxima: 30, 50 o 60 kW.
- Factor de planta: 0.50 a 0.70.
- Factor de potencia: 0.70 a 0.95.
- Reducción de fines de semana.
- Incremento de verano.

El modelo diferencia día laboral, noche, verano, no verano y fines de semana. La ubicación no determina automáticamente la demanda; la ubicación se usa para el recurso solar.

### 2. Motor solar y pvlib

La simulación utiliza `pvlib` para:

- Posición solar.
- Cielo despejado con modelo Ineichen.
- Transposición POA con `pvlib.irradiance.get_total_irradiance`.
- Integración con datos externos mediante `pvlib.iotools`.

### 3. Relación con Jensen et al.

El paper de Jensen et al. se enfoca en `pvlib.iotools`, un conjunto de funciones para leer archivos locales y recuperar datos externos de irradiancia de forma estandarizada. Por ello, el proyecto interpreta “Jensen” como un flujo de trabajo basado en `pvlib.iotools` y no como una ecuación física única de transposición.

## Fuentes de irradiancia

La app permite seis modos:

1. Cielo despejado con pvlib Ineichen.
2. Escenario climático simple.
3. PVGIS con `pvlib.iotools`.
4. NSRDB PSM3 con `pvlib.iotools`.
5. NASA POWER.
6. CSV propio.

## Variables de entrada

### Ubicación

- Latitud.
- Longitud.
- Altitud.
- Zona horaria.

### Sistema fotovoltaico

- Potencia del panel.
- Área del panel.
- Eficiencia.
- Número de paneles.
- Pérdidas del sistema.
- Albedo.

### Geometría

- Tilt.
- Azimuth.

### Demanda

- Demanda máxima.
- Factor de planta.
- Factor de potencia.
- Estacionalidad.

## Salidas

- GHI, DNI y DHI.
- POA global.
- POA directa, difusa, de cielo y reflejada por suelo.
- Generación eléctrica cada 15 minutos.
- Energía anual generada.
- Demanda anual.
- Autoconsumo.
- Energía exportada.
- Energía tomada de red.
- Estimación de costo sin PV, con PV y ahorro.
- Comparación de escenarios.
- Exportación en CSV, Excel y PDF.

## Estructura técnica

- `app.py`: interfaz principal de Streamlit.
- `src/solar_engine.py`: motor solar, posición solar, POA y generación.
- `src/irradiance_data.py`: carga de PVGIS, NSRDB, NASA POWER y CSV.
- `src/demand_engine.py`: perfil de demanda industrial.
- `src/tariff_engine.py`: estimación tarifaria GDMTH.
- `src/scenario_engine.py`: comparación de configuraciones.
- `src/plotting.py`: gráficas de análisis.
- `src/exporting.py`: exportación CSV, Excel y PDF.

## Alcance

La versión actual es un MVP académico funcional. Para una implementación industrial se recomienda validar con datos reales de demanda, tarifa oficial actualizada, mediciones de irradiancia locales o datasets satelitales seleccionados por región.

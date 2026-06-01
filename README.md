# Simulador Fotovoltaico GDMTH con pvlib y pvlib.iotools

Aplicación en Streamlit para simular una instalación fotovoltaica bajo los requerimientos del reto GDMTH. La herramienta permite seleccionar ubicación en un mapa, configurar el arreglo fotovoltaico, obtener o modelar irradiancia, calcular irradiancia POA, estimar generación eléctrica quinceminutal, cruzarla con demanda industrial y exportar resultados.

## Enfoque del modelo

Esta versión separa claramente tres partes:

1. **Recurso solar:** depende de ubicación, fecha, fuente de irradiancia y geometría solar.
2. **Sistema fotovoltaico:** convierte irradiancia POA a potencia usando como base la potencia nominal instalada, temperatura de celda y pérdidas. El área y la eficiencia del panel se conservan como validación física/informativa, no como la base principal de generación.
3. **Demanda industrial:** no se infiere de la ubicación. Se genera como un escenario de carga parametrizable a partir de demanda máxima, factor de planta, factor de potencia, horario operativo, verano y fines de semana.

La fórmula principal de generación es:

```text
P_instalada_kWp = number_of_panels * panel_power_w / 1000

generation_kW =
    P_instalada_kWp
    * (POA_W_m2 / 1000)
    * temperature_factor
    * (1 - system_losses)
```

La consistencia física del panel se revisa con:

```text
estimated_panel_power_w = panel_area_m2 * panel_efficiency * 1000
```

Si esta potencia estimada difiere mucho de `panel_power_w`, la app conserva una advertencia interna y sigue usando la potencia nominal declarada.

## Relación con Jensen et al. y pvlib.iotools

El paper proporcionado para el proyecto, *pvlib iotools—Open-source Python functions for seamless access to solar irradiance data* de Jensen et al. (2023), no presenta una sola ecuación de transposición llamada “modelo de Jensen”. Su aportación principal es el uso de `pvlib.iotools` para acceder de forma estandarizada a datos de irradiancia solar provenientes de archivos locales o proveedores externos.

Por eso, esta app implementa el flujo más correcto para el reto:

```text
Ubicación + periodo de simulación
        ↓
Datos de irradiancia: cielo despejado, escenario climático, PVGIS, NSRDB, NASA POWER o CSV
        ↓
Posición solar con pvlib.solarposition.get_solarposition
        ↓
Transposición POA con pvlib.irradiance.get_total_irradiance
        ↓
Generación fotovoltaica cada 15 minutos
        ↓
Cruce con demanda industrial y estimación GDMTH
```

## Fuentes de irradiancia disponibles

La interfaz separa las fuentes en dos niveles para mantener claro el flujo de entrega.

### Fuentes principales del MVP

1. **Cielo despejado con pvlib Ineichen**  
   Usa `pvlib.location.Location.get_clearsky(model="ineichen")`. Representa un escenario ideal sin nubosidad.

2. **Escenario climático simple**  
   Parte del cielo despejado y aplica un factor de reducción para representar condiciones como parcialmente nublado, nublado o lluvia.

3. **CSV propio**  
   Permite cargar datos externos proporcionados por el profesor, una estación meteorológica o una base descargada manualmente.

### Fuentes solares externas avanzadas

1. **PVGIS con pvlib.iotools**  
   Usa `pvlib.iotools.get_pvgis_hourly`. Es útil porque normalmente no requiere API key.

2. **NASA POWER**  
   Fuente alternativa sin API key. Se conserva como respaldo para escenarios reales aproximados.

3. **NSRDB PSM3 con pvlib.iotools / API NSRDB**  
   Usa `pvlib.iotools.get_psm3` cuando la versión instalada de pvlib lo incluye; si no existe, usa directamente el endpoint CSV de NSRDB PSM3. Requiere API key y correo registrado.

PVGIS, NASA POWER y NSRDB se cargan bajo demanda con el botón **Cargar datos solares externos** dentro del bloque avanzado. Si se selecciona una fuente externa pero todavía no se han cargado datos para la configuración actual, la simulación usa temporalmente cielo despejado con pvlib Ineichen para evitar bloqueos o esperas innecesarias.

## Columnas esperadas para CSV propio

Mínimas:

```text
datetime, ghi
```

Recomendadas:

```text
datetime, ghi, dni, dhi, temp_air, wind_speed
```

La app también reconoce nombres equivalentes como `GHI`, `DNI`, `DHI`, `temp_air`, `wind_speed`, `GHI_W_m2`, `DNI_W_m2` y `DHI_W_m2`.

## Demanda real por archivo

Además de la demanda sintética validada, la app permite cargar demanda real desde CSV o Excel.

Columnas mínimas:

```text
datetime, demand_kW
```

Columnas opcionales:

```text
demand_energy_kWh, power_factor
```

Si falta `demand_energy_kWh`, se calcula como `demand_kW * 0.25`. Si falta `power_factor`, se usa el factor de potencia configurado en la interfaz. La demanda cargada se valida, se ajusta a resolución de 15 minutos y alimenta el mismo balance energético y tarifario que la demanda sintética.

## Funciones incluidas

- Mapa interactivo con Google Maps JavaScript API para selección de ubicación.
- Búsqueda con Google Places Autocomplete, click en mapa y altitud automática con Elevation API.
- Simulación anual en intervalos de 15 minutos.
- Cálculo de posición solar con `pvlib`.
- Cálculo de GHI, DNI, DHI y POA.
- Modo ideal, modo climático, modo con `pvlib.iotools`, modo NASA POWER y modo CSV.
- Perfil sintético de demanda industrial.
- Demanda real por archivo CSV o Excel.
- Diferenciación de verano, no verano y fines de semana.
- Módulo tarifario GDMTH configurable.
- Exportación de resultados en CSV, Excel y PDF.
- Interfaz sin emojis y con estilo técnico.

## Instalación

En Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

En macOS o Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Variables opcionales

Para activar el mapa con Google Maps, búsqueda autocomplete, elevación automática y zona horaria automática, el desarrollador debe configurar una API key de Google Maps Platform como variable de entorno o secreto de Streamlit:

```text
GOOGLE_MAPS_API_KEY=tu_api_key
```

El usuario final no introduce esta llave en la interfaz. Si `GOOGLE_MAPS_API_KEY` no está configurada, la app sigue funcionando con latitud, longitud, altitud y zona horaria manuales.

En Google Cloud deben estar habilitadas al menos estas APIs:

```text
Maps JavaScript API
Places API
Elevation API
Time Zone API
```

Para usar NSRDB PSM3 se puede escribir la API key directamente en la app cuando la fuente solar seleccionada es NSRDB, o guardarla como variable de entorno:

```text
NSRDB_API_KEY=tu_api_key
NSRDB_EMAIL=tu_correo
```

Las fuentes externas se descargan solo cuando el usuario presiona **Cargar datos solares externos**. Si faltan credenciales de NSRDB o los datos cargados no coinciden con ubicación, año, zona horaria o configuración actual, la app usa cielo despejado temporalmente y muestra un aviso.

## Estructura del repositorio

```text
gdmth-pv-streamlit/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── .streamlit/
│   └── config.toml
├── assets/
│   └── styles.css
├── docs/
│   └── 00-project-brief.md
├── src/
│   ├── __init__.py
│   ├── demand_engine.py
│   ├── exporting.py
│   ├── irradiance_data.py
│   ├── plotting.py
│   ├── scenario_engine.py
│   ├── solar_engine.py
│   ├── summary.py
│   ├── tariff_engine.py
│   └── ui_components.py
├── tests/
│   └── test_engines.py
└── pyproject.toml
```

## Nota de alcance

La app es un MVP académico funcional. El cálculo GDMTH es una estimación configurable y no sustituye una facturación oficial de CFE. La demanda puede ser sintética o cargada desde archivo real. La comparación automática de escenarios queda como funcionalidad futura y no está activa en la interfaz actual.

# CONTEXT PROJECT — Motor FV GDMTH

**Proyecto:** Reto GDMTH: Ingeniería y Viabilidad Fotovoltaica  
**Nombre de la app:** Motor FV GDMTH  
**Fecha de actualización:** 2026-05-26  
**Uso previsto:** Entregar este archivo a Codex junto con el archivo `CONTEXT_DESIGN_MOTOR_PV_GDMTH_CODEX.md` y el ZIP de Stitch `stitch_vibrant_modern_design.zip`.

---

## 1. Resumen del proyecto

Se está desarrollando una herramienta web para simular la viabilidad técnica de un sistema fotovoltaico industrial dentro del contexto del **Reto GDMTH: Ingeniería y Viabilidad Fotovoltaica**.

La herramienta no debe ser un dashboard de monitoreo en tiempo real de paneles ya instalados. Debe ser un **motor de simulación fotovoltaica** que permita configurar un sitio, definir la geometría del arreglo, seleccionar o editar un sistema fotovoltaico, ejecutar una simulación y analizar los resultados.

El objetivo técnico del motor es producir resultados de irradiancia, generación eléctrica y escenarios de diseño para un sistema FV industrial. Los resultados deben quedar listos para integrarse posteriormente a un análisis económico bajo tarifa GDMTH.

---

## 2. Objetivo técnico del motor

Dado un conjunto de parámetros geográficos, geométricos y técnicos, el motor debe calcular:

1. Posición solar.
2. Irradiancia en plano horizontal:
   - GHI
   - DNI
   - DHI
3. Irradiancia sobre el plano del arreglo:
   - POA
4. Potencia fotovoltaica generada.
5. Energía generada por intervalo.
6. Resúmenes horarios, mensuales y anuales.
7. Comparación contra perfil de demanda industrial.
8. Escenarios de variación por inclinación, azimut, eficiencia o cantidad de paneles.
9. Exportación de resultados para análisis posterior GDMTH.

La simulación debe trabajar con intervalos **quinceminutales**:

```text
1 año = 8,760 h
4 intervalos por hora
N = 35,040 puntos/año
```

---

## 3. Alcance actual

### Incluido en esta etapa

- Frontend visual en React.
- Interfaz completamente en español.
- Diseño oscuro premium con estética técnica.
- Configuración de ubicación mediante búsqueda y mapa.
- Configuración de geometría del panel.
- Configuración del sistema fotovoltaico.
- Configuración de simulación.
- Resultados por pestañas:
  - Irradiancia
  - Generación
  - Demanda vs Solar
  - Escenarios
  - Exportar
- Uso inicial de datos mock para construir el frontend.
- Preparación de arquitectura para conectar después con backend FastAPI.
- Exportación planeada a Excel/CSV.

### No incluido todavía

- No implementar cálculo económico GDMTH completo en la primera iteración.
- No depender todavía del Excel GDMTH como fuente principal.
- No crear un dashboard de monitoreo tipo “panel activo/inactivo”.
- No simular datos en tiempo real.
- No llamar a la app “Solar Monitoring”.

---

## 4. Stack tecnológico objetivo

### Frontend

- React 18
- Vite
- Tailwind CSS
- JavaScript con componentes funcionales
- Context API + `useReducer` para estado global
- Recharts para gráficas estándar
- SVG custom para heatmaps y diagramas polares cuando convenga
- React Leaflet + Leaflet para mapa
- SheetJS (`xlsx`) para exportación de archivos Excel
- `lucide-react` o iconografía similar para UI
- Fetch nativo para comunicación HTTP

### Backend previsto

- Python
- FastAPI
- Pydantic v2
- pvlib
- pandas
- numpy
- requests
- openpyxl
- timezonefinder
- uvicorn

### Comunicación

- React en puerto local de desarrollo, normalmente `http://localhost:5173`.
- FastAPI en `http://localhost:8000`.
- API REST JSON.
- CORS habilitado en backend.
- El frontend debe estar preparado para llamar a endpoints, aunque inicialmente trabaje con mock data.

---

## 5. Arquitectura objetivo del repositorio

```text
motor-pv-gdmth/
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── index.css
│       ├── context/
│       │   └── SimContext.jsx
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.jsx
│       │   │   └── Topbar.jsx
│       │   ├── inputs/
│       │   │   ├── LocationPanel.jsx
│       │   │   ├── GeometryPanel.jsx
│       │   │   ├── SystemPanel.jsx
│       │   │   └── SimConfigPanel.jsx
│       │   ├── kpis/
│       │   │   └── KpiCards.jsx
│       │   ├── tabs/
│       │   │   ├── IrradianceTab.jsx
│       │   │   ├── GenerationTab.jsx
│       │   │   ├── DemandTab.jsx
│       │   │   ├── ScenariosTab.jsx
│       │   │   └── ExportTab.jsx
│       │   ├── charts/
│       │   │   ├── MonthlyIrradianceChart.jsx
│       │   │   ├── SolarPathChart.jsx
│       │   │   ├── POAHeatmap.jsx
│       │   │   ├── GenerationCharts.jsx
│       │   │   ├── DemandCharts.jsx
│       │   │   └── ScenarioHeatmap.jsx
│       │   └── ui/
│       │       ├── Card.jsx
│       │       ├── Button.jsx
│       │       ├── Tabs.jsx
│       │       ├── MetricCard.jsx
│       │       ├── SectionHeader.jsx
│       │       └── StatusState.jsx
│       ├── hooks/
│       │   ├── useSimulation.js
│       │   ├── useGeocoding.js
│       │   └── useExport.js
│       ├── data/
│       │   ├── mockData.js
│       │   └── panels.js
│       └── utils/
│           ├── colors.js
│           ├── formatters.js
│           └── demandProfile.js
│
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── routers/
│   │   ├── simulation.py
│   │   ├── scenarios.py
│   │   ├── geocoding.py
│   │   └── elevation.py
│   ├── services/
│   │   ├── irradiance.py
│   │   ├── transposition.py
│   │   ├── temperature.py
│   │   └── demand.py
│   └── models/
│       └── schemas.py
│
├── design/
│   └── stitch/
│       └── stitch_vibrant_modern_design/
│
├── docs/
│   ├── CONTEXT_PROJECT_MOTOR_PV_GDMTH_CODEX.md
│   └── CONTEXT_DESIGN_MOTOR_PV_GDMTH_CODEX.md
│
└── README.md
```

---

## 6. Estado global sugerido

```javascript
const initialState = {
  location: {
    lat: 25.6866,
    lon: -100.3161,
    alt: 540,
    tz: "America/Monterrey",
    city: "Monterrey, Nuevo León"
  },

  geometry: {
    tilt: 25,
    azimuth: 180,
    mounting: "fixed"
  },

  system: {
    panelId: "Canadian Solar CS6R-410",
    power_wp: 410,
    eta: 0.210,
    area_m2: 1.954,
    n_panels: 120,
    losses: 0.14
  },

  simConfig: {
    year: 2024,
    irrSource: "nasa_power",
    transpModel: "perez",
    demMaxKw: 50,
    demProfile: "industrial_standard",
    tempAmb: 25
  },

  status: "idle",
  error: null,
  results: null,
  scenarios: null,
  monthlyTable: null,

  activeSection: "ubicacion",
  activeTab: "irradiance",
  selectedMonth: 4
};
```

---

## 7. Navegación principal

La app debe tener dos tipos de navegación:

### Navegación de configuración en sidebar

- Ubicación
- Geometría
- Sistema
- Configuración
- Simular

Estas secciones corresponden a la configuración previa del modelo.

### Pestañas de resultados

- Irradiancia
- Generación
- Demanda vs Solar
- Escenarios
- Exportar

Estas pestañas corresponden al análisis de resultados después de ejecutar o cargar una simulación mock.

---

## 8. Idioma y tono

Toda la interfaz debe estar en **español**.

### Reglas

- No mezclar inglés y español.
- Usar español técnico, natural y profesional.
- Público objetivo: usuarios hispanohablantes, estudiantes e ingenieros en México.
- Se permiten siglas técnicas internacionales:
  - POA
  - GHI
  - DNI
  - DHI
  - PR
  - FV
  - GDMTH
  - kW
  - kWh
  - kWh/m²

### Labels preferidos

| Inglés / genérico | Usar en la UI |
|---|---|
| Location | Ubicación |
| Geometry | Geometría |
| System | Sistema |
| Config | Configuración |
| Simulate | Simular |
| Run Simulation | Ejecutar simulación |
| Irradiance | Irradiancia |
| Generation | Generación |
| Demand vs Solar | Demanda vs Solar |
| Scenarios | Escenarios |
| Export | Exportar |
| Annual Energy Yield | Energía anual |
| Peak POA Irradiance | POA máxima |
| Performance Ratio | Índice de desempeño (PR) |
| Optimal Tilt Angle | Inclinación óptima |
| Download Excel | Descargar Excel |
| Download CSV | Descargar CSV |

---

## 9. Parámetros de entrada

### Ubicación

- Ciudad o sitio
- Latitud
- Longitud
- Altitud
- Zona horaria

### Geometría

- Inclinación del panel
- Azimut
- Tipo de montaje:
  - Fijo
  - Seguidor de un eje
  - Seguidor de dos ejes

### Sistema FV

- Panel comercial seleccionado
- Potencia nominal
- Eficiencia
- Área del módulo
- Número de paneles
- Pérdidas del sistema
- Potencia instalada total en kWp

### Simulación

- Año
- Fuente de irradiancia:
  - NASA POWER
  - PVGIS
  - Cielo despejado
- Modelo de transposición:
  - Perez
  - Isotrópico
- Demanda máxima:
  - 30 kW
  - 50 kW
  - 60 kW
- Perfil de demanda:
  - Industrial estándar

---

## 10. Fórmulas centrales del motor

### Potencia FV

```text
P_FV = POA × A_panel × η_panel
```

En kW:

```text
P_FV,kW = (POA × A_panel × η_panel × N_paneles × (1 - pérdidas)) / 1000
```

### Energía por intervalo

```text
E_i = P_i × 0.25 h
```

### Energía anual

```text
E_anual = Σ E_i
```

### Demanda neta

```text
Demanda_neta = max(Demanda_original - Generación_FV, 0)
```

### Autoconsumo y excedente

```text
Autoconsumo = min(Generación_FV, Demanda_original)
Excedente = max(Generación_FV - Demanda_original, 0)
```

---

## 11. Datos mock mínimos para frontend

Mientras no esté conectado el backend, el frontend debe funcionar con mock data. Debe incluir:

- `meta`
  - energia_anual_kwh
  - energia_anual_kwh_kwp
  - poa_max_wm2
  - pot_max_kw
  - pr_pct
  - factor_planta_pct
  - inclinacion_optima
  - azimut_optimo
  - autoconsumo_kwh
  - excedente_kwh
- `monthly`
  - mes
  - ghi_kwh_m2
  - dni_kwh_m2
  - dhi_kwh_m2
  - poa_kwh_m2
  - energia_kwh
  - demanda_kwh
  - autoconsumo_kwh
  - excedente_kwh
  - pot_pico_kw
- `hourly_avg`
  - hora
  - ghi
  - dni
  - dhi
  - poa
  - pot_kw
  - demanda_kw
  - demanda_neta_kw
- `heatmap`
  - months
  - hours
  - values
- `duration_curve`
  - hours
  - power_kw
- `scenarios`
  - tilt
  - azimuth
  - energia_anual_kwh
  - delta_pct

---

## 12. Endpoints previstos

Estos endpoints pueden implementarse después. En la primera iteración, los hooks pueden regresar mock data.

### POST `/simulate`

Recibe parámetros completos del modelo y devuelve resultados agregados.

### POST `/scenarios`

Recibe rangos de inclinación y azimut. Devuelve matriz o arreglo de escenarios y el óptimo.

### GET `/geocode?q=...`

Busca ciudad o sitio.

### GET `/elevation?lat=&lon=`

Obtiene altitud.

### GET `/timezone?lat=&lon=`

Obtiene zona horaria.

---

## 13. Exportación

La app debe preparar exportaciones para análisis posterior. La exportación puede ser mock o parcial en primera iteración, pero la UI debe existir.

### Hojas sugeridas del Excel

1. `Serie 15min`
   - Timestamp
   - GHI
   - DNI
   - DHI
   - POA
   - Potencia
   - Energía
   - Demanda
   - Demanda Neta
   - Autoconsumo
   - Excedente

2. `Resumen Mensual`
   - Mes
   - GHI
   - POA
   - Energía
   - Demanda
   - Autoconsumo
   - Excedente
   - Potencia pico

3. `Escenarios`
   - Inclinación
   - Azimut
   - Energía anual
   - Delta vs base
   - Óptimo

4. `Parámetros`
   - Ubicación
   - Geometría
   - Sistema
   - Configuración de simulación
   - Métricas principales

---

## 14. Perfil de demanda industrial

El perfil de demanda puede generarse inicialmente en el cliente con JavaScript usando una curva normalizada. Debe ser compatible con intervalos quinceminutales.

Reglas sugeridas:

- 00:00–06:00: carga nocturna baja.
- 06:00–08:00: rampa de arranque.
- 08:00–12:00: aumento de producción.
- 12:00–14:00: pico.
- 14:00–18:00: operación alta.
- 18:00–20:00: reducción gradual.
- 20:00–24:00: operación baja.
- Verano: factor mayor.
- Fines de semana: factor menor.

---

## 15. Principios de desarrollo

1. Primero implementar frontend visual con mock data.
2. Mantener componentes reutilizables.
3. No pegar HTML estático de Stitch como código final.
4. Usar el ZIP de Stitch como referencia visual, no como implementación rígida.
5. Mantener UI en español.
6. Preparar hooks para conectar backend después.
7. Evitar lógica pesada dentro de componentes visuales.
8. Separar datos, estado, componentes y utilidades.
9. Usar nombres claros en español para labels y nombres claros en inglés para archivos/código cuando sea convención de React.
10. La app debe correr con `npm run dev`.

---

## 16. Resultado esperado de la primera iteración de Codex

Primera meta:

- Crear proyecto frontend funcional con Vite.
- Implementar layout principal:
  - Sidebar
  - Topbar
  - Área principal
  - Cards KPI
  - Navegación entre secciones
  - Tabs de resultados
- Implementar pantallas:
  - Ubicación
  - Geometría
  - Sistema
  - Configuración
  - Irradiancia
  - Generación
  - Demanda vs Solar
  - Escenarios
  - Exportar
- Usar mock data.
- Mantener estilo del diseño de Stitch.
- Dejar hooks preparados para backend.
- Documentar cómo correr el frontend.

No se espera que la primera iteración haga el cálculo físico real.

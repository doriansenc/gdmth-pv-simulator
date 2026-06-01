# CONTEXT DESIGN — Motor FV GDMTH

**Proyecto:** Reto GDMTH: Ingeniería y Viabilidad Fotovoltaica  
**App:** Motor FV GDMTH  
**Fecha de actualización:** 2026-05-26  
**Uso previsto:** Entregar este archivo a Codex junto con `CONTEXT_PROJECT_MOTOR_PV_GDMTH_CODEX.md` y el ZIP `stitch_vibrant_modern_design.zip`.

---

## 1. Propósito de este archivo

Este archivo describe cómo debe implementarse el diseño visual de la app a partir de los mockups generados en Stitch.

El ZIP de Stitch contiene varias pantallas HTML estáticas y capturas PNG. Esos archivos deben usarse como **referencia visual** para construir componentes React reutilizables. No se debe simplemente insertar cada HTML como una página estática.

---

## 2. Archivo ZIP de referencia

El usuario entregará a Codex el archivo:

```text
stitch_vibrant_modern_design.zip
```

Este ZIP contiene:

```text
stitch_vibrant_modern_design/
├── ubicaci_n_del_proyecto/
│   ├── code.html
│   └── screen.png
├── geometr_a_del_arreglo/
│   ├── code.html
│   └── screen.png
├── sistema_fotovoltaico/
│   ├── code.html
│   └── screen.png
├── configuraci_n_de_simulaci_n/
│   ├── code.html
│   └── screen.png
├── an_lisis_de_irradiancia/
│   ├── code.html
│   └── screen.png
├── an_lisis_de_generaci_n/
│   ├── code.html
│   └── screen.png
├── demanda_vs_solar/
│   ├── code.html
│   └── screen.png
├── comparaci_n_de_escenarios/
│   ├── code.html
│   └── screen.png
├── exportar_resultados/
│   ├── code.html
│   └── screen.png
└── pro_dark_precision/
    └── DESIGN.md
```

### Cómo usar el ZIP

1. Extraer el ZIP en:

```text
design/stitch/
```

2. Revisar primero `pro_dark_precision/DESIGN.md`.
3. Revisar cada `screen.png` para layout visual.
4. Revisar cada `code.html` para clases, colores, spacing y jerarquía.
5. Convertir el diseño en componentes React reutilizables.
6. No copiar todo como HTML estático final.
7. No duplicar sidebar/topbar en cada página; deben ser componentes globales.

---

## 3. Estilo visual base

El diseño tiene una estética:

- Dark premium.
- Técnica.
- Industrial.
- Limpia.
- Data-focused.
- Parecida a herramientas profesionales de ingeniería energética.
- Con cards redondeadas, bordes sutiles y alto contraste.
- Sin decoraciones innecesarias.
- Sin estilo de landing page.
- Sin apariencia de app de monitoreo de paneles en tiempo real.

---

## 4. Sistema visual extraído de Stitch

El archivo `pro_dark_precision/DESIGN.md` usa esta base:

```yaml
name: Pro Dark Precision
surface: '#11131c'
surface-container-lowest: '#0c0e16'
surface-container-low: '#191b24'
surface-container: '#1d1f28'
surface-container-high: '#282933'
surface-container-highest: '#33343e'
on-surface: '#e2e1ee'
on-surface-variant: '#c3c5d8'
outline: '#8d90a1'
outline-variant: '#434655'
primary: '#b7c4ff'
primary-container: '#3366ff'
secondary: '#ffb77f'
secondary-container: '#ff8a00'
tertiary: '#3ce36a'
error: '#ffb4ab'
background: '#11131c'
```

### Paleta funcional recomendada

```css
:root {
  --bg-main: #11131c;
  --bg-deep: #0c0e16;
  --bg-sidebar: #11131c;
  --bg-card: #1d1f28;
  --bg-card-soft: #282933;
  --border-soft: #434655;

  --text-main: #e2e1ee;
  --text-muted: #c3c5d8;
  --text-soft: #8d90a1;

  --blue-active: #3366ff;
  --blue-soft: #b7c4ff;

  --solar-amber: #ff8a00;
  --solar-soft: #ffb77f;

  --green-positive: #3ce36a;
  --red-error: #ffb4ab;
  --purple-demand: #8b7cff;
}
```

---

## 5. Tipografía

El diseño de Stitch usa:

- `Plus Jakarta Sans` para UI general, títulos y labels.
- `IBM Plex Mono` para números, coordenadas, unidades y valores técnicos.

### Reglas

- Usar Plus Jakarta Sans como fuente principal.
- Usar IBM Plex Mono en métricas, coordenadas, valores y datos.
- Mantener buena legibilidad en fondo oscuro.
- No usar fuentes decorativas.

---

## 6. Layout global

Todas las pantallas deben compartir la misma estructura:

```text
┌─────────────────────────────────────────────────────────────┐
│ Sidebar fija │ Topbar                                      │
│              ├─────────────────────────────────────────────┤
│              │ Contenido principal                          │
│              │                                             │
│              │ KPI cards                                    │
│              │ Tabs / secciones                             │
│              │ Cards, gráficas, tablas, mapa                │
└──────────────┴─────────────────────────────────────────────┘
```

### Sidebar

- Fija a la izquierda.
- Fondo oscuro.
- Branding:
  - Motor FV
  - Tarifa GDMTH
- Navegación:
  - Ubicación
  - Geometría
  - Sistema
  - Configuración
  - Resultados o Simular
- Parte inferior:
  - Soporte
  - Ajustes
  - Botón “Ejecutar simulación”
- El elemento activo debe resaltarse con azul.

### Topbar

Debe incluir:

- Nombre del proyecto: `Motor FV GDMTH`
- Coordenadas seleccionadas.
- Ciudad seleccionada.
- Acciones o íconos secundarios:
  - Notificaciones
  - Ajustes
  - Usuario

---

## 7. Idioma visual

Toda la interfaz debe estar en español:

- Títulos
- Sidebar
- Botones
- Tablas
- Tooltips
- Gráficas
- Tabs
- Estados
- Mensajes de ayuda
- Exportaciones

No usar:

- `Location`
- `Geometry`
- `System`
- `Config`
- `Run Simulation`
- `Export`
- `Generation`

Usar:

- `Ubicación`
- `Geometría`
- `Sistema`
- `Configuración`
- `Ejecutar simulación`
- `Exportar`
- `Generación`

Se permiten siglas:
POA, GHI, DNI, DHI, PR, FV, GDMTH, kW, kWh.

---

## 8. Mapeo de pantallas de Stitch a React

| Carpeta Stitch | Página React objetivo |
|---|---|
| `ubicaci_n_del_proyecto` | `LocationPage.jsx` |
| `geometr_a_del_arreglo` | `GeometryPage.jsx` |
| `sistema_fotovoltaico` | `SystemPage.jsx` |
| `configuraci_n_de_simulaci_n` | `SimulationConfigPage.jsx` |
| `an_lisis_de_irradiancia` | `IrradiancePage.jsx` o `IrradianceTab.jsx` |
| `an_lisis_de_generaci_n` | `GenerationPage.jsx` o `GenerationTab.jsx` |
| `demanda_vs_solar` | `DemandPage.jsx` o `DemandTab.jsx` |
| `comparaci_n_de_escenarios` | `ScenariosPage.jsx` o `ScenariosTab.jsx` |
| `exportar_resultados` | `ExportPage.jsx` o `ExportTab.jsx` |
| `pro_dark_precision/DESIGN.md` | `colors.js`, `index.css`, tokens de diseño |

---

## 9. Pantallas de configuración

### 9.1 Ubicación

Debe incluir:

- Buscador: `Buscar ciudad o sitio`
- Mapa con estilo compatible con Leaflet/OpenStreetMap.
- Marcador de ubicación.
- Campos:
  - Latitud
  - Longitud
  - Altitud
  - Zona horaria
- Card de resumen.
- Botón `Confirmar ubicación`.
- Mensaje de ayuda:
  - “La ubicación define la posición solar y la estimación de irradiancia.”

### 9.2 Geometría

Debe incluir:

- Slider de inclinación.
- Control de azimut.
- Diagrama tipo brújula.
- Selector de montaje:
  - Fijo
  - Seguidor de un eje
  - Seguidor de dos ejes
- Card de explicación técnica:
  - “La inclinación y el azimut modifican la irradiancia POA recibida por el arreglo.”

### 9.3 Sistema fotovoltaico

Debe incluir:

- Selector de panel comercial.
- Tabla de especificaciones:
  - Marca
  - Modelo
  - Potencia nominal
  - Eficiencia
  - Área
  - Tier
- Input de número de paneles.
- Input de pérdidas.
- Capacidad instalada en kWp.
- Área total instalada.

### 9.4 Configuración de simulación

Debe incluir:

- Año.
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
- Perfil de demanda.
- Estado de simulación.
- Botón:
  - `Ejecutar simulación`

---

## 10. Pantallas de resultados

### 10.1 Irradiancia

Debe incluir:

- KPIs:
  - Energía anual
  - POA máxima
  - Índice de desempeño (PR)
  - Inclinación óptima
- Gráfica:
  - Perfil mensual de irradiancia
  - Comparación GHI vs POA
- Diagrama:
  - Trayectoria solar
- Heatmap:
  - Intensidad POA por hora y mes
- Gráfica de composición:
  - GHI, DNI, DHI, reflejada, POA

### 10.2 Generación

Debe incluir:

- Potencia generada en kW.
- Energía mensual en kWh.
- Scatter POA vs potencia generada.
- Curva de duración de potencia.
- KPIs:
  - Generación anual
  - Potencia pico
  - Factor de planta
  - PR

### 10.3 Demanda vs Solar

Debe incluir:

- Línea triple:
  - Demanda original
  - Generación FV
  - Demanda neta
- Donut:
  - Autoconsumo vs excedente
- Balance anual:
  - Demanda total
  - Cubierta por FV
  - Energía de red
- Tabla mensual:
  - Demanda
  - Generación FV
  - Autoconsumo
  - Excedente
  - Energía de red

### 10.4 Escenarios

Debe incluir:

- Heatmap inclinación × azimut.
- Ranking de mejores configuraciones.
- Card del escenario óptimo.
- Comparación caso base vs óptimo.
- Controles:
  - Rango de inclinación
  - Rango de azimut
  - Variación de eficiencia
- Botón:
  - `Ejecutar barrido de escenarios`

### 10.5 Exportar

Debe incluir:

- Tabla de resumen mensual.
- Cards de exportación:
  - Serie temporal 15 min
  - Resumen mensual/anual
  - Comparación de escenarios
  - Parámetros de simulación
- Botones:
  - Descargar Excel
  - Descargar CSV
- Nota:
  - “Los archivos exportados están preparados para integrarse a una evaluación económica GDMTH posterior.”

---

## 11. Componentes UI reutilizables

Codex debe extraer patrones visuales y convertirlos en componentes:

```text
components/ui/
├── Card.jsx
├── Button.jsx
├── MetricCard.jsx
├── Tabs.jsx
├── SectionHeader.jsx
├── InputGroup.jsx
├── SelectField.jsx
├── SliderField.jsx
├── StatusState.jsx
└── DataTable.jsx
```

### Cards

- Fondo: `surface-container`.
- Borde: `outline-variant`.
- Radio: 1rem aproximado.
- Padding consistente.
- Encabezado claro.
- Texto secundario muted.

### Botones

- Primario: azul activo.
- Secundario: fondo transparente con borde.
- Exportación: con ícono de descarga.
- Estado hover visible.

### KPI cards

- Título pequeño en mayúsculas o semibold.
- Valor grande con fuente mono.
- Unidad clara.
- Delta o nota secundaria.
- Icono pequeño.

---

## 12. Gráficas

### Librería recomendada

- Usar Recharts para:
  - Barras.
  - Líneas.
  - Áreas.
  - Scatter.
  - Donut/Pie.

### SVG custom

- Usar SVG propio para:
  - Diagrama polar solar.
  - Heatmap POA.
  - Heatmap inclinación × azimut si Recharts no resulta cómodo.

### Colores funcionales

- GHI: amber / naranja solar.
- DNI: azul.
- DHI: azul claro.
- POA: amarillo/naranja brillante.
- Generación FV: verde.
- Demanda: morado o rojo controlado.
- Demanda neta: azul/púrpura.
- Excedente: amber.

---

## 13. Mapa

El mapa pertenece a la pantalla de `Ubicación`.

### Implementación objetivo

- React Leaflet.
- OpenStreetMap.
- Click en mapa actualiza lat/lon.
- Marcador draggable si es posible.
- Búsqueda de ciudad mediante hook mock o futuro endpoint `/geocode`.

### En primera iteración

Si React Leaflet complica la instalación inicial, se permite crear primero un placeholder visual compatible con el diseño. Sin embargo, la estructura debe quedar preparada para reemplazarlo por mapa real.

---

## 14. Estados visuales

Implementar o preparar componentes para:

- `Aún no hay simulación`
- `Ejecutando simulación`
- `Simulación completada`
- `No se pudo ejecutar la simulación`
- `Selecciona una ubicación para comenzar`

Estos estados no deben romper la estética del dashboard.

---

## 15. Qué no debe hacer Codex con el diseño

- No dejar la UI en inglés.
- No usar los HTML de Stitch como iframes.
- No copiar cada `code.html` como una página independiente con layout repetido.
- No crear una landing page.
- No cambiar el producto a “Solar Monitoring”.
- No eliminar el mapa.
- No eliminar la tab de Demanda vs Solar.
- No eliminar la pantalla de Exportar.
- No meter toda la app en `App.jsx`.
- No construir backend físico real en la primera iteración si no se solicita explícitamente.

---

## 16. Resultado visual esperado

La primera implementación debe verse como una app de ingeniería:

- Sidebar oscura.
- Topbar compacta.
- Cards KPI.
- Gráficas técnicas.
- Tablas limpias.
- Mapa en configuración.
- Pestañas de análisis.
- Diseño consistente con los PNG del ZIP.
- Textos en español.
- Listo para conectar al backend después.


# Contexto tecnico del simulador fotovoltaico GDMTH

## 1. Resumen general del proyecto

Este proyecto es una aplicacion en Streamlit para evaluar un sistema fotovoltaico conectado a una carga comercial/industrial bajo una tarifa tipo GDMTH. La app integra un modelo fisico de generacion FV, un modelo de demanda electrica, un balance energetico por intervalos de 15 minutos y una estimacion economica con periodos tarifarios, cargos por demanda, factor de potencia e IVA.

La app permite:

- seleccionar ubicacion con entradas manuales o mapa;
- estimar recurso solar e irradiancia en plano del arreglo;
- configurar potencia, area, eficiencia, numero de paneles, inclinacion, orientacion y perdidas;
- usar demanda sintetica o demanda real cargada por archivo;
- calcular autoconsumo, energia exportada y energia tomada de red;
- estimar costo sin FV, costo con FV y ahorro bajo una tarifa tipo GDMTH;
- revisar graficas energeticas/economicas;
- exportar resultados en CSV, Excel y PDF.

El alcance es academico y de simulacion. La tarifa implementada es una aproximacion defendible, pero no sustituye una factura oficial CFE ni un estudio electrico formal.

## 2. Flujo general del modelo

El flujo principal conecta la interfaz con los motores fisicos y economicos asi:

```text
UI Streamlit
    |
    v
st.session_state
    |
    v
PVSystemConfig / DemandConfig / TariffConfig
    |
    v
Fuente de irradiancia / cielo despejado / CSV / datos externos
    |
    v
Irradiancia GHI, DNI, DHI
    |
    v
Posicion solar + transposicion POA con pvlib
    |
    v
Generacion FV kW y kWh por intervalo
    |
    v
Demanda sintetica o demanda real
    |
    v
Balance energetico por intervalo
    |
    v
Tarifa GDMTH estimada
    |
    v
Resumen, graficas y exportaciones
```

Funciones principales relacionadas:

- `simulate_pv_system()` en `src/solar_engine.py`;
- `add_synthetic_industrial_demand()` y `read_uploaded_demand()` en `src/demand_engine.py`;
- `add_tariff_columns()`, `monthly_tariff_summary()` y `annual_tariff_summary()` en `src/tariff_engine.py`;
- `compute_summary()` en `src/summary.py`;
- funciones de graficas en `src/plotting.py`;
- exportaciones en `src/exporting.py`.

## 3. Modelo fisico solar

La irradiancia es la potencia solar incidente por unidad de area, normalmente expresada en W/m2. El modelo distingue:

- `GHI`: irradiancia global horizontal. Es la radiacion total que llega a una superficie horizontal.
- `DNI`: irradiancia directa normal. Es la radiacion directa del sol medida sobre una superficie perpendicular al rayo solar.
- `DHI`: irradiancia difusa horizontal. Es la radiacion dispersada por la atmosfera que llega a una superficie horizontal.
- `POA`: plane of array. Es la irradiancia que llega al plano real del panel, considerando inclinacion, orientacion, posicion solar, albedo y modelo de transposicion.

La variable mas importante para estimar generacion FV es `POA_W_m2`, porque los paneles no estan acostados horizontalmente: estan inclinados y orientados. Por eso no basta con GHI; se necesita transformar GHI/DNI/DHI al plano del arreglo.

La libreria `pvlib` se usa para:

- calcular posicion solar;
- generar cielo despejado con el modelo Ineichen;
- descomponer GHI si faltan DNI/DHI;
- transponer irradiancia al plano del arreglo;
- estimar temperatura de celda.

El modelo de cielo despejado Ineichen representa un dia ideal sin nubes. Es util como referencia fisica, pero puede sobreestimar la generacion frente a un ano meteorologico real.

Los modelos de transposicion disponibles en la app son:

- `isotropic`: aproximacion simple de radiacion difusa isotropica;
- `haydavies`: modelo mas detallado que considera anisotropia de la radiacion difusa;
- `perez`: modelo mas avanzado de irradiancia difusa y condiciones de cielo.

## 4. Formula FV principal

La potencia instalada se calcula con la potencia nominal del modulo:

```text
P_instalada_kWp = number_of_panels * panel_power_w / 1000
```

La generacion instantanea del sistema se calcula como:

```text
generation_kW =
    P_instalada_kWp
    * (POA_W_m2 / 1000)
    * temperature_factor
    * (1 - system_losses)
```

La energia del intervalo se calcula como:

```text
energy_kWh = generation_kW * 0.25
```

Explicacion fisica:

- `P_instalada_kWp`: capacidad nominal total del arreglo bajo condiciones estandar.
- `POA_W_m2 / 1000`: fraccion relativa a 1000 W/m2, irradiancia de referencia STC.
- `temperature_factor`: ajuste por temperatura de celda. Si la celda se calienta, baja la potencia.
- `1 - system_losses`: factor agregado de perdidas.
- `0.25`: duracion de cada intervalo, porque 15 minutos equivalen a 0.25 horas.

## 5. Parametros del panel

Los parametros principales del arreglo son:

- potencia del panel (`panel_power_w`);
- area del panel (`panel_area_m2`);
- eficiencia (`panel_efficiency`);
- numero de paneles (`number_of_panels`);
- area total (`panel_area_m2 * number_of_panels`).

Caso representativo usado en las pruebas de sensibilidad:

| Parametro | Valor |
|---|---:|
| Numero de paneles | 100 |
| Potencia por panel | 550 W |
| Area por panel | 2.5 m2 |
| Eficiencia | 22% |
| Potencia instalada | 55 kWp |
| Area total | 250 m2 |

La consistencia entre potencia, area y eficiencia se verifica con:

```text
eficiencia = 550 / (2.5 * 1000) = 0.22 = 22%
```

Estos valores son representativos de un modulo comercial moderno, no una ficha tecnica obligatoria. Para un analisis real se deben sustituir por los datos del panel seleccionado.

## 6. Potencia nominal vs generacion real

Hay una diferencia importante entre capacidad y energia producida:

- La potencia instalada no cambia con clima ni perdidas.
- La potencia nominal estimada por area y eficiencia tampoco cambia con clima ni perdidas.
- La generacion real si cambia con irradiancia, POA, temperatura, inclinacion, orientacion, clima y perdidas.

La metrica "Potencia nominal estimada por area y eficiencia (STC)" se calcula como:

```text
panel_area_m2 * panel_efficiency * 1000 W/m2
```

Es una validacion nominal bajo condiciones estandar. No representa energia anual y no debe bajar al seleccionar nublado o aumentar perdidas. Si esa metrica bajara con clima, seria una senal de confusion conceptual.

## 7. Perdidas del sistema

`system_losses` representa perdidas agregadas por efectos no modelados individualmente:

- inversor;
- cableado;
- suciedad;
- mismatch;
- disponibilidad;
- sombras no modeladas por separado;
- otros efectos operativos.

Perdidas mayores reducen:

- generacion anual;
- pico de generacion;
- autoconsumo;
- ahorro economico.

Pero no reducen:

- potencia instalada;
- area total;
- potencia nominal estimada por area y eficiencia.

Como referencia, PVWatts/NREL usa un valor default cercano a 14% para perdidas agregadas. En la app el usuario puede modificar este valor.

## 8. Modelo de demanda

El simulador soporta demanda sintetica y demanda real cargada por archivo.

La demanda sintetica representa una operacion comercial/industrial, no una vivienda ni una ciudad. Sus parametros son:

- `max_demand_kw`: demanda maxima o pico permitido;
- `plant_factor`: relacion entre demanda media y demanda maxima;
- `power_factor`: factor de potencia para calcular kVA/reactivos;
- `weekend_reduction`: reduccion de carga en fines de semana;
- `summer_increase`: aumento de carga en verano;
- `random_seed`: semilla para reproducibilidad.

La energia de demanda por intervalo se calcula como:

```text
demand_energy_kWh = demand_kW * 0.25
```

La demanda media anual se calcula como:

```text
demanda_media_anual_kW = demanda_anual_kWh / 8760
```

## 9. Demanda sintetica vs demanda real

En demanda sintetica, la app genera una curva anual de 35,040 intervalos con:

- forma diaria industrial;
- diferencias entre horas de operacion y noche;
- reduccion en fines de semana;
- incremento en verano;
- ruido reproducible mediante semilla.

En demanda real, esos patrones ya deben venir contenidos en el archivo. La app no inventa fines de semana ni verano cuando el usuario carga datos reales; solo valida, convierte y alinea la serie temporal.

Columnas minimas para demanda real:

```text
datetime
demand_kW
```

Columnas opcionales:

```text
demand_energy_kWh
power_factor
```

Si falta `demand_energy_kWh`, se calcula con `demand_kW * 0.25`. Si falta `power_factor`, se usa el factor de potencia general configurado en la interfaz.

## 10. Balance energetico

El balance energetico se calcula en cada intervalo de 15 minutos:

```text
self_consumed_kWh = min(energy_kWh, demand_energy_kWh)

exported_kWh = max(energy_kWh - demand_energy_kWh, 0)

grid_energy_kWh = max(demand_energy_kWh - energy_kWh, 0)
```

Interpretacion:

- `self_consumed_kWh`: energia FV usada por la carga en el mismo intervalo.
- `exported_kWh`: excedente FV cuando la generacion supera la demanda instantanea.
- `grid_energy_kWh`: energia tomada de red cuando la demanda supera la generacion FV.

Sin bateria, puede haber exportacion durante horas solares y consumo de red en la noche. Por eso se distinguen:

- `generacion anual / demanda anual`: compara energia total anual generada contra energia total consumida;
- `cobertura directa por autoconsumo`: compara solo la energia FV que coincidio temporalmente con la demanda.

## 11. Caso de validacion de 100 paneles

Caso analizado:

| Parametro | Valor |
|---|---:|
| Ubicacion | Monterrey, Nuevo Leon |
| Fuente solar | Cielo despejado con pvlib Ineichen |
| Paneles | 100 |
| Potencia por panel | 550 W |
| Potencia instalada | 55 kWp |
| Area total | 250 m2 |
| Tilt | 25 grados |
| Azimuth | Sur |
| Modelo POA | Hay-Davies |
| Perdidas | 12% |

Resultado observado:

| Indicador | Valor aproximado |
|---|---:|
| Generacion anual | 108,856 kWh/ano |
| Rendimiento especifico | 1,979 kWh/kWp/ano |
| PVOUT diario | 5.42 kWh/kWp/dia |

Rango de referencia para Mexico:

```text
PVOUT aproximado = 3.77 a 5.52 kWh/kWp/dia
```

Para 55 kWp:

```text
bajo = 55 * 3.77 * 365 = 75,683 kWh/ano
alto = 55 * 5.52 * 365 = 110,814 kWh/ano
```

El resultado de 108,856 kWh/ano es alto, pero fisicamente defendible porque usa cielo despejado. Esta cerca del limite superior esperado para Mexico.

## 12. Sensibilidad fisica

### Perdidas

Caso base: 55 kWp, Monterrey, cielo despejado, demanda 50 kW con factor de planta 0.60.

| Perdidas | Generacion kWh/ano | PVOUT diario | Pico kW | Autoconsumo kWh | Exportacion kWh | Red kWh | Ahorro MXN |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 12% | 108,856 | 5.42 | 43.79 | 104,082 | 4,774 | 158,718 | 247,727 |
| 14% | 106,382 | 5.30 | 42.79 | 102,322 | 4,061 | 160,478 | 242,855 |
| 20% | 98,960 | 4.93 | 39.81 | 96,497 | 2,463 | 166,303 | 226,673 |
| 30% | 86,590 | 4.31 | 34.83 | 85,878 | 712 | 176,922 | 197,058 |

Al aumentar perdidas:

- baja generacion anual;
- baja pico de generacion;
- baja autoconsumo;
- baja ahorro;
- sube energia tomada de red.

### Clima

| Escenario | GHI prom W/m2 | POA prom W/m2 | Generacion kWh/ano | PVOUT diario | Ahorro MXN |
|---|---:|---:|---:|---:|---:|
| Cielo despejado | 260.0 | 283.9 | 108,856 | 5.42 | 247,727 |
| Parcial 0.75 | 195.0 | 212.3 | 83,579 | 4.16 | 189,309 |
| Nublado 0.45 | 117.0 | 126.9 | 51,520 | 2.57 | 100,636 |
| Muy cubierto 0.25 | 65.0 | 70.4 | 29,123 | 1.45 | 50,539 |

Al reducir irradiancia:

- baja GHI;
- baja POA;
- baja generacion;
- baja ahorro.

## 13. Escala de demanda

Los escenarios de 30, 50 y 60 kW corresponden al reto academico. No necesariamente representan una aplicacion oficial estricta de GDMTH, que suele asociarse a demandas mayores, por ejemplo alrededor de 100 kW o mas.

Ejemplo:

```text
max_demand_kw = 30 kW
plant_factor = 0.50
demanda_media = 30 * 0.50 = 15 kW
demanda_anual = 15 * 8760 = 131,400 kWh/ano
```

Esto representa una operacion comercial/industrial pequena, no una vivienda.

Comparacion academica observada para el sistema de 55 kWp:

| Caso | Demanda anual kWh | Cobertura directa | Exportacion kWh | Energia de red kWh |
|---|---:|---:|---:|---:|
| 30 kW LF 0.50 | 131,400 | 54.8% | 36,911 | 59,455 |
| 50 kW LF 0.60 | 262,800 | 39.6% | 4,774 | 158,718 |
| 60 kW LF 0.70 | 367,920 | 29.6% | 89 | 259,153 |
| 100 kW LF 0.60 | 525,600 | 20.7% | 0 | 416,744 |

En el caso de 100 kW, el sistema FV se autoconsume practicamente por completo y no hay exportacion.

## 14. Tarifa GDMTH

El modulo tarifario estima costo mensual y anual con y sin FV. Componentes principales:

- energia en periodo Base;
- energia en periodo Intermedia;
- energia en periodo Punta;
- cargo de distribucion;
- cargo de capacidad;
- ajuste por factor de potencia;
- cargo fijo;
- IVA.

Sin FV se usa la energia de demanda:

```text
cost_without_pv_mxn = demand_energy_kWh * energy_rate_mxn_kwh
```

Con FV se usa la energia tomada de red:

```text
cost_with_pv_mxn = grid_energy_kWh * energy_rate_mxn_kwh
```

Ahorro:

```text
savings_mxn = cost_without_pv_mxn - cost_with_pv_mxn
```

La demanda facturable se estima mensualmente con una adaptacion academica:

```text
Dlim = monthly_energy_kWh / (hours_in_month * demand_limit_load_factor)

Ddist = min(max(Dbase, Dintermedia, Dpunta), Dlim)

Dcap = min(Dpunta, Dlim)
```

Luego:

```text
distribution_cost = Ddist * distribution_rate_mxn_kw

capacity_cost = Dcap * capacity_rate_mxn_kw
```

El cargo fijo se aplica tanto con FV como sin FV, por lo que no genera ahorro artificial. El IVA se aplica al subtotal final. Este modulo es una aproximacion academica, no una factura oficial CFE.

## 15. Factor de potencia

Definiciones:

- `kW`: potencia activa, asociada al trabajo util.
- `kVA`: potencia aparente.
- `kVAr`: potencia reactiva.
- `factor de potencia`: relacion entre potencia activa y aparente.

La app calcula:

```text
apparent_power_kVA = demand_kW / power_factor
```

Si no existe una columna explicita de reactivos, el modulo tarifario puede estimar `kVAr` a partir de `kVA` o de `power_factor`.

El factor de potencia global mensual se calcula como:

```text
fp_global =
sum(active_power) /
sqrt(sum(active_power)^2 + sum(reactive_power)^2)
```

Ajuste aplicado:

```text
fp_adjustment = (3 / 5) * (0.9 / fp_global - 1)
```

La FV puede reducir potencia activa tomada de red durante horas solares, pero no necesariamente reduce reactivos si la carga sigue demandando potencia reactiva. Por eso el modelo conserva una separacion entre potencia activa y reactiva.

## 16. Mapa y ubicacion

La ubicacion afecta:

- posicion solar;
- cielo despejado;
- POA;
- zona horaria;
- periodos tarifarios;
- alineacion de demanda real.

La app integra:

- Google Maps JavaScript API para mapa;
- Places API para busqueda de lugares;
- Elevation API para altitud;
- Time Zone API para zona horaria.

El usuario tambien puede introducir latitud, longitud, altitud y zona horaria manualmente. Si no existe `GOOGLE_MAPS_API_KEY`, la app no se detiene: muestra fallback manual.

La API key no esta hardcodeada en el codigo ni debe exponerse en UI, README o docs. Debe configurarse como variable de entorno o secreto local de Streamlit.

## 17. Fuentes de irradiancia

Fuentes principales:

- cielo despejado Ineichen;
- escenario climatico simple;
- CSV propio.

Fuentes externas avanzadas:

- PVGIS;
- NASA POWER;
- NSRDB PSM3.

PVGIS, NASA POWER y NSRDB se cargan bajo demanda con el boton correspondiente. No se descargan automaticamente para evitar bloqueos en cada rerun de Streamlit.

Si se selecciona una fuente externa y no hay datos cargados para la configuracion actual, la app usa cielo despejado temporalmente y muestra aviso.

CSV propio espera al menos:

```text
datetime
ghi
```

Opcionales:

```text
dni
dhi
temp_air
wind_speed
```

## 18. Exportaciones

La app permite preparar:

- CSV;
- Excel;
- PDF.

Las exportaciones se generan bajo boton para evitar trabajo pesado en cada rerun. Excel puede tardar porque incluye la serie anual completa de 15 minutos.

La firma de exportacion incluye:

- forma del dataframe;
- primer y ultimo timestamp;
- resumen energetico;
- resumen tarifario anual;
- totales y checksum de columnas energeticas clave;
- totales y checksum del resumen mensual tarifario.

Si cambian los resultados, las exportaciones preparadas se invalidan y deben generarse de nuevo.

## 19. Tests y validacion

Al cierre de este documento, la suite automatizada reporta:

```text
46 passed
```

La suite valida:

- generacion FV;
- uso de potencia nominal instalada;
- perdidas;
- sensibilidad climatica;
- demanda sintetica;
- demanda real;
- balance energetico por intervalo y anual;
- tarifa GDMTH;
- periodos Base/Intermedia/Punta;
- IVA;
- factor de potencia;
- firma de exportaciones;
- helpers de mapa y zona horaria.

Pruebas relevantes en `tests/test_engines.py`:

- `test_pv_generation_uses_nominal_installed_power_when_pvlib_is_available`;
- `test_physical_sensitivity_preserves_nominal_metrics_and_updates_exports`;
- `test_interval_and_annual_energy_balances_are_conserved`;
- `test_industrial_demand_profile_uses_inputs_and_preserves_units`;
- `test_real_demand_profile_is_compatible_with_simulation_balance_columns`;
- `test_monthly_and_annual_tariff_summaries_are_consistent_and_non_negative`;
- `test_low_power_factor_increases_tariff_total`;
- `test_fetch_google_timezone_uses_params_without_key_in_url`.

## 20. Limitaciones

Limitaciones principales:

- tarifa GDMTH aproximada;
- no sustituye factura oficial CFE;
- no monetiza energia exportada;
- no modela bateria;
- no modela peak shaving todavia;
- no calcula payback ni ROI;
- escenario climatico simple no sustituye mediciones reales;
- demanda sintetica no sustituye perfil real medido;
- perdidas son agregadas, no desglosadas por componente;
- cielo despejado puede sobreestimar generacion frente a clima real;
- no modela degradacion anual, clipping de inversor ni sombras detalladas.

## 21. Proximas etapas

Mejoras sugeridas:

- integrar perfil real de demanda del profesor;
- cargar base real de costos de energia y parametros tarifarios vigentes;
- implementar escenarios de 25%, 50% y 75% de demanda media;
- implementar escenario enfocado en horario punta;
- evaluar si el caso requiere bateria o peak shaving;
- comparar cielo despejado contra PVGIS, NASA POWER o NSRDB cargados bajo demanda;
- agregar validacion visual final para Places Autocomplete en navegador externo.

## 22. Referencias al codigo

Archivos y funciones clave:

| Area | Archivo | Funcion |
|---|---|---|
| Modelo FV | `src/solar_engine.py` | `simulate_pv_system()` |
| Irradiancia externa | `src/irradiance_data.py` | `read_uploaded_irradiance()`, `to_15min_irradiance()` |
| Demanda sintetica | `src/demand_engine.py` | `add_synthetic_industrial_demand()` |
| Demanda real | `src/demand_engine.py` | `read_uploaded_demand()` |
| Tarifa | `src/tariff_engine.py` | `add_tariff_columns()` |
| Resumen mensual | `src/tariff_engine.py` | `monthly_tariff_summary()` |
| Resumen anual | `src/tariff_engine.py` | `annual_tariff_summary()` |
| Resumen tecnico | `src/summary.py` | `compute_summary()` |
| Graficas | `src/plotting.py` | `plot_monthly_energy()`, `plot_monthly_tariff_savings()` |
| Exportaciones | `src/exporting.py` | `build_excel_export()`, `build_pdf_report()` |

Este documento resume el comportamiento implementado en el codigo actual. Si se modifican formulas, fuentes de datos, tarifa o interfaz, debe actualizarse junto con `docs/model_validation.md`.

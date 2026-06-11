# Plan de implementacion Etapa 2: Consumo y ahorro

## 1. Objetivo de la Etapa 2

Construir una seccion clara de Consumo y ahorro que conecte la generacion fotovoltaica de la Etapa 1 con el consumo energetico del usuario para estimar, de forma rapida y entendible:

- energia consumida por el usuario
- energia FV generada por el sistema
- energia FV autoconsumida
- energia tomada de la red
- energia exportada o sobrante
- porcentaje de cobertura solar directa
- ahorro express cuando el usuario ingresa un costo promedio por kWh

La etapa debe mantenerse por debajo del analisis tarifario formal. No debe incluir BESS, respaldo, ROI, cashflow, payback, costo de inaccion ni analisis financiero avanzado.

## 2. Estado actual encontrado en el codigo

La app ya tiene una pestana llamada Consumo y ahorro en `app.py`. La Etapa 2A ya esta implementada como flujo interno por pasos, con un modo rapido de consumo y ahorro express separado del analisis tarifario formal.

- `render_stage2_savings_wizard(df, summary, monthly_tariff, annual_tariff)` concentra el flujo de Consumo y ahorro.
- `STAGE2_STEPS` define los pasos `Consumo`, `Costo express`, `Balance solar`, `Resultados` y `Avanzado`.
- El encabezado de la pestana usa `section_header()` con titulo y descripcion compacta.
- El modo rapido calcula balance energetico y ahorro express sin usar el motor GDMTH.
- `render_stage2_advanced_step()` muestra la entrada `Facturacion CFE avanzada` con selector de analisis basado en datos de recibo.
- `build_sidebar()` concentra la configuracion de demanda y tarifa en la barra lateral avanzada.
- `run_simulation()` siempre ejecuta una simulacion FV y agrega demanda sintetica o demanda real cargada.
- El flujo principal calcula `df`, `summary`, `monthly_tariff` y `annual_tariff` antes de renderizar las pestanas.

Keys durables usadas por 2A:

- `stage2_step`
- `stage2_monthly_consumption_kwh`
- `stage2_annual_consumption_kwh`
- `stage2_consumption_input_mode`
- `stage2_express_enabled`
- `stage2_avg_kwh_cost_mxn`
- `stage2_advanced_billing_mode`
- `stage2_receipt_service_type`
- `stage2_receipt_period_frequency`
- `stage2_receipt_contracted_demand_kw`
- `stage2_receipt_tariff_label`
- `stage2_receipt_confirmed_tariff`
- `stage2_receipt_residential_tariff`
- `stage2_receipt_periods_df`
- `stage2_receipt_periods_initialized`

Los widgets condicionales usan keys temporales `_stage2_*_widget`, pero la fuente de verdad debe seguir siendo el estado durable anterior para evitar resets al navegar entre pasos.

La tabla editable del recibo usa `stage2_receipt_periods_df` como fuente durable. La plantilla inicial solo se crea cuando la tabla no existe o cuando el usuario presiona explicitamente restablecer; no debe forzarse un minimo de filas despues de que el usuario edita o elimina periodos.

La busqueda de marcadores tipicos de mojibake en `app.py`, `src` y `docs` no encontro cadenas corruptas visibles al momento de esta auditoria.

## 3. Componentes existentes que se pueden reutilizar

### Demanda

Archivo: `src/demand_engine.py`

Componentes reutilizables:

- `DemandConfig`
- `add_synthetic_industrial_demand(df, config)`
- `read_uploaded_demand(file, year, timezone, default_power_factor)`
- `add_real_demand_to_simulation(pv_df, demand_df)`
- `_add_energy_balance_columns(result, demand_source)`

Capacidades existentes:

- demanda sintetica industrial
- demanda real cargada por CSV o Excel
- validacion de `datetime` y `demand_kW`
- columna opcional `demand_energy_kWh`
- columna opcional `power_factor`
- reindexado e interpolacion a intervalos de 15 minutos
- deteccion de duplicados y faltantes
- calculo de `apparent_power_kVA`
- calculo de energia de demanda por intervalo

### Balance energetico

Archivo: `src/demand_engine.py`

La funcion `_add_energy_balance_columns()` ya calcula por intervalo:

- `self_consumed_kWh = min(energy_kWh, demand_energy_kWh)`
- `exported_kWh = max(energy_kWh - demand_energy_kWh, 0)`
- `grid_energy_kWh = max(demand_energy_kWh - energy_kWh, 0)`
- `net_power_kW = generation_kW - demand_kW`
- `demand_source`

Archivo: `src/summary.py`

`compute_summary()` ya agrega:

- generacion anual
- demanda anual
- autoconsumo anual
- energia exportada
- energia tomada de red
- cobertura de demanda por autoconsumo
- pico de generacion
- pico de demanda
- rendimiento especifico

### Costos y ahorro

Archivo: `src/tariff_engine.py`

Componentes existentes:

- `TariffConfig`
- `classify_gdmth_period(timestamp)`
- `add_tariff_columns(df, config)`
- `monthly_tariff_summary(df, config)`
- `annual_tariff_summary(monthly)`

Capacidades existentes:

- costo sin FV y con FV por periodo GDMTH
- ahorro mensual y anual
- cargos por demanda de distribucion y capacidad
- cargo fijo mensual
- IVA
- ajuste por factor de potencia
- resumen mensual y anual

Para Etapa 2 se recomienda no usar esta logica como experiencia principal, porque el alcance rapido es ahorro express con costo promedio por kWh. Puede quedar disponible dentro del paso Avanzado como analisis con datos de recibo y balance detallado.

Alcance actual del motor tarifario:

- Es una estimacion GDMTH simplificada.
- No contiene por si mismo un modelo GDMTO o residencial basado en recibo resumido.
- No debe tomar la tabla residencial tipo 1 como fuente de precios por kWh.
- No sustituye un calculo oficial CFE.
- No debe recibir valores hardcodeados de una ciudad, tarifa o mes especifico.

Archivo: `src/express_savings.py`

Componentes existentes:

- `compute_express_savings(...)`

Capacidades existentes:

- consumo anual desde entrada mensual o anual
- generacion anual desde la simulacion FV
- energia restante de red
- energia excedente
- cobertura solar
- costo sin FV, costo con FV y ahorro express cuando hay costo promedio valido

Este modulo debe mantenerse separado del motor tarifario formal.

### Visualizaciones

Archivo: `src/plotting.py`

Funciones reutilizables:

- `plot_daily_generation_vs_demand(df_day)`
- `plot_monthly_energy(df)`
- `plot_monthly_energy_balance(df)`
- `plot_net_energy_flow(df)`
- `plot_hourly_average(df)`
- `plot_monthly_tariff_savings(monthly)`
- `plot_tariff_energy_by_period(monthly)`
- `plot_tariff_component_breakdown(monthly)`

Para Etapa 2 son especialmente utiles las graficas de generacion contra demanda y balance mensual. Las graficas tarifarias GDMTH deben quedar separadas del modo express.

### Exportaciones

Archivo: `src/exporting.py`

`build_excel_export()` ya exporta resumen, serie de 15 minutos, tarifa y escenarios. `build_pdf_report()` ya puede recibir resumen y tarifa anual. Para esta etapa no es necesario cambiar exportaciones todavia, pero el plan debe considerar que las nuevas salidas express podrian agregarse despues.

## 4. Riesgos tecnicos

- La pestana Consumo y ahorro ya existe y depende del flujo global de simulacion. Cambiarla puede romper la Etapa 1 si se altera `run_simulation()`, `compute_summary()` o la construccion de `df`.
- La demanda sintetica esta activa por default. El modo express ya evita modificar el motor industrial existente, pero cualquier ampliacion debe conservar esa separacion.
- El calculo actual de cobertura usa autoconsumo por intervalo. Esto es correcto, pero debe explicarse de forma breve para evitar que el usuario confunda generacion anual/demanda anual con cobertura real.
- El modulo GDMTH actual es mas avanzado que el ahorro express. Si se mezcla con el modo rapido, la interfaz puede quedar pesada y fuera del alcance de Etapa 2.
- La carga de demanda real exige serie horaria o quinceminutal. Los datos mensuales o bimestrales del recibo deben tratarse como analisis resumido, no como serie temporal detallada.
- Los widgets de demanda y tarifa estan en la barra lateral avanzada, no dentro de un flujo guiado de Consumo y ahorro.
- La app calcula tarifa GDMTH siempre, aunque el usuario solo quiera un balance express. Esto puede ser innecesario para la experiencia rapida.
- Si se agrega costo promedio por kWh, debe evitarse modificar formulas GDMTH existentes o reemplazar sus resultados.
- El paso `Avanzado` de Consumo y ahorro reutiliza el GDMTH actual y debe distinguirlo del analisis resumido basado en recibo.
- La barra lateral todavia expone parametros GDMTH globales. Si se agrega CFE avanzado, conviene evitar que esos controles parezcan obligatorios para el modo express.
- El siguiente modulo CFE avanzado debe evitar hardcodear ciudad, cliente, mes u otros datos de un caso particular. Todo dato tarifario debe ser entrada configurable o fixture de prueba.
- Debe evitarse mezclar ahorro express, recibo resumido y balance quinceminutal: cada capa responde preguntas distintas y usa datos de diferente resolucion.

## 5. Diseno funcional propuesto

La pestana Consumo y ahorro debe dividirse conceptualmente en dos modos:

### Modo rapido

Objetivo: que el usuario obtenga una estimacion simple sin cargar archivos ni configurar tarifa formal.

Entrada propuesta:

- consumo mensual promedio en kWh, o
- consumo anual estimado en kWh
- costo promedio por kWh opcional

Salida propuesta:

- consumo anual estimado
- generacion FV anual tomada de Etapa 1
- autoconsumo estimado
- energia tomada de red
- energia exportada o sobrante
- cobertura solar directa
- costo anual estimado sin FV
- costo anual estimado con FV
- ahorro express anual

### Modo detallado

Objetivo: reutilizar la demanda real o sintetica existente y calcular balance con resolucion de 15 minutos.

Entrada propuesta:

- demanda sintetica existente, o
- archivo CSV/Excel existente con `datetime` y `demand_kW`

Salida propuesta:

- balance anual y mensual con las columnas existentes
- grafica diaria de generacion contra demanda
- grafica mensual de demanda, generacion, autoconsumo, red y exportacion
- resumen de cobertura solar directa

El analisis con datos de recibo debe mantenerse separado del modo express. Puede vivir en el paso Avanzado de Consumo y ahorro, alineado con Facturacion CFE avanzada.

### Capas de analisis en Consumo y ahorro

La Etapa 2 debe distinguir tres niveles:

- Express: usa consumo anual o mensual y costo promedio simple para dar una estimacion rapida.
- Recibo resumido: usa historial de consumo, demanda cuando aplique y precio medio facturado MXN/kWh tomado del recibo.
- Balance quinceminutal: usa serie temporal de demanda para calcular autoconsumo, energia exportada, energia de red y coincidencia temporal entre demanda y generacion FV.

El analisis con datos de recibo no debe depender de precios precargados por zona. Los precios varian por zona, periodo, temporada y condiciones del recibo; por eso el dato base economico de esta etapa es el precio medio facturado MXN/kWh que el usuario captura por mes o bimestre.

### Resultado anual historico y proyeccion anual

- Historico anual: aplica cuando el usuario captura 12 meses, 6 bimestres o el conjunto completo de periodos equivalentes del ano.
- Proyeccion anual: aplica cuando el usuario captura menos periodos y la app anualiza el promedio mensual o bimestral capturado.

La interfaz y la documentacion deben mostrar claramente si el resultado es historico anual o proyeccion anual.

### Datos minimos recomendados del recibo

Industrial:

- demanda contratada kW
- tarifa que aparece en el recibo, opcional
- periodo
- consumo total kWh
- demanda maxima kW
- factor de potencia %, opcional
- precio medio MXN/kWh

Residencial:

- tarifa residencial seleccionada: 1A, 1B, 1C, 1D, 1E o 1F
- periodo mensual o bimestral
- consumo kWh
- precio medio MXN/kWh

No pedir por ahora:

- numero de servicio
- RMU
- cuenta
- numero de medidor
- fecha limite de pago
- corte a partir
- numero de hilos
- multiplicador
- carga conectada

### Tabla residencial tipo 1

La tabla residencial tipo 1 solo identifica limites de bloques y clasificacion de tarifa. No contiene precios por kWh, no debe ser editable y no debe usarse como fuente de precios. El precio economico usable en esta etapa es el precio medio facturado que el usuario lee de su recibo.

### Lugar del analisis quinceminutal

El analisis quinceminutal pertenece al balance energetico detallado, no a la tabla del recibo. Sirve para calcular mejor:

- autoconsumo
- energia exportada
- energia de red
- coincidencia temporal entre demanda y generacion FV

Si el usuario solo ingresa datos mensuales o bimestrales del recibo, el balance es mensual o anual resumido. Si el usuario carga demanda quinceminutal, el balance puede ser temporal detallado.

## 6. Estado de subetapas

### 2A Entrada rapida de consumo y ahorro express

Estado: implementada.

- Controles nativos de Streamlit para entrada mensual promedio o anual estimada.
- Costo promedio por kWh opcional mediante modo express.
- Estado durable para conservar consumo, costo y activacion express al navegar entre pasos.
- Resultados muestran balance energetico cuando hay consumo valido.
- Resultados muestran ahorro monetario solo si express esta activo y hay costo valido.
- No modifica demanda real, demanda sintetica, motor solar, NASA POWER ni GDMTH.

### 2B Modulo CFE avanzado dentro de Consumo y ahorro

Estado: implementada como primera version funcional para analisis con datos de recibo.

Ubicacion recomendada: paso `Avanzado` dentro de la pestana Consumo y ahorro.

Razon:

- Depende del consumo, generacion FV, balance energetico y datos utiles del recibo.
- Debe mantenerse separado del modo express.
- Evita convertir la pestana superior `Avanzado` en una mezcla de datos solares, exportaciones y facturacion.
- Permite conservar el GDMTH actual como vista avanzada y agrega una ruta conceptual para recibo resumido.

Alcance inicial recomendado:

- El paso `Avanzado` muestra `Facturacion CFE avanzada` como entrada formal separada del modo express.
- `stage2_advanced_billing_mode` conserva la seleccion del analisis avanzado.
- Opciones actuales: `Sin analisis formal`, `GDMTH existente`, `CFE residencial tipo 1` y `Tarifa configurable`.
- `GDMTH existente` reutiliza la vista y motor GDMTH actuales sin cambiar formulas.
- `CFE residencial tipo 1` es una vista informativa de bloques; no contiene precios y no debe ser editable.
- `Tarifa configurable` describe los campos recomendados del recibo: consumo, demanda si aplica y precio medio facturado.
- Mantener todos los valores economicos como datos capturados del recibo o entradas configurables, no hardcodeados.
- Sugerir GDMTO/GDMTH a partir de la demanda contratada y la tarifa que aparece en el recibo, sin obligar una ciudad o periodo fijo.
- Clasificar el resultado como historico anual si hay periodos completos o como proyeccion anual si se anualiza un subconjunto.
- `compute_receipt_based_savings(...)` calcula consumo anual, costo sin FV, energia cubierta, energia de red, costo con FV, ahorro y porcentaje de ahorro usando precio medio facturado.
- `suggest_industrial_tariff_family(...)` sugiere GDMTO si la demanda contratada es menor a 100 kW y GDMTH si es mayor o igual a 100 kW.
- La tabla residencial tipo 1 se muestra solo dentro de un expander informativo cerrado por default.
- El balance quinceminutal queda como expander informativo separado de la tabla del recibo.
- No incluir ROI, cashflow, BESS, respaldo ni payback.

### 2C Entrada detallada o carga historica

- Reutilizar `read_uploaded_demand()` para CSV/Excel horario o quinceminutal.
- Mantener validaciones actuales de columnas, negativos, duplicados, timezone y resolucion.
- Evaluar si la entrada mensual historica debe mapearse a un perfil mensual simple en una funcion nueva.
- No cambiar formulas existentes de demanda real.

### 2D Balance demanda vs generacion

- Reutilizar las columnas de Etapa 1: `generation_kW`, `energy_kWh`, `datetime`, `date`, `month`, `month_name`, `hour`, `irradiance_source`.
- Para modo detallado, reutilizar `_add_energy_balance_columns()` a traves de `add_synthetic_industrial_demand()` o `add_real_demand_to_simulation()`.
- Para modo rapido, crear una funcion nueva que convierta consumo mensual/anual en demanda energetica compatible con `energy_kWh`.
- Mantener los nombres de salida existentes cuando sea posible: `demand_energy_kWh`, `self_consumed_kWh`, `exported_kWh`, `grid_energy_kWh`.

### 2E Ahorro express con costo promedio por kWh

- Mantener el calculo independiente del motor GDMTH.
- Usar costo promedio por kWh solo si el usuario lo ingresa y lo activa.
- Calcular y conservar:
  - costo sin FV = consumo anual kWh * costo promedio
  - costo con FV = energia de red anual kWh * costo promedio
  - ahorro express = costo sin FV - costo con FV
  - ahorro express porcentual = ahorro express / costo sin FV
- No incluir cargos por demanda, IVA, factor de potencia, demanda facturable ni periodos tarifarios en modo express.

### 2F Visualizaciones de consumo y ahorro

- Reutilizar `plot_daily_generation_vs_demand()` para modo detallado.
- Reutilizar `plot_monthly_energy()` o `plot_monthly_energy_balance()` para balance mensual.
- Mantener una vista compacta de indicadores principales.
- Evitar una tabla larga visible por default; usar expander si hace falta.

### 2G Validaciones y pulido visual

- Validar consumo mayor o igual a cero.
- Validar costo promedio por kWh mayor o igual a cero.
- Evitar division entre cero en cobertura y ahorro porcentual.
- Mostrar mensajes claros si no hay consumo cargado.
- Mantener la Etapa 1 independiente de consumo.
- Mantener textos breves y sin JSON visible.

## 7. Variables de entrada

Entradas de Etapa 1 reutilizadas:

- `year`
- `timezone`
- `irradiance_source`
- `latitude`
- `longitude`
- `number_of_panels`
- `panel_power_w`
- `panel_area_m2`
- `panel_efficiency_percent`
- `tilt_deg`
- `azimuth_deg`
- `system_losses_percent`
- `albedo`
- `transposition_model`

Entradas existentes de demanda detallada:

- `demand_mode`
- `max_demand_kw`
- `plant_factor`
- `power_factor`
- `weekend_reduction`
- `summer_increase`
- `random_seed`
- `uploaded_demand_file`

Entradas nuevas propuestas para modo rapido:

- modo de consumo rapido: mensual promedio o anual estimado
- `stage2_monthly_consumption_kwh`
- `stage2_annual_consumption_kwh`
- `stage2_consumption_input_mode`
- `stage2_express_enabled`
- `stage2_avg_kwh_cost_mxn`

Entradas propuestas para analisis con datos de recibo:

- `stage2_advanced_billing_mode`
- segmento de recibo: industrial o residencial
- periodo mensual o bimestral
- consumo total kWh por periodo
- precio medio MXN/kWh por periodo
- demanda contratada kW para industrial
- demanda maxima kW para industrial
- tarifa que aparece en el recibo, opcional
- factor de potencia %, opcional
- seleccion residencial 1A, 1B, 1C, 1D, 1E o 1F
- cantidad de periodos capturados para distinguir historico anual de proyeccion anual

## 8. Variables de salida

Salidas energeticas:

- `annual_consumption_kWh`
- `annual_generation_kWh`
- `self_consumed_kWh`
- `grid_energy_kWh`
- `exported_kWh`
- `coverage_percent`
- `generation_to_demand_percent`
- `exported_fraction_percent`

Salidas de ahorro express:

- `annual_cost_without_pv_mxn`
- `annual_cost_with_pv_mxn`
- `annual_express_savings_mxn`
- `annual_express_savings_percent`
- `average_cost_mxn_kwh`

Salidas para trazabilidad:

- fuente de demanda
- fuente solar activa
- ano de simulacion
- potencia FV instalada
- numero de paneles
- tipo de analisis anual: historico anual o proyeccion anual
- cantidad de periodos de recibo capturados

## 9. Funciones existentes a reutilizar

- `simulate_pv_system()` en `src/solar_engine.py`
- `run_simulation()` en `app.py`
- `DemandConfig` en `src/demand_engine.py`
- `add_synthetic_industrial_demand()` en `src/demand_engine.py`
- `read_uploaded_demand()` en `src/demand_engine.py`
- `add_real_demand_to_simulation()` en `src/demand_engine.py`
- `compute_summary()` en `src/summary.py`
- `summary_table()` en `src/summary.py`
- `plot_daily_generation_vs_demand()` en `src/plotting.py`
- `plot_monthly_energy()` en `src/plotting.py`
- `plot_monthly_energy_balance()` en `src/plotting.py`
- `plot_net_energy_flow()` en `src/plotting.py`
- `metric_card()` y `section_header()` en `src/ui_components.py`

## 10. Funciones nuevas propuestas, si hacen falta

- `build_quick_consumption_profile(pv_df, annual_consumption_kwh, profile_mode)` para generar una demanda simple compatible con el DataFrame FV.
- `compute_express_savings(...)` para calcular ahorro express sin tarifa GDMTH. Ya existe en `src/express_savings.py`.
- `monthly_energy_balance(df)` si se quiere separar la agregacion mensual de las funciones de plotting.
- `render_consumption_inputs()` para mover la entrada de consumo desde la barra lateral hacia la pestana de Consumo y ahorro.
- `render_express_savings()` para mostrar indicadores de ahorro express sin mezclar GDMTH.
- `analyze_receipt_history(...)` o equivalente para resumir consumo, demanda y precio medio facturado por periodo.
- `compute_receipt_based_savings(...)` para estimar ahorro anual resumido con datos del recibo. Ya existe en `src/receipt_savings.py`.
- `classify_annual_receipt_scope(...)` para distinguir historico anual contra proyeccion anual.
- `suggest_industrial_tariff_family(...)` para sugerir GDMTO/GDMTH desde demanda contratada, sin hardcodear zona. Ya existe en `src/receipt_savings.py`.
- `ReceiptPeriodInput` o equivalente para encapsular datos resumidos del recibo.

Estas funciones deben ser pequenas y no deben modificar el motor solar, NASA POWER, formulas GDMTH ni exportaciones existentes.

## 11. Plan recomendado para siguiente subetapa CFE avanzada

### 11.1 Auditoria de entradas de recibo

- Documentar que campos utiles se necesitan para industrial y residencial.
- Separar entradas requeridas, opcionales y derivables desde la serie de demanda.
- Usar precio medio facturado MXN/kWh como dato capturado por periodo.
- Excluir identificadores administrativos que no aportan al analisis energetico.

### 11.2 Estructura de historial de recibos

- Capturar meses o bimestres con consumo kWh, costo medio y demanda cuando aplique.
- Detectar si hay 12 meses, 6 bimestres o periodos completos equivalentes.
- Marcar el resultado como historico anual o proyeccion anual.

### 11.3 Analisis economico con precio medio facturado

- Calcular costo base desde consumo y precio medio facturado.
- Usar el balance energetico existente para estimar energia de red con FV.
- Mantener el resultado como analisis basado en recibo, no como sustituto de factura oficial.

### 11.4 Interfaz en paso Avanzado

- Mantener selector de tipo de analisis dentro de `Avanzado` de Consumo y ahorro.
- Mostrar captura mensual o bimestral compacta.
- Mostrar si el resultado es historico anual o proyeccion anual.
- Conservar express como flujo rapido independiente.
- Mantener la tabla residencial tipo 1 como referencia no editable de bloques.

### 11.5 Pruebas

- Agregar pruebas unitarias para periodos mensuales y bimestrales.
- Probar entradas invalidas, ceros y datos faltantes.
- Probar clasificacion historico anual contra proyeccion anual.
- Confirmar que Etapa 1, NASA POWER, GDMTH existente y exportaciones no cambian.

## 12. Pruebas recomendadas

Cuando se implemente codigo en Etapa 2, ejecutar:

```bash
python -m py_compile app.py
python -m pytest -q -p no:cacheprovider
```

Pruebas unitarias recomendadas:

- consumo mensual promedio se convierte correctamente a consumo anual
- consumo anual estimado se conserva correctamente
- balance express conserva `energy_kWh = self_consumed_kWh + exported_kWh`
- balance express conserva `demand_energy_kWh = self_consumed_kWh + grid_energy_kWh`
- costo promedio por kWh calcula costo sin FV, costo con FV y ahorro
- costo promedio cero no genera ahorro monetario artificial
- consumo cero no produce division entre cero
- clasificacion GDMTO si demanda contratada es menor a 100 kW
- clasificacion GDMTH si demanda contratada es mayor o igual a 100 kW
- costo por periodo de recibo usa consumo kWh por precio medio MXN/kWh
- historico anual cuando hay 12 meses o 6 bimestres capturados
- proyeccion anual cuando hay menos periodos capturados
- ahorro estimado usa la generacion FV anual actual
- demanda cargada por archivo sigue pasando las pruebas actuales
- la pestana Diagnostico solar sigue funcionando sin depender de consumo rapido

## 13. Validaciones estandar

Para esta auditoria solo se modifica documentacion, por lo que no es necesario ejecutar pytest.

Validaciones estandar de implementacion:

- no mostrar JSON ni tracebacks al usuario
- no agregar dependencias nuevas
- no modificar NASA POWER
- no modificar formulas solares
- no modificar formulas GDMTH cuando se trabaje solo en ahorro express
- mantener keys estables en widgets y graficas
- mantener la Etapa 1 usable aunque el usuario no ingrese consumo
- mantener fuera de Etapa 2: BESS, respaldo, ROI, payback, cashflow, costo de inaccion y analisis financiero avanzado

